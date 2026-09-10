from __future__ import annotations

"""规则束懒加载器 — 阶段4（从 rules.json 按阶段/门禁取规则）。

只加载当前阶段需要的规则（budget 限定），避免上下文溢出。
"""
import json, re, sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hardware_analysis.config import Config


def _match(rule_id: str, pattern: str) -> bool:
    if pattern.endswith("*"):
        return rule_id.startswith(pattern[:-1])
    return rule_id == pattern


def load_stage_bundle(rules_path: str | Path, stage: str, budget_tokens: int | None = None) -> dict:
    rj = json.loads(Path(rules_path).read_text(encoding="utf-8"))
    stage_cfg = next((p for p in rj["process"] if p["stage"] == stage), None)
    if not stage_cfg:
        return {"stage": stage, "rules": [], "chars": 0, "under_budget": True}
    patterns = stage_cfg.get("rules", [])
    picked = {cid: r for cid, r in rj["rules"].items()
              if any(_match(cid, p) for p in patterns)}
    chars = sum(r.get("chars", 0) for r in picked.values())
    cap = budget_tokens or Config().rule_bundle_tokens()
    under = chars <= cap
    return {"stage": stage, "patterns": patterns, "rule_ids": sorted(picked),
            "rules": picked, "chars": chars, "cap": cap,
            "under_budget": under, "budget_check": "OK" if under else "OVER"}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("stage")
    a = ap.parse_args()
    b = load_stage_bundle("rules/rules.json", a.stage)
    print(f"阶段 {a.stage}: 命中 {len(b['rule_ids'])} 条规则 | {b['chars']}字 / cap {b['cap']} | {b['budget_check']}")
    print("样例:", b["rule_ids"][:8])
