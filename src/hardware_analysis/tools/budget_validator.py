"""budget_validator — 上下文预算强制（512K 硬顶不可破 / 规则束≤40K / 输入≤400K）.

确定性估算（字符数近似 token；中文≈1字/token，偏保守）。
用法: python -m hardware_analysis.tools.budget_validator --rules text --input text ...
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hardware_analysis.config import Config, HARD_CONTEXT_LIMIT


def est_tokens(obj) -> int:
    if isinstance(obj, (dict, list)):
        s = json.dumps(obj, ensure_ascii=False)
    else:
        s = str(obj)
    return max(1, (len(s) + 1) // 2 + (len(s) // 6))  # 中文≈1字/token, 粗略偏保守


def validate(rules_text="", input_texts=(), fixed=3_000) -> dict:
    cfg = Config()
    rule_bundle = est_tokens(rules_text)
    data = sum(est_tokens(t) for t in input_texts)
    total = fixed + rule_bundle + data
    caps = {
        "rule_bundle_tokens": cfg.rule_bundle_tokens(),
        "input_hard_cap": int(cfg.budget["input_hard_cap"]),
        "context_total": HARD_CONTEXT_LIMIT,          # 512K，不可破
    }
    checks = []
    checks.append({"id": "BUD-01", "status": "PASS" if rule_bundle <= caps["rule_bundle_tokens"] else "FAIL",
                   "expected": f"规则束≤{caps['rule_bundle_tokens']}", "actual": f"{rule_bundle}"})
    checks.append({"id": "BUD-02", "status": "PASS" if data <= caps["input_hard_cap"] else "FAIL",
                   "expected": f"输入≤{caps['input_hard_cap']}", "actual": f"{data}"})
    checks.append({"id": "BUD-03", "status": "PASS" if total <= caps["context_total"] else "FAIL",
                   "expected": f"总上下文≤{caps['context_total']}(512K硬顶)", "actual": f"{total}"})
    ok = all(c["status"] == "PASS" for c in checks)
    return {"schema_version": "1.0", "kind": "budget_check", "status": "PASS" if ok else "FAIL",
            "estimates": {"fixed": fixed, "rule_bundle": rule_bundle, "data": data, "total": total},
            "caps": caps, "checks": checks}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules", default="", help="规则束文本")
    ap.add_argument("--input", action="append", default=[], help="输入数据(可多个)")
    args = ap.parse_args()
    r = validate(rules_text=args.rules, input_texts=args.input)
    print("status:", r["status"], "| estimates:", r["estimates"])
    for c in r["checks"]:
        print(f"  [{c['status']}] {c['id']}: {c['expected']} actual={c['actual']}")


if __name__ == "__main__":
    main()
