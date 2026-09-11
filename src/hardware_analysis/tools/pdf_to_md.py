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
OCR_PY = str(Path.home() / "ocr-env" / "bin" / "python")   # GPU PaddleOCR 专用环境


def _pdftotext(p: Path) -> str | None:
    try:
        r = subprocess.run(["pdftotext", "-layout", str(p), "-"],
                           capture_output=True, text=True, timeout=180)
        return r.stdout if r.returncode == 0 else None
    except Exception:
        return None


def _render_pdf(p: Path, dpi: int = 200) -> list:
    """PDF → PNG 图片（用于扫描件 OCR）。"""
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="pdfocr_"))
    try:
        subprocess.run(["pdftoppm", "-r", str(dpi), "-png", str(p), str(tmp / "pg")],
                       capture_output=True, timeout=900)
        return sorted(tmp.glob("pg*.png"))
    except Exception:
        return []


def _ocr_images(imgs: list) -> str:
    """调 ~/ocr-env 的 GPU PaddleOCR 识别图片，返回文本（按页分段）。"""
    if not imgs or not Path(OCR_PY).exists():
        return ""
    code = (
        "import sys\n"
        "from paddleocr import PaddleOCR\n"
        "ocr=PaddleOCR(device='gpu:0')\n"
        "out=[]\n"
        "for p in sys.argv[1:]:\n"
        "    try:\n"
        "        r=ocr.predict(p)\n"
        "        t='\\n'.join(r[0].get('rec_texts',[])) if r else ''\n"
        "    except Exception as e:\n"
        "        t='[OCR错误]'+str(e)[:80]\n"
        "    out.append('## '+p.split('/')[-1]+'\\n'+t)\n"
        "print('\\n\\n'.join(out))\n"
    )
    try:
        r = subprocess.run([OCR_PY, "-c", code, *map(str, imgs)],
                           capture_output=True, text=True, timeout=1800)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def _pdfplumber(p: Path) -> str | None:
    try:
        import pdfplumber
        with pdfplumber.open(p) as pdf:
            return "\n\n".join((pg.extract_text() or "") for pg in pdf.pages)
    except Exception:
        return None


def convert(pdf: str | Path, out_dir: str | Path | None = None, force: bool = False,
            use_ocr: bool = True) -> dict:
    """把单个 PDF 转成同名 .md（默认放同目录）。无文字层时自动 OCR（use_ocr）。"""
    p = Path(pdf)
    if p.suffix.lower() != ".pdf" or not p.exists():
        return {"src": str(p), "out": None, "chars": 0, "ok": False, "error": "非PDF或不存在", "method": ""}
    out = (Path(out_dir) if out_dir else p.parent) / (p.stem + ".md")
    if out.exists() and not force:
        return {"src": str(p), "out": str(out), "chars": out.stat().st_size, "ok": True, "error": "已存在(跳过)", "method": "skip"}
    text = _pdftotext(p)
    method = "pdftotext"
    if not text:
        text = _pdfplumber(p)
        method = "pdfplumber"
    text = (text or "").strip()
    if len(text) < MIN_CHARS and use_ocr:                 # 无文字层 → OCR 兜底
        imgs = _render_pdf(p)
        ocr_text = _ocr_images(imgs)
        if len(ocr_text.strip()) >= MIN_CHARS:
            text, method = ocr_text.strip(), "paddleocr(OCR)"
    if len(text) < MIN_CHARS:
        return {"src": str(p), "out": None, "chars": len(text), "ok": False, "method": method,
                "error": "无文字层且OCR不可用/失败（需 paddle-ocr 或补料）"}
    header = f"# {p.name}\n\n> 来源: {p} | 提取: {method}\n\n"
    out.write_text(header + text, encoding="utf-8")
    return {"src": str(p), "out": str(out), "chars": len(text), "ok": True, "error": "", "method": method}


def convert_many(paths: list, out_dir: str | Path | None = None, force: bool = False,
                 use_ocr: bool = True) -> list[dict]:
    res = []
    for x in paths:
        p = Path(x)
        if p.is_dir():
            for f in sorted(p.glob("*.pdf")):
                res.append(convert(f, out_dir, force, use_ocr))
        elif p.suffix.lower() == ".pdf":
            res.append(convert(p, out_dir, force, use_ocr))
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-ocr", action="store_true", help="禁用 OCR 兜底")
    a = ap.parse_args()
    rs = convert_many(a.paths, a.out_dir, a.force, use_ocr=not a.no_ocr)
    ok = sum(1 for r in rs if r["ok"])
    print(f"PDF→md: {ok}/{len(rs)} 成功")
    for r in rs:
        tag = "OK " if r["ok"] else "NG "
        print(f"  [{tag}] {Path(r['src']).name} -> {r.get('out') or r['error']}")


if __name__ == "__main__":
    main()
