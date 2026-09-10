"""编号规范化 + 双向映射 — 阶段1b 产物 C.

对 raw 清册逐节赋规范编号，产出 双向映射表 mapping.json。
规则: 稳定ID、可反查、无撞名；hardware-reviewer 按 § 归类到 ROLE/GATE/CT/DP/Q/SA/BLOCK。
用法: python -m scripts.prepare_rules.renumber [--inventory docs/conflicts/raw_inventory.json] [--out docs/conflicts/mapping.json]
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.prepare_rules.numbering_dict import DERIVE_DIR

# hardware-reviewer.md 的节归类（按标题）
HR_CLASSIFIER = [
    (r"^\s*§1\.9|角色定义与架构|机器人.*裁判|委派架构", "ROLE"),
    (r"^\s*§?1\.[0-9]+[ .\t].*(——|─|-).*", "ROLE"),
    (r"The.*$", "ROLE"),  # fallback 未知当 ROLE
]

def classify_hr(title: str) -> str:
    t = title.strip()
    # 关键词快速分类（在 § 编号规则之前）
    if "Agent 规则" in t or t.startswith("## ") and "快速导航" not in t:
        return "DOC"
    if "阻断" in t or "Block" in t:
        return "BLOCK"
    if "适用规则" in t:
        return "GATE"          # §2 的子节表
    if "无缺失自动 PASS" in t or "Question 弹窗配置" in t:
        return "GATE"
    if t.startswith("`") and ".msg`" in t or "msg —" in t:
        return "CT"
    if "路径约定" in t or "命名规范" in t or "Schema" in t or "契约" in t:
        return "CT"
    if "回写" in t or "升级建议" in t or "SUG-" in t or t.startswith("G6"):
        return "LEARN"         # 自学习（二期）
    if "G6 通过标准" in t or "G6 自审清单" in t:
        return "SA"
    # § 编号规则
    if re.match(r"^§?1\.", t): return "ROLE"
    if re.match(r"^§?2\.", t):
        return "BLOCK" if ("阻断" in t or "Block" in t) else "GATE"
    if re.match(r"^§?4\.", t): return "CT"      # 数据契约
    if re.match(r"^§?5\.", t): return "DP"      # 委派规范
    if re.match(r"^§?6\.", t):
        return "SA" if ("自审" in t or "Audit" in t or "门禁" in t) else "Q"
    if re.match(r"^§[0-9]", t): return "PART"
    if re.match(r"^1\.[0-9]+", t): return "ROLE"
    return "OTHER"


def build_mapping(inventory: dict) -> dict:
    mapping = {"schema_version": "1.0", "kind": "numbering_mapping",
               "raw_to_canonical": {}, "canonical_to_raw": {},
               "raw_sections_total": 0, "mapped": 0, "unclassified": 0,
               "duplicate_raw_sections": []}
    counters = {}
    seen_canonical = {}

    for rel, inv in inventory["files"].items():
        prefix = inv.get("suggest_prefix", "")
        secs = inv["sections"]
        src = {"file": rel, "len": inv["chars"], "n": inv["n_sections"]}
        if rel.endswith("hardware-reviewer.md"):
            pass  # HR 用专用归类
        last = None
        for s in secs:
            raw_key = f"{rel}::L{s['line']}"
            mapping["raw_sections_total"] += 1
            if rel.endswith("hardware-reviewer.md"):
                cat = classify_hr(s["title"])
                if cat in ("ROLE", "GATE", "BLOCK", "CT", "DP", "Q", "SA", "PART", "DOC", "LEARN"):
                    counters.setdefault(cat, 0)
                    counters[cat] += 1
                    cid = f"{cat}-{counters[cat]:03d}"
                else:
                    mapping["unclassified"] += 1
                    cid = f"OTHER-{raw_key}"
            else:
                counters.setdefault(prefix, 0)
                counters[prefix] += 1
                cid = f"{prefix}{counters[prefix]:03d}" if prefix else f"RAW-{counters.setdefault('RAW',0):03d}"
            # 防撞名
            if cid in seen_canonical:
                mapping["duplicate_raw_sections"].append({"canonical": cid, "prev": seen_canonical[cid], "now": raw_key})
                cid = f"{cid}x{counters.setdefault('X',0)+1}"
            seen_canonical[cid] = raw_key
            mapping["raw_to_canonical"][raw_key] = cid
            mapping["canonical_to_raw"][cid] = {
                "source": raw_key, "title": s["title"], "line": s["line"],
                "end_line": s["end_line"], "body_chars": s["body_chars"],
                "suggest_prefix": prefix or cat if isinstance(cat := locals().get("cat"), str) else prefix,
            }
            mapping["mapped"] = sum(1 for _ in mapping["canonical_to_raw"])
    mapping["counters"] = counters
    return mapping


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", default=str(DERIVE_DIR / "raw_inventory.json"))
    ap.add_argument("--out", default=str(DERIVE_DIR / "mapping.json"))
    args = ap.parse_args()
    inv = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
    m = build_mapping(inv)
    Path(args.out).write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已写: {args.out}")
    print(f"总节 = {m['raw_sections_total']} | 已映射 = {m['mapped']} | 未归类 = {m['unclassified']} | 撞名 = {len(m['duplicate_raw_sections'])}")
    print("按类分布:", m["counters"])


if __name__ == "__main__":
    main()
