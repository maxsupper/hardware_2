"""direct.py — 轻量直连调用（短 prompt + 直连 llm + 归一化契约）.

Crew 包装在本网关长结构化 prompt 下开销大；批量短调用更稳更快。
仍走 角色(精简) + 契约模型，输出归一化后过 Pydantic 校验。
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hardware_analysis.config import Config
from hardware_analysis.agents.crew import normalize_output, ENUM_RESOLVE

BRIEF_ROLE = {
    "hw_search": ("你是芯片数据手册检索专员。只检索不分析：为每个 IC 匹配数据手册，"
                  "本地 refbook 未命中则用 Tavily 联网；缺手册用 TRULY_MISSING；不确定 UNVERIFIED。"),
    "hw_analyze": ("你是硬件原理图验证专家。逐 IC 全维度检查并给五级判定"
                   "(CRITICAL/WARNING/OK/INFERRED/UNVERIFIED)，全部结论带手册页码或 EDN 行号证据；禁止经验推断。"),
    "hw_write": ("你是报告撰写专员。只读输入数据。输出三字段 JSON：findings[](check,severity,detail), "
                 "tables[](title,columns,rows 完整无截断), narrative{}。"),
    "hw_auditor": ("你是质量审计师。只审不改：逐条 SA 门禁核对 + 证据链一致性，输出 gates[](id,status,expected,actual) "
                   "与缺项清单 miss[] 与建议 fix[]。"),
    "hw_master": ("你是硬件故障分析专家。根据现象/位号给出可能性排序假设 "
                  "hypotheses[](rank,probability,location,steps[],evidence_refs,confidence)，并给排查手段。"),
}


def llm_json(agent: str, prompt: str, model_cls, cfg: Config | None = None,
             timeout: int = 60, system_footer: str = "", rules_text: str = "") -> tuple:
    """直连 llm.call 一次，返回 (normalized_obj, errors, seconds)。
    启用环境变量 HARDWARE_MOCK=1 时走模板 mock（快速验证，不调网关）。
    rules_text：本阶段规则束渲染文本（默认空 → 行为与旧版完全一致），置于 BRIEF_ROLE 之后、system_footer 之前。"""
    import os
    if os.environ.get("HARDWARE_MOCK") == "1":
        return _mock(agent, model_cls), [], 0.0
    cfg = cfg or Config()
    # 直接 HTTP 调用 OpenAI 兼容接口（不经 crewai.LLM：它在长 system 提示下会返回空 content）
    max_tok = int(cfg.llm.get("max_tokens", 4096))
    sys_msg = BRIEF_ROLE.get(agent, "输出 JSON 结果。") + " 只输出 JSON，不要任何解释或 Markdown 围栏。"
    if rules_text:
        sys_msg += "\n\n【本阶段规则束（必须遵守）】\n" + rules_text
    sys_msg += system_footer
    t = time.time()
    try:
        raw = _http_chat(cfg, [{"role": "system", "content": sys_msg},
                               {"role": "user", "content": prompt}], max_tok, timeout)
        obj, errs = normalize_output(model_cls, str(raw))
        return obj, errs, round(time.time() - t, 1)
    except Exception as e:
        return None, [str(e)[:150]], round(time.time() - t, 1)


def _http_chat(cfg: Config, messages: list, max_tokens: int, timeout: int) -> str:
    """OpenAI 兼容 /chat/completions 直连（stdlib，无第三方依赖）。返回 content（空则抛错）。"""
    import json as _j, urllib.request, urllib.error
    url = cfg.llm["baseUrl"].rstrip("/") + "/chat/completions"
    body = _j.dumps({"model": cfg.llm["models"]["flash"], "messages": messages,
                     "temperature": 0, "max_tokens": max_tokens}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": "Bearer " + cfg.llm_api_key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = _j.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as he:
        raise RuntimeError(f"HTTP {he.code}: {he.read()[:150].decode('utf-8', 'replace')}")
    msg = d["choices"][0]["message"]
    content = (msg.get("content") or "").strip()
    if not content:
        # 推理模型答在 reasoning 里时退而取之
        content = (msg.get("reasoning_content") or msg.get("reasoning") or "").strip()
    if not content:
        raise RuntimeError(f"空响应(finish={d['choices'][0].get('finish_reason')})")
    return content


def _mock(agent: str, model_cls):
    """快速 mock：按契约给最小模板（供确定性流程/Gate/端到端验证）。"""
    import json as _j
    kind = getattr(model_cls, "__name__", "")
    if kind == "G0Sources":
        d = {"status": "PASS", "ics": {"U6": {"model": "EG4X20BG256I8", "ic_type": "FPGA",
            "manual_path": "storge/refbook/EG4X20.md", "status": "FOUND", "attempted_sources": ["refbook", "tavily"]}}}
    elif kind == "SummaryDoc":
        d = {"kind": "summary", "section": "§5 mock", "scope": "U6", "checks_count": 1,
             "findings": [{"check": "mock 检查", "severity": "OK", "detail": "mock 通过"}]}
    elif kind == "ReportDoc":
        d = {"kind": "report", "findings": [], "tables": [], "narrative": {"mock": "mock 报告"}}
    elif kind == "GateResult":
        d = {"gate": "G6", "status": "PASS", "checks": []}
    elif kind == "ManualNoteVerdict":
        d = {"action": "IGNORE", "compatible_model": "", "reason": "mock", "confidence": "UNCERTAIN"}
    elif kind == "IcTypeVerdict":
        d = {"model": "", "ic_type": "SINK", "channels": [], "reason": "mock"}
    else:
        d = {}
    return model_cls.model_validate(_j.loads(_j.dumps(d)))

def err_to_str(errs) -> str:
    return "；".join(errs)[:220]
