"""manual_index 生成器 — PH-1 产物（位号→手册存放路径 表格）.

输入: BOM 清单（先经 bom_parse 产出 bom_entries.json，支持 Word/Excel）
逻辑: 取 BOM 中所有 U*（IC）→ 按型号去重 → refbook 本地检索（型号模糊匹配）
      → 命中记 manual_path、未命中记 TRULY_MISSING（后续 Tavily 兜底由 hw_search agent 补）
输出: manual_index.json（entries 键 = "板::位号"；字段 model/ic_type/manual_path/status/attempted_sources）
说明: ic_type（SINK/PASS_THRU/POWER_SRC）由 PH-1 的 LLM 判定回填；本工具先置 UNKNOWN。
用法: python -m hardware_analysis.tools.manual_index <bom_entries.json> --out <PH-1_manual>/manual_index.json [--refbook storge/refbook]
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
