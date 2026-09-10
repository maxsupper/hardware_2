"""位号↔BOM↔功能映射 — 阶段3a 产物 D（v2：按板配对 + DNP 标注）.

输入: B_prep/global_components.json(板级: "板::位号") + bom_entries.json(含 board)
规则(用户确认):
  - 身份 = (板, 位号)；A_EDN ↔ A_BOM、B_EDN ↔ B_BOM
  - EDN 有、该板 BOM 无 → 不装(DNP)，populated=False，不算缺项
  - EDN 符号名(cellRef) 与 BOM 料号是不同标识，不判冲突
用法: python -m hardware_analysis.tools.refdes_map <B_prep_dir>
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("b_prep_dir")
    args = ap.parse_args()
    d = Path(args.b_prep_dir)
    gcomp = json.loads((d / "global_components.json").read_text(encoding="utf-8"))
    bom = json.loads((d / "bom_entries.json").read_text(encoding="utf-8")).get("entries", {})

    # 按板拆 BOM
    bom_by_board: dict[str, dict] = {}
    for _k, b in bom.items():
        rd = b.get("refdes") or _k.split("::")[-1]
        bom_by_board.setdefault(b.get("board", "X"), {})[rd] = b

    components, dnp_list, bom_only_list = [], [], []
    per_board = {}
    for key, c in gcomp.items():
        board, refdes = (key.split("::", 1) + [""])[:2]
        bb = bom_by_board.get(board, {})
        b = bb.get(refdes, {})
        edn_symbol = c.get("model", "")
        bom_pn = b.get("mfg_model", "") or b.get("model_name", "")
        populated = bool(b)
        per_board.setdefault(board, {"both": 0, "dnp": 0, "bom_only": 0})
        if populated:
            per_board[board]["both"] += 1
        else:
            per_board[board]["dnp"] += 1
            dnp_list.append(f"{board}::{refdes}")
        components.append({
            "id": key, "board": board, "refdes": refdes,
            "identity": {
                "bom_name": b.get("name", ""), "model": bom_pn or edn_symbol or "",
                "package": b.get("package", ""), "mfg": b.get("mfg", ""),
                "mfg_model": b.get("mfg_model", ""), "grade": b.get("grade", ""),
            },
            "function": {"category": "", "role": "", "description": "", "nets": [], "power_domains": []},
            "manual": {"status": "UNKNOWN", "path": ""},
            "provenance": {"in_edn": True, "in_bom": populated, "edn_symbol": edn_symbol,
                           "bom_row": b.get("bom_row", ""), "bom_file": b.get("bom_file", ""),
                           "populated": populated, "match": "both" if populated else "dnp"},
        })

    # BOM 有、EDN 无（按板）
    edn_keys = set(k for k in gcomp)
    for board, bb in bom_by_board.items():
        for rd in bb:
            if f"{board}::{rd}" not in edn_keys:
                bom_only_list.append(f"{board}::{rd}")
                per_board.setdefault(board, {"both": 0, "dnp": 0, "bom_only": 0})["bom_only"] += 1

    out = {
        "schema_version": "1.0", "kind": "refdes_function_map", "product": "",
        "status": "PASS",
        "components": components,
        "dnp": dnp_list, "bom_only": bom_only_list,
        "stats": {"total": len(components), "dnp": len(dnp_list), "bom_only": len(bom_only_list),
                  "per_board": per_board},
    }
    (d / "refdes_function_map.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"映射: total={len(components)} 不装(DNP)={len(dnp_list)} bom_only={len(bom_only_list)}")
    for b, s in per_board.items():
        print(f"  板{b}: both={s['both']} 不装={s['dnp']} bom_only={s['bom_only']}")


if __name__ == "__main__":
    main()
