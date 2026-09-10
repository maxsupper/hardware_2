"""refbook 本地手册库检索 — 阶段3c（对 refbook/datasheet 递归 + 型号模糊匹配）.

匹配策略: 规范化(去除非字母数字/统一大写)后，文件名/目录名与型号做: 完全等于 / 型号含于文件名 / 文件名含型号 / token 重叠评分。
用法: python -m hardware_analysis.tools.refbook_search <model> [--root storge/refbook] [--top 5]
"""
from __future__ import annotations
import argparse, difflib, json, sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

EXTS = (".md", ".pdf", ".txt", ".xlsx", ".docx", ".png", ".jpg")


def norm(s: str) -> str:
    return "".join(ch for ch in str(s).upper() if ch.isalnum())


def score_filename(model: str, path: Path) -> tuple:
    nm = norm(model)
    fn = norm(path.name)
    if not nm:
        return 0, 0
    if fn == nm:
        return 100, 0
    if nm in fn:
        return 80 + min(len(nm) / max(len(fn), 1) * 15, 15), len(fn)
    if fn in nm:
        return 60, len(fn)
    # token 重叠
    mtoks, ftoks = set(nm[:6]), set(fn[:6])
    overlap = len(mtoks & ftoks) / max(len(mtoks), 1)
    return overlap * 50, len(fn)


def search(model: str, root: str | Path = "storge/refbook", top: int = 5,
           max_files: int = 20000) -> list[dict]:
    root = Path(root)
    hits = []
    idx = 0
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in EXTS:
            idx += 1
            if idx > max_files:
                break
            sc, pen = score_filename(model, p)
            if sc >= 40:
                hits.append({"score": round(sc, 1), "path": str(p), "name": p.name,
                             "stem_match": sc >= 70})
    hits.sort(key=lambda h: (-h["score"], len(h["path"])))
    return hits[:top]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--root", default="storge/refbook")
    ap.add_argument("--top", type=int, default=5)
    args = ap.parse_args()
    r = search(args.model, root=args.root, top=args.top)
    print(f"检索 '{args.model}' @ {args.root}: {len(r)} 条")
    for h in r:
        print(f"  [{h['score']:5.1f}] {h['name'][:70]}")


if __name__ == "__main__":
    main()
