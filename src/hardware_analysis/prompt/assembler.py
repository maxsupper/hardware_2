"""Prompt 组装器 — 阶段5.

三段式任务提示词: ①角色指令(roles/*.yaml) ②任务指令(规则束+输入引用+约束) ③输出契约。
规则束按阶段懒加载且过 budget 校验；输出契约描述来自 models。
"""
from __future__ import annotations
import json, sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import yaml

from hardware_analysis.config import Config
from hardware_analysis.flows.rule_loader import load_stage_bundle

ROLES = Path("roles")
RULES = Path("rules/rules.json")

CONTRACT_DESC = {
    "hw_search": "输出 JSON=g0_sources: {ics:{位号:{model,ic_type,manual_path,status(FOUND/PARTIAL/MISSING),attempted_sources[]}}}",
    "hw_prep": "输出 JSON=prep 事实数据（确定性工具主产出，LLM 仅兜底歧义器件分类）",
    "hw_analyze": "输出 JSON=evidence: findings[{id,severity(CRITICAL/WARNING/OK/INFERRED/UNVERIFIED),confidence,object,result,source_refs[](EDN行号/手册页)}] + coverage",
    "hw_write": "输出 JSON=report: 三字段 findings[]/tables[](title,columns,rows)/narrative{}",
    "hw_auditor": "输出 JSON=audit: gates[{id,status,expected,actual}] + 缺项清单 + 修正建议",
    "hw_master": "输出 JSON=diagnosis: hypotheses[{rank,probability,location,steps[],evidence_refs,confidence}]",
}


def assembler(agent: str, stage: str, inputs: list[str],
              rules_json: str | Path = RULES, cfg: Config | None = None) -> dict:
    cfg = cfg or Config()
    role = yaml.safe_load((ROLES / f"{agent}.yaml").read_text(encoding="utf-8"))
    bundle = load_stage_bundle(rules_json, stage)
    rule_ids = "、".join(bundle["rule_ids"][:99]) or "-"
    in_refs = "\n".join(f"  - {i}" for i in inputs) or "  - (无)"
    contract = CONTRACT_DESC.get(agent, "输出 JSON（见契约模型）")

    prompt = f"""# {agent} 任务

## ① 角色指令
role: {role['role']}
goal: {role['goal']}
backstory: {role['backstory']}
铁律(MUST/MUST NOT): 严格按其角色要求；禁止经验推断、禁止用规则文档描述替代手册原文；不确定→UNVERIFIED。

## ② 任务指令（阶段 {stage}）
【规则束】(本阶段启用，ID 清单: {rule_ids})
【输入引用】
{in_refs}
【执行要求】引用手册必须带页码/表格号；结论带 EDN 行号；逐项独立；全 JSON 输出。

## ③ 输出契约（必须是 JSON）
{contract}
"""
    est = {"tokens": max(1, (len(prompt) + 2000) // 2), "chars": len(prompt)}
    budget = {
        "rule_ids": len(bundle["rule_ids"]), "bundle_chars": bundle["chars"],
        "cap": bundle["cap"], "under_budget": bundle["under_budget"], "est": est,
    }
    return {"agent": agent, "stage": stage, "prompt": prompt,
            "budget": budget, "contract": contract}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("agent"); ap.add_argument("--stage", default="PH-4")
    a = ap.parse_args()
    r = assembler(a.agent, a.stage, inputs=["storge/project/<P>/B_prep/refdes_function_map.json"])
    print(r["budget"])
    print(r["prompt"][:600])
