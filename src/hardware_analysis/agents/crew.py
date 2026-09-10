"""CrewAI Agent/任务 接线 — 阶段5.

角色从 roles/*.yaml 生成 Agent（模型=config spark-dsv4）；
任务携带 assembled prompt（规则束+输入+契约），输出用 output_pydantic 强制 JSON；
task_callback/step_callback 写入 run.log.jsonl（供 web SSE 与 agent 计数）。
"""
from __future__ import annotations
import json, sys
from datetime import datetime, timezone
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


def make_agent(name: str, cfg: Config | None = None):
    cfg = cfg or Config()
    role = yaml.safe_load((Path("roles") / f"{name}.yaml").read_text(encoding="utf-8"))
    llm = __import__("crewai", fromlist=["LLM"]).LLM(
        model=f"openai/{cfg.llm['models'].get(role.get('model','flash'))}",
        base_url=cfg.llm["baseUrl"], api_key=cfg.llm_api_key, temperature=0, timeout=180)
    return __import__("crewai", fromlist=["Agent"]).Agent(
        role=role["role"], goal=role["goal"], backstory=role["backstory"],
        llm=llm, allow_delegation=False, verbose=False)


def make_task(agent_name: str, stage: str, inputs: list[str], ws, on_event=None,
              output_model=None, cfg: Config | None = None, tools=None):
    cfg = cfg or Config()
    p = assembler(agent_name, stage, inputs, cfg=cfg)
    agent = make_agent(agent_name, cfg)
    crewai = __import__("crewai", fromlist=["Task"])

    def cb(task_output):
        ev = {"type": "task_completed", "phase": stage, "agent": agent_name,
              "status": getattr(task_output, "output_format", "json") if hasattr(task_output, "output_format") else "done",
              "token": str(getattr(getattr(task_output, "token_usage", None), "total_tokens", ""))}
        ws.log(ev)
        if on_event:
            on_event(ev)

    return crewai.Task(
        description=p["prompt"],
        expected_output=CONTRACT_DESC.get(agent_name, "JSON"),
        agent=agent,
        output_pydantic=output_model or CONTRACT_MODEL.get(agent_name),
        callback=cb,
        max_retry_limit=2,
        tools=tools or [],
    )


def run_crew(tasks, ws, cfg: Config | None = None, budget_tokens: int | None = None):
    """顺序跑一组任务，全部呼到 Crew.kickoff()；返回各任务输出。"""
    crewai = __import__("crewai", fromlist=["Crew"])
    crew = crewai.Crew(agents=[t.agent for t in tasks], tasks=tasks,
                       process=__import__("crewai", fromlist=["Process"]).Process.sequential,
                       output_log_file=str(ws.dir / ".run" / "crew_log.json"),
                       verbose=False)
    res = crew.kickoff()
    return res
