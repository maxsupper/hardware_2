"""CrewAI Agent/任务 接线 — 阶段5（v2：自身归一化 + 契约校验，绕开慢速修复循环）.

流程: 角色/任务组装 → Crew kickoff 得原始文本 → normalize_output 确定性归一
      (JSON提取/枚举对齐/空值规范) → Pydantic 契约校验 → 产物 JSON。
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import yaml

from hardware_analysis.config import Config
from hardware_analysis.prompt.assembler import assembler, CONTRACT_DESC
from hardware_analysis.models.contracts import (G0Sources, EvidenceDoc, GateResult,
                                                SummaryDoc, ReportDoc)

CONTRACT_MODEL = {
    "hw_search": G0Sources, "hw_analyze": SummaryDoc,
    "hw_write": ReportDoc, "hw_auditor": GateResult,
}

# 枚举宽容映射（模型偶尔用 raw 原词变小写/带空格）
ENUM_RESOLVE = {"found_partial": "FOUND_PARTIAL", "truly_missing": "TRULY_MISSING",
                "warning": "WARNING", "critical": "CRITICAL", "unverified": "UNVERIFIED",
                "inferred": "INFERRED", "definite": "DEFINITE", "likely": "LIKELY",
                "uncertain": "UNCERTAIN", "unknown": "UNKNOWN"}


def _extract_json(text: str):
    """从模型输出提取首个完整 JSON 对象（容忍 markdown 围栏/前后噪音）。"""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|```\s*$", "", t, flags=re.M)
    st, en, depth, in_str = -1, -1, 0, False
    for i, c in enumerate(t):
        if c == '"' and (i == 0 or t[i-1] != "\\"):
            in_str = not in_str
        if in_str:
            continue
        if c == "{":
            if depth == 0:
                st = i
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                en = i
                break
    if st < 0 or en <= st:
        raise ValueError("未找到 JSON 对象")
    return json.loads(t[st:en+1])


def _norm(v):
    if isinstance(v, dict):
        return {k: _norm(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_norm(x) for x in v]
    if isinstance(v, str):
        s = v.strip()
        low = s.lower().replace("-", "_").replace(" ", "_")
        if low in ENUM_RESOLVE:
            return ENUM_RESOLVE[low]
        if low in ("", "null", "none", "n_a", "na"):
            return None
        return s
    if v is None:
        return None
    return v


def normalize_output(model_cls, raw_text: str):
    """归一化并契约化校验；返回 (pydantic_obj, errors) 。"""
    obj = _extract_json(raw_text)
    obj = _norm(obj)
    try:
        return model_cls.model_validate(obj), []
    except Exception as e:
        return None, [str(e)[:200]]


def make_agent(name: str, cfg: Config | None = None):
    cfg = cfg or Config()
    role = yaml.safe_load((Path("roles") / f"{name}.yaml").read_text(encoding="utf-8"))
    crewai = __import__("crewai", fromlist=["LLM"])
    llm = crewai.LLM(model=f"openai/{cfg.llm['models'].get(role.get('model', 'flash'))}",
                     base_url=cfg.llm["baseUrl"], api_key=cfg.llm_api_key,
                     temperature=0, timeout=120)
    return crewai.Agent(role=role["role"], goal=role["goal"], backstory=role["backstory"],
                        llm=llm, allow_delegation=False, verbose=False)


def make_task(agent_name: str, stage: str, inputs: list[str], ws, cfg: Config | None = None, tools=None):
    """任务：description=组装提示词；输出为原始文本（不用内置 pydantic 以免慢修复）。"""
    cfg = cfg or Config()
    p = assembler(agent_name, stage, inputs, cfg=cfg)
    agent = make_agent(agent_name, cfg)
    crewai = __import__("crewai", fromlist=["Task"])
    return crewai.Task(description=p["prompt"], expected_output=CONTRACT_DESC.get(agent_name, "JSON"),
                       agent=agent, max_retry_limit=1, tools=tools or [])


def run_crew(tasks, ws, cfg: Config | None = None):
    """顺序跑 Crew，返回各任务 (输出字符串)。不克隆内置契约校验。"""
    crewai = __import__("crewai", fromlist=["Crew", "Process"])
    crew = crewai.Crew(agents=[t.agent for t in tasks], tasks=tasks,
                       process=crewai.Process.sequential, verbose=False)
    res = crew.kickoff()
    outs = [o.raw if hasattr(o, "raw") else str(o) for o in res.tasks_output]
    # 记录事件（web）
    ev = {"type": "task_completed", "phase": getattr(tasks[0], "_phase", "PH"),
          "agent": tasks[0].agent.role, "status": "done", "n_tasks": len(tasks)}
    ws.log(ev)
    return outs
