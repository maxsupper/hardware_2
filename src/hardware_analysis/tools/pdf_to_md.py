"""pdf_to_md — PDF → Markdown 文本抽取（供手册检索/阅读统一为 .md）.

优先 pdftotext(poppler，快)；不可用时退化 pdfplumber。
无文字层（扫描件）时返回 ok=False + 提示需 OCR（paddle-ocr/docling）。
用法:
  python -m hardware_analysis.tools.pdf_to_md <a.pdf|dir> [...] [--out-dir D] [--force]
"""
from __future__ import annotations
import argparse, subprocess, sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

MIN_CHARS = 20          # 少于此认为无文字层（扫描件）


def _pdftotext(p: Path) -> str | None:
    try:
        r = subprocess.run(["pdftotext", "-layout", str(p), "-"],
                           capture_output=True, text=True, timeout=180)
        return r.stdout if r.returncode == 0 else None
    except Exception:
        return None


def _pdfplumber(p: Path) -> str | None:
    try:
        import pdfplumber
        with pdfplumber.open(p) as pdf:
            return "\n\n".join((pg.extract_text() or "") for pg in pdf.pages)
    except Exception:
        return None


def convert(pdf: str | Path, out_dir: str | Path | None = None, force: bool = False) -> dict:
    """把单个 PDF 转成同名 .md（默认放同目录）。返回 {src,out,chars,ok,error}。"""
    p = Path(pdf)
    if p.suffix.lower() != ".pdf" or not p.exists():
        return {"src": str(p), "out": None, "chars": 0, "ok": False, "error": "非PDF或不存在"}
    out = (Path(out_dir) if out_dir else p.parent) / (p.stem + ".md")
    if out.exists() and not force:
        return {"src": str(p), "out": str(out), "chars": out.stat().st_size, "ok": True, "error": "已存在(跳过)"}
    text = _pdftotext(p)
    method = "pdftotext"
    if not text:
        text = _pdfplumber(p)
        method = "pdfplumber"
    if text is None:
        return {"src": str(p), "out": None, "chars": 0, "ok": False, "error": "无可用PDF解析器"}
    text = text.strip()
    if len(text) < MIN_CHARS:
        return {"src": str(p), "out": None, "chars": len(text), "ok": False,
                "error": "无文字层(扫描件)，需 OCR（paddle-ocr/docling）"}
    header = f"# {p.name}\n\n> 来源: {p} | 提取: {method}\n\n"
    out.write_text(header + text, encoding="utf-8")
    return {"src": str(p), "out": str(out), "chars": len(text), "ok": True, "error": "", "method": method}


def convert_many(paths: list, out_dir: str | Path | None = None, force: bool = False) -> list[dict]:
    res = []
    for x in paths:
        p = Path(x)
        if p.is_dir():
            for f in sorted(p.glob("*.pdf")):
                res.append(convert(f, out_dir, force))
        elif p.suffix.lower() == ".pdf":
            res.append(convert(p, out_dir, force))
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    rs = convert_many(a.paths, a.out_dir, a.force)
    ok = sum(1 for r in rs if r["ok"])
    print(f"PDF→md: {ok}/{len(rs)} 成功")
    for r in rs:
        tag = "OK " if r["ok"] else "NG "
        print(f"  [{tag}] {Path(r['src']).name} -> {r.get('out') or r['error']}")


if __name__ == "__main__":
    main()
