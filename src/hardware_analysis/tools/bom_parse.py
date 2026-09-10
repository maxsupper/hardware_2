"""BOM(xlsx) 解析器 — 阶段3a 产物 C（确定性工具）.

自动选表(跳过 变更单/封面)、表头模糊映射、位号逗号展开，
产出 per-refdes BOM 条目 JSON。
用法: python -m hardware_analysis.tools.bom_parse <bom.xlsx>... --out <dir>/bom_entries.json
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import openpyxl

HEADER_KEYS = {"位号": "refdes", "公司规格型号": "name", "规格型号": "name", "型号": "model_name",
               "厂家型号": "mfg_model", "厂家": "mfg", "封装形式": "package", "封装": "package",
               "数量": "qty", "等级": "grade", "备注": "note"}


def pick_sheet(wb):
    skip_names = ("变更", "通知", "封面", "说明目录")
    cands = [ws for ws in wb.worksheets]
    # 优先表名含 BOM
    cands.sort(key=lambda ws: (0 if "bom" in ws.title.lower() else 1, ws.title))

    def header_of(ws):
        for row in ws.iter_rows(min_row=1, max_row=12, values_only=True):
            vals = [str(v) if v is not None else "" for v in row]
            if not any("位号" in v for v in vals):
                continue
            if any(k in v for _ in [0] for v in vals for k in ("生产更改", "通知单")):
                continue
            if any("公司规格型号" in v or "规格型号" in v for v in vals):
                return ws, {i: str(v) for i, v in enumerate(vals)}
        return None

    for ws in cands:
        if any(s in ws.title for s in skip_names):
            continue
        h = header_of(ws)
        if h:
            return h
    # 退化：仍找不到
    for ws in cands:
        h = header_of(ws)
        if h:
            return h
    return wb.worksheets[0], None


def col_map(header_row: list) -> dict:
    m = {}
    for i, v in enumerate(header_row):
        s = str(v).strip()
        for key, field in HEADER_KEYS.items():
            if key in s and field not in m:
                m[field] = i
                break
    return m


def parse_bom(path: Path) -> dict:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws, header_vals = pick_sheet(wb)
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    # 表头行（优先用 pick_sheet 精确匹配的表头；退化才重扫）
    header_idx, cmap = None, {}
    if header_vals is not None:
        hv = [str(v) if v is not None else "" for v in header_vals]
        for i, row in enumerate(rows[:12]):
            vals = [str(v) if v is not None else "" for v in row]
            # 逐格相等（容忍空格）
            if all((a.strip() == b.strip()) or (not a.strip() and not b.strip()) for a, b in zip(vals, hv)) \
               or (i == 0 and hv == vals):
                header_idx, cmap = i, col_map(hv)
                break
    if header_idx is None:
        for i, row in enumerate(rows[:12]):
            vals = [str(v) if v is not None else "" for v in row]
            if any("位号" in v for v in vals):
                header_idx, cmap = i, col_map(vals)
                break
    if header_idx is None:
        return {"errors": [f"{path.name}: 未找到表头(位号)"], "entries": {}}
    entries = {}
    for r, row in enumerate(rows[header_idx + 1:], header_idx + 2):
        get = lambda f, d="": (str(row[cmap[f]]) if f in cmap and cmap[f] < len(row) and row[cmap[f]] is not None else d)
        refdes_cell = get("refdes")
        if not refdes_cell.strip():
            continue
        qty = get("qty")
        for rd in [x.strip() for x in refdes_cell.replace("，", ",").split(",") if x.strip()]:
            entries[rd] = {
                "refdes": rd,
                "name": get("name"), "model_name": get("model_name", get("name")),
                "mfg_model": get("mfg_model"), "mfg": get("mfg"), "package": get("package"),
                "qty": qty, "grade": get("grade"), "note": get("note"),
                "bom_row": r, "bom_file": path.name,
            }
    return {"errors": [], "entries": entries}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("boms", nargs="+", help="一个或多个 xlsx")
    ap.add_argument("--out", default=None, help="输出 bom_entries.json 路径")
    args = ap.parse_args()
    merged = {}
    errs = []
    for b in args.boms:
        r = parse_bom(Path(b))
        errs += r["errors"]
        merged.update(r["entries"])
    # 冲突检测：同位号多 BOM 不同型号
    conflicts = [e for e in errs]
    out = Path(args.out) if args.out else Path(args.boms[0]).parent / "bom_entries.json"
    out.write_text(json.dumps({"schema_version": "1.0", "kind": "bom_entries",
                               "entries": merged, "errors": errs,
                               "stats": {"refdes": len(merged), "files": len(args.boms)}},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"BOM 条目: {len(merged)} 位号 | 文件: {args.boms} | errors: {len(errs)}")
    for k in list(merged)[:4]:
        print("  ", k, merged[k]["name"], merged[k].get("mfg_model"))


if __name__ == "__main__":
    main()
