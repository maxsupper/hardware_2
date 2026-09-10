"""位号↔BOM↔功能映射生成器 — 阶段3a 产物 D.

输入: B_prep/global_components.json(EDN) + B_prep/bom_entries.json(BOM)
合并规则: refdes 主键；双源都在→合并；仅在其一→标记缺失来源；型号不同→冲突记录。
function 层一期留空（由 E 阶段分析渐进填充）。
用法: python -m hardware_analysis.tools.refdes_map <B_prep_dir>
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("b_prep_dir", help="含 global_components.json / bom_entries.json 的目录")
    args = ap.parse_args()
    d = Path(args.b_prep_dir)
    comps = json.loads((d / "global_components.json").read_text(encoding="utf-8"))
    bom = json.loads((d / "bom_entries.json").read_text(encoding="utf-8")).get("entries", {})

    comps = {k: v for k, v in comps.items() if k}  # 去空 refdes

    components = []
    conflicts, bom_only, edn_only = [], [], []
    for rd in sorted(set(comps) | set(bom)):
        c = comps.get(rd, {})
        b = bom.get(rd, {})
        c_model, b_model = c.get("model", ""), b.get("mfg_model", "") or b.get("model_name", "")
        if rd in comps and rd in bom and c_model and b_model and c_model != b_model:
            conflicts.append({"refdes": rd, "edn_model": c_model, "bom_model": b_model})
        if rd in bom and rd not in comps:
            bom_only.append(rd)
        if rd in comps and rd not in bom:
            edn_only.append(rd)
        components.append({
            "refdes": rd,
            "identity": {
                "bom_name": b.get("name", ""),
                "model": b_model or c_model or "",
                "value": b.get("name", ""),
                "package": b.get("package", ""),
                "mfg": b.get("mfg", ""),
                "mfg_model": b.get("mfg_model", ""),
                "qty": b.get("qty", ""),
                "grade": b.get("grade", ""),
            },
            "function": {"category": "", "role": "", "description": "", "nets": [], "power_domains": []},
            "manual": {"status": "UNKNOWN", "path": ""},
            "provenance": {
                "in_edn": rd in comps,
                "in_bom": rd in bom,
                "edn_model": c_model,
                "bom_row": b.get("bom_row", ""),
                "bom_file": b.get("bom_file", ""),
                "match": "both" if (rd in comps and rd in bom) else ("edn_only" if rd in comps else "bom_only"),
                "confidence": "DEFINITE",
            },
        })

    out = {
        "schema_version": "1.0", "kind": "refdes_function_map",
        "product": "", "status": "WARNING" if (conflicts or bom_only or edn_only) else "PASS",
        "components": components,
        "index_by_category": {},
        "stats": {
            "total": len(components), "both": len(components) - len(bom_only) - len(edn_only),
            "bom_only": len(bom_only), "edn_only": len(edn_only),
            "model_conflicts": len(conflicts),
        },
        "conflicts": conflicts, "bom_only": bom_only, "edn_only": edn_only[:20],
    }
    (d / "refdes_function_map.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"映射: total={out['stats']['total']} both={out['stats']['both']} "
          f"bom_only={len(bom_only)} edn_only={len(edn_only)} 型号冲突={len(conflicts)}")
    if conflicts:
        print("  冲突样例:", conflicts[:3])


if __name__ == "__main__":
    main()
