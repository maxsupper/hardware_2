"""raw 规则清册提取器 — 阶段1b 产物 B.

逐文件按"节"提取 raw 规则条目，产出清册(利于编号/建索引/反向验证)。
只读 raw，不做修改；幂等可重跑。
用法: python -m scripts.prepare_rules.inventory_raw [--out docs/conflicts/raw_inventory.json]
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 项目根
from scripts.prepare_rules.numbering_dict import RAW_DIR, DERIVE_DIR, SECTION_PATTERNS, load_numbering_dict


BOM = "\ufeff"


def strip_bom(s: str) -> str:
    return s[1:] if s.startswith(BOM) else s


def iter_sections(text: str, pattern: str) -> list[dict]:
    """按正则把文本切成 (标题, 起始行, 结束行)。兼容多分支正则。"""
    lines = strip_bom(text).splitlines()
    starts = []          # (line_no, title)
    pat = re.compile(pattern)
    for i, ln in enumerate(lines, 1):
        m = pat.search(ln)
        if m:
            t = m.group(1).strip() if m.lastindex else ln.strip()
            starts.append((i, t, ln.strip()))
    items = []
    for idx, (ln, title, rawline) in enumerate(starts):
        end = starts[idx + 1][0] - 1 if idx + 1 < len(starts) else len(lines)
        body = "\n".join(lines[ln - 1 : end])
        items.append({
            "title": title,
            "line": ln,
            "end_line": end,
            "raw_head": rawline[:60],
            "body_chars": len(body),
            "body_head": body[:120],
        })
    return items


def inventory_file(rel: str) -> dict:
    p = RAW_DIR / rel
    text = p.read_text(encoding="utf-8", errors="replace")
    base = Path(rel).name
    pattern = SECTION_PATTERNS.get(base, SECTION_PATTERNS["默认"])
    sections = iter_sections(text, pattern)
    return {
        "file": rel,
        "chars": len(text),
        "sections": sections,
        "n_sections": len(sections),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DERIVE_DIR / "raw_inventory.json"))
    args = ap.parse_args()

    nd = load_numbering_dict()
    files = list(nd.raw_map.keys())
    out = {"schema_version": "1.0", "kind": "raw_inventory", "files": {}}
    for rel in files:
        inv = inventory_file(rel)
        inv["suggest_prefix"] = nd.prefix_for_file(rel)
        out["files"][rel] = inv

    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已写: {args.out}")
    for rel, inv in out["files"].items():
        print(f"  {rel}: {inv['n_sections']} 节 (prefix={inv['suggest_prefix'] or '-'})")


if __name__ == "__main__":
    main()
