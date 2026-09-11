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

# status/severity 同义词映射（宽松归一，防模型用 pass/fail/high 等）
STATUS_MAP = {
    "ok": "OK", "pass": "OK", "passed": "OK", "good": "OK", "fine": "OK", "normal": "OK",
    "info": "OK", "informational": "OK", "low": "OK", "none": "OK", "no_issue": "OK",
    "warn": "WARNING", "warning": "WARNING", "major": "WARNING", "medium": "WARNING",
    "minor": "WARNING", "caution": "WARNING",
    "fail": "CRITICAL", "failed": "CRITICAL", "error": "CRITICAL", "critical": "CRITICAL",
    "high": "CRITICAL", "severe": "CRITICAL", "blocker": "CRITICAL",
    "unverified": "UNVERIFIED", "unknown": "UNVERIFIED", "na": "UNVERIFIED", "n_a": "UNVERIFIED",
    "inferred": "INFERRED",
}


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


def _norm(v, key=None):
    if isinstance(v, dict):
        return {k: _norm(x, k) for k, x in v.items()}
    if isinstance(v, list):
        return [_norm(x, key) for x in v]
    if isinstance(v, str):
        s = v.strip()
        low = s.lower().replace("-", "_").replace(" ", "_")
        if key == "severity":                       # 只有 finding 的严重度走此表（门禁 status 另由 _coerce_gate_status 处理）
            if low in STATUS_MAP:
                return STATUS_MAP[low]
            if low.upper() in ("CRITICAL", "WARNING", "OK", "INFERRED", "UNVERIFIED"):
                return low.upper()
            return "UNVERIFIED"                     # 未知严重度→保守归为待核
        if low in ENUM_RESOLVE:
            return ENUM_RESOLVE[low]
        if low in ("", "null", "none", "n_a", "na"):
            return None
        return s
    if v is None:
        return None
    return v


def _clamp_strings(o):
    """宽松归一：把超长字符串截到契约上限（detail≤80，其余≤2000），避免因超长被 Pydantic 拒收。"""
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            if isinstance(v, str):
                out[k] = v[:80] if (k == "detail" and len(v) > 80) else (v[:2000] if len(v) > 2000 else v)
            else:
                out[k] = _clamp_strings(v)
        return out
    if isinstance(o, list):
        return [_clamp_strings(x) for x in o]
    return o


def _coerce_narrative(o):
    """narrative 值契约要求 str；模型给对象/数组时序列化为字符串。"""
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            if k == "narrative" and isinstance(v, dict):
                out[k] = {kk: (vv if isinstance(vv, str) else json.dumps(vv, ensure_ascii=False))
                          for kk, vv in v.items()}
            else:
                out[k] = _coerce_narrative(v)
        return out
    if isinstance(o, list):
        return [_coerce_narrative(x) for x in o]
    return o


def _norm_table(t):
    """表格行列对齐：每行列数 = 表头列数（多载少补），防 RF-002 截断告警。"""
    if not isinstance(t, dict):
        return t
    cols = t.get("columns") or []
    rows = t.get("rows") or []
    n = len(cols) or (max((len(r) for r in rows if isinstance(r, list)), default=0))
    fixed = []
    for r in rows:
        r = r if isinstance(r, list) else [r]
        if n:
            r = r[:n] + [""] * (n - len(r)) if len(r) < n else r[:n]
        fixed.append(r)
    t = dict(t); t["rows"] = fixed
    return t


def _normalize_tables(o):
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            if k == "tables" and isinstance(v, list):
                out[k] = [_norm_table(t) for t in v]
            else:
                out[k] = _normalize_tables(v)
        return out
    if isinstance(o, list):
        return [_normalize_tables(x) for x in o]
    return o


# 审计/门禁的 GateStatus 词表（与 Severity 五级不同）
GATE_STATUS_MAP = {
    "ok": "PASS", "pass": "PASS", "passed": "PASS", "good": "PASS", "success": "PASS",
    "fail": "FAIL", "failed": "FAIL", "error": "FAIL", "critical": "FAIL", "blocker": "FAIL",
    "warn": "WARNING", "warning": "WARNING", "unverified": "WARNING", "unknown": "WARNING",
    "blocked": "BLOCKED", "forced_pass": "FORCED_PASS", "forced": "FORCED_PASS",
}


def _coerce_gate_status(o):
    """GateResult 的 status/gate 按 GateStatus 词表归一（把 UNVERIFIED 等映射为 WARNING/PASS）。"""
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            if k == "status" and isinstance(v, str):
                out[k] = GATE_STATUS_MAP.get(v.strip().lower().replace("-", "_"), "PASS")
            elif k == "checks" and isinstance(v, list):
                out[k] = [({**c, "status": GATE_STATUS_MAP.get(str(c.get("status", "")).lower(), c.get("status"))}
                           if isinstance(c, dict) else c) for c in v]
            else:
                out[k] = _coerce_gate_status(v)
        return out
    if isinstance(o, list):
        return [_coerce_gate_status(x) for x in o]
    return o


def _migrate_finding_severity(o):
    """仅对 findings 列表做字段迁移：旧的 status → severity（不改其他位置的 status）。"""
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            if k == "findings" and isinstance(v, list):
                items = []
                for it in v:
                    if isinstance(it, dict) and "severity" not in it and "status" in it:
                        it = {**{kk: vv for kk, vv in it.items() if kk != "status"}, "severity": it["status"]}
                    items.append(_migrate_finding_severity(it))
                out[k] = items
            else:
                out[k] = _migrate_finding_severity(v)
        return out
    if isinstance(o, list):
        return [_migrate_finding_severity(x) for x in o]
    return o


def normalize_output(model_cls, raw_text: str):
    """归一化并契约化校验；返回 (pydantic_obj, errors) 。"""
    obj = _extract_json(raw_text)
    obj = _migrate_finding_severity(obj)      # 先迁移旧字段 status→severity
    obj = _norm(obj)                          # 再统一映射枚举（severity 走严重度表）
    obj = _clamp_strings(obj)
    obj = _coerce_narrative(obj)
    obj = _normalize_tables(obj)
    if getattr(model_cls, "__name__", "") == "GateResult":
        obj = _coerce_gate_status(obj)
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
