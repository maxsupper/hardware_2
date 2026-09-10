"""refbook 本地手册库检索 — 阶段3c（对 refbook/datasheet 递归 + 型号模糊匹配）.

匹配策略: 规范化(去除非字母数字/统一大写)后，文件名/目录名与型号做: 完全等于 / 型号含于文件名 / 文件名含型号 / token 重叠评分。
用法: python -m hardware_analysis.tools.refbook_search <model> [--root storge/refbook] [--top 5]
"""
from __future__ import annotations
import argparse, difflib, json, re, sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

EXTS = (".md", ".pdf", ".txt", ".xlsx", ".docx", ".png", ".jpg")


def norm(s: str) -> str:
    return "".join(ch for ch in str(s).upper() if ch.isalnum())


def variants(model: str) -> list[str]:
    """型号变体：全量 / 去尾缀(-2, -0001, _Vxx) / 去封装尾数。长→短。"""
    m = str(model or "").upper().strip()
    out = {norm(m)}
    m2 = re.split(r"[-_/\s]", m)[0]
    out.add(norm(m2))
    out.add(norm(re.sub(r"(\d+)$", "", m2)))
    return sorted((v for v in out if len(v) >= 3), key=len, reverse=True)


def _tokens(s: str) -> set:
    return set(re.findall(r"[A-Z0-9]+", str(s).upper()))


def score_filename(model: str, path: Path) -> tuple:
    """型号 vs 文件名：词元命中 > 子串 > 重叠。返回 (score, -len)。"""
    fn = norm(path.name)
    toks = _tokens(path.name)
    best = 0.0
    for v in variants(model):
        if fn == v:
            best = max(best, 100)
        elif v in toks:
            best = max(best, 90 + min(len(v) / max(len(fn), 1) * 8, 8))   # 词元命中
        elif v in fn:
            best = max(best, 58 + min(len(v) / max(len(fn), 1) * 12, 12))   # 子串命中(偏弱)
        else:
            ov = len(set(v[:6]) & set(fn[:6])) / max(len(set(v[:6])), 1)
            best = max(best, ov * 30)                                       # 纯字符重叠 ≤30（不入阈）
    if best >= 58 and any(k in fn for k in ("DATASHEET", "TRM", "MANUAL", "SPEC", "DS", "数据手册", "规格书")):
        best = min(best + 8, 100)                                           # 手册/TRM 优先
    return best, -len(fn)


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
