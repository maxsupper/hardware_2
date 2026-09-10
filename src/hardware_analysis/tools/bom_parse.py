"""BOM 解析器 — 阶段3a 产物 C（确定性工具）.

支持 **Excel(.xlsx/.xlsm)** 与 **Word(.docx)** 两种 BOM 清单（PH-1 输入）。
自动选表(跳过 变更单/封面)、表头模糊映射、位号逗号展开、重复表头行剔除，
产出 per-refdes BOM 条目 JSON（含 board/model）。
用法: python -m hardware_analysis.tools.bom_parse <bom.xlsx|bom.docx>... --out bom_entries.json
"""
from __future__ import annotations
import argparse, json, re, sys, zipfile
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

HEADER_KEYS = {"位号": "refdes", "公司规格型号": "name", "规格型号": "name", "型号": "model_name",
               "厂家型号": "mfg_model", "厂家": "mfg", "封装形式": "package", "封装": "package",
               "数量": "qty", "等级": "grade", "备注": "note"}
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _board_of(name: str) -> str:
    m = re.search(r"-([A-Z])_V\d", name) or re.search(r"-([A-Z])_", name)
    return m.group(1) if m else "X"


def _docx_rows(path: Path) -> list[tuple]:
    """从 docx 表格提取行（zip+XML，无需 python-docx 依赖）。"""
    from xml.etree import ElementTree as ET
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    rows = []
    for tbl in root.iter(_W + "tbl"):
        for tr in tbl.iter(_W + "tr"):
            cells = []
            for tc in tr.findall(_W + "tc"):
                cells.append("".join((t.text or "") for t in tc.iter(_W + "t")).strip())
            rows.append(tuple(cells))
    return rows


def _xlsx_rows(path: Path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    skip_names = ("变更", "通知", "封面", "说明目录")
    cands = sorted(wb.worksheets, key=lambda ws: (0 if "bom" in ws.title.lower() else 1, ws.title))

    def header_row(ws):
        for row in ws.iter_rows(min_row=1, max_row=12, values_only=True):
            vals = [str(v) if v is not None else "" for v in row]
            if any("位号" in v for v in vals) and any("规格型号" in v for v in vals) \
               and not any(("生产更改" in v or "通知单" in v) for v in vals):
                return True
        return False

    ws = next((w for w in cands if not any(s in w.title for s in skip_names) and header_row(w)), None) \
        or next((w for w in cands if header_row(w)), None) or cands[0]
    rows = [tuple("" if v is None else v for v in r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    return rows


def _extract(rows: list[tuple], filename: str) -> dict:
    rows = [tuple("" if v is None else v for v in r) for r in rows]
    header_idx, cmap = None, {}
    for i, row in enumerate(rows[:14]):
        vals = [str(v) for v in row]
        if any("位号" in v for v in vals):
            header_idx, cmap = i, col_map(vals)
            break
    if header_idx is None:
        return {"errors": [f"{filename}: 未找到表头(位号)"], "entries": {}}
    entries = {}
    for r, row in enumerate(rows[header_idx + 1:], header_idx + 2):
        get = lambda f, d="": (str(row[cmap[f]]).strip() if f in cmap and cmap[f] < len(row)
                               and row[cmap[f]] not in (None, "") else d)
        refdes_cell = get("refdes")
        if not refdes_cell:
            continue
        if refdes_cell in ("位号", "序号") or get("name") in ("公司规格型号", "规格型号"):
            continue
        model = get("mfg_model") or get("model_name") or get("name")
        for rd in [x.strip() for x in refdes_cell.replace("，", ",").split(",") if x.strip()]:
            entries[rd] = {
                "refdes": rd, "board": _board_of(filename),
                "name": get("name"), "model_name": get("model_name", get("name")),
                "model": model, "mfg_model": get("mfg_model"), "mfg": get("mfg"),
                "package": get("package"), "qty": get("qty"), "grade": get("grade"),
                "note": get("note"), "bom_row": r, "bom_file": filename,
            }
    return {"errors": [], "entries": entries}


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
    suf = path.suffix.lower()
    if suf in (".xlsx", ".xlsm"):
        rows = _xlsx_rows(path)
    elif suf == ".docx":
        rows = _docx_rows(path)
    else:
        return {"errors": [f"{path.name}: 不支持的 BOM 格式({suf})，仅支持 xlsx/xlsm/docx"], "entries": {}}
    return _extract(rows, path.name)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("boms", nargs="+")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    merged, errs = {}, []
    for b in args.boms:
        r = parse_bom(Path(b))
        errs += r["errors"]
        for k, v in r["entries"].items():
            merged[f'{v["board"]}::{k}'] = v          # 板级唯一键
    out = Path(args.out) if args.out else Path(args.boms[0]).parent / "bom_entries.json"
    out.write_text(json.dumps({"schema_version": "2.0", "kind": "bom_entries",
                               "entries": merged, "errors": errs,
                               "stats": {"refdes": len(merged), "files": len(args.boms)}},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"BOM 条目: {len(merged)} 位号 | 文件: {len(args.boms)} | errors: {len(errs)}")
    for k in list(merged)[:4]:
        print("  ", k, merged[k].get("model"))


if __name__ == "__main__":
    main()
