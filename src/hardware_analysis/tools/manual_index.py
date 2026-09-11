"""manual_index 生成器 — PH-1 产物（位号→手册存放路径 表格）.

输入: BOM 清单（先经 bom_parse 产出 bom_entries.json，支持 Word/Excel）
逻辑: 取 BOM 中所有 U*（IC）→ 按型号去重 → refbook 本地检索（型号模糊匹配）
      → 命中记 manual_path、未命中记 TRULY_MISSING（后续 Tavily 兜底由 hw_search agent 补）
输出: manual_index.json（entries 键 = "板::位号"；字段 model/ic_type/manual_path/status/attempted_sources）
说明: ic_type（SINK/PASS_THRU/POWER_SRC）由 PH-1 的 LLM 判定回填；本工具先置 UNKNOWN。
用法: python -m hardware_analysis.tools.manual_index <bom_entries.json> --out <PH-1_手册检索>/manual_index.json [--refbook storge/refbook]
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hardware_analysis.tools import refbook_search
from hardware_analysis.common.conventions import CONV


def build(bom_entries_path: str | Path, refbook_root: str = "storge/refbook",
          product: str = "") -> dict:
    bom = json.loads(Path(bom_entries_path).read_text(encoding="utf-8")).get("entries", {})
    ics = {k: v for k, v in bom.items() if CONV.is_active(v.get("refdes", ""))}
    # 按型号去重检索（同型号只查一次）
    models = {}
    for k, v in ics.items():
        models.setdefault(v.get("model") or v.get("mfg_model") or v.get("name") or "", []).append(k)
    entries, stats = {}, {"FOUND": 0, "FOUND_PARTIAL": 0, "TRULY_MISSING": 0}
    for model, keys in models.items():
        path, status, score = None, "TRULY_MISSING", 0.0
        if model:
            hits = refbook_search.search(model, refbook_root, top=1)
            if hits:
                score = hits[0]["score"]
                if score >= 70:
                    path, status = hits[0]["path"], "FOUND"
                elif score >= 40:
                    path, status = hits[0]["path"], "FOUND_PARTIAL"
        stats[status] = stats.get(status, 0) + 1
        for k in keys:
            board, _, refdes = k.partition("::")
            entries[k] = {
                "refdes": refdes, "board": board or ics[k].get("board", ""), "model": model,
                "ic_type": "UNKNOWN", "manual_path": path, "status": status,
                "attempted_sources": ([f"refbook:{path}"] if path else ["refbook:no-hit"]),
                "pin_count": 0, "match_score": score,
            }
    return {"schema_version": "2.0", "kind": "manual_index", "product": product,
            "status": "PASS", "entries": entries,
            "stats": {"ic_refdes": len(entries), "unique_models": len(models), **stats,
                      "refbook_root": refbook_root}}


def collect_gaps(b_prep_dir: str | Path) -> dict:
    """从 manual_index.json 收集无手册（待补）清单。"""
    p = Path(b_prep_dir) / "manual_index.json"
    d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"entries": {}}
    gaps = []
    for k, e in d.get("entries", {}).items():
        if not e.get("manual_path"):
            gaps.append({"refdes": k, "model": e.get("model", ""), "status": e.get("status", "TRULY_MISSING"),
                         "action": "PENDING", "compatible_model": None, "manual_path": None, "note": ""})
    return {"kind": "manual_gaps", "product": d.get("product", ""), "total": len(gaps), "gaps": gaps}


def apply_decisions(b_prep_dir: str | Path, decisions: dict, refbook_root: str = "storge/refbook",
                    datasheet_dir: str = "storge/datasheet") -> dict:
    """应用人工决策：IGNORE(→UNVERIFIED) / COMPATIBLE(→同兼容型号) / PROVIDE_FILE(→指定文件)。
    decisions: { "板::位号": {"action":..., "compatible_model":..., "file":...} }
    """
    p = Path(b_prep_dir) / "manual_index.json"
    mi = json.loads(p.read_text(encoding="utf-8"))
    ents = mi.get("entries", {})
    for key, dec in (decisions or {}).items():
        e = ents.get(key)
        if not e:
            continue
        act = str(dec.get("action", "IGNORE")).upper()
        if act == "IGNORE":
            e["status"], e["manual_path"] = "UNVERIFIED", None
            e["note"] = "人工：忽视（无手册，结论标 UNVERIFIED）"
        elif act == "COMPATIBLE":
            cm = dec.get("compatible_model") or ""
            hit = refbook_search.search(cm, refbook_root, top=1) if cm else []
            if hit and hit[0]["score"] >= 40:
                e["manual_path"], e["status"] = hit[0]["path"], "FOUND_COMPATIBLE"
                e["compatible_model"] = cm
                e["note"] = f"人工：按兼容型号 {cm} 处理"
            else:
                e["status"], e["compatible_model"] = "UNVERIFIED", cm
                e["note"] = f"人工：兼容型号 {cm} 未检索到→UNVERIFIED"
        elif act == "PROVIDE_FILE":
            src = dec.get("file") or ""
            sp = Path(src)
            if sp.exists():
                dest = Path(datasheet_dir) / sp.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                import shutil as _sh
                if sp.resolve() != dest.resolve():
                    _sh.copy(sp, dest)
                e["manual_path"], e["status"] = str(dest), "FOUND"
                e["note"] = "人工：补充文件"
            else:
                e["note"] = f"人工：指定文件不存在({src})→保持 UNVERIFIED"
                e["status"] = "UNVERIFIED"
        e["action"] = act
    # 重算 stats
    st = mi.setdefault("stats", {})
    from collections import Counter
    c = Counter(e.get("status") for e in ents.values())
    for k2 in ("FOUND", "FOUND_PARTIAL", "FOUND_COMPATIBLE", "TRULY_MISSING", "UNVERIFIED"):
        st[k2] = c.get(k2, 0)
    p.write_text(json.dumps(mi, ensure_ascii=False, indent=1), encoding="utf-8")
    return st


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("bom_entries")
    ap.add_argument("--out", required=True)
    ap.add_argument("--refbook", default="storge/refbook")
    ap.add_argument("--product", default="")
    args = ap.parse_args()
    r = build(args.bom_entries, args.refbook, args.product)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    s = r["stats"]
    print(f"manual_index: IC={s['ic_refdes']} 唯型号={s['unique_models']} | "
          f"FOUND={s['FOUND']} PARTIAL={s['FOUND_PARTIAL']} MISSING={s['TRULY_MISSING']}")
    for k in list(r["entries"])[:3]:
        e = r["entries"][k]
        print(f"  {k} {e['model']} -> {e['status']} {str(e['manual_path'])[:60]}")


if __name__ == "__main__":
    main()
