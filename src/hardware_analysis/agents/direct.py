"""direct.py — 轻量直连调用（短 prompt + 直连 llm + 归一化契约）.

Crew 包装在本网关长结构化 prompt 下开销大；批量短调用更稳更快。
仍走 角色(精简) + 契约模型，输出归一化后过 Pydantic 校验。
"""
from __future__ import annotations
import json, re, sys, time
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


_RETRY_HTTP = {429, 500, 502, 503, 504}
_FATAL_HTTP = {400, 401, 403}


def _is_retryable(err: str) -> bool:
    """错误是否值得重试（PF-009）：读超时/空响应/契约校验失败/HTTP 429&5xx → True；
    HTTP 400/401/403（及其它 HTTP 状态）→ False。"""
    s = str(err or "")
    m = re.search(r"HTTP\s+(\d{3})", s)
    if m:
        code = int(m.group(1))
        return code not in _FATAL_HTTP and code in _RETRY_HTTP
    low = s.lower()
    if ("read operation timed out" in low or "timed out" in low
            or "timeouterror" in low or "urlerror" in low
            or "connection reset" in low or "remote end closed" in low
            or "connection refused" in low):
        return True
    if s.startswith("空响应"):
        return True
    # Pydantic/契约校验失败（normalize_output 返回 obj=None）也算可重试
    return True


def llm_json(agent: str, prompt: str, model_cls, cfg: Config | None = None,
             timeout: int | None = None, system_footer: str = "", rules_text: str = "",
             retries: int = 0, retry_backoff: float = 2.0) -> tuple:
    """直连 llm.call，返回 (normalized_obj, errors, seconds)。

    - ``timeout=None`` → cfg.llm.request_timeout（默认 180）；显式传入以传入为准。
    - ``retries`` = **额外**尝试次数（0=旧行为，仅一次）；可重试错误按指数退避重试。
    - 可重试：socket 读超时/TimeoutError/URLError、空响应、Pydantic 校验失败、HTTP 429/500/502/503/504。
    - 不可重试：HTTP 400/401/403。
    - 每次尝试打印日志（attempt/错误/耗时）。
    启用环境变量 HARDWARE_MOCK=1 时走模板 mock（快速验证，不调网关）。
    rules_text：本阶段规则束渲染文本（默认空 → 行为与旧版完全一致），置于 BRIEF_ROLE 之后、system_footer 之前。
    """
    import os
    if os.environ.get("HARDWARE_MOCK") == "1":
        return _mock(agent, model_cls, prompt), [], 0.0
    cfg = cfg or Config()
    if timeout is None:
        timeout = int(cfg.llm.get("request_timeout", 180))
    # 直接 HTTP 调用 OpenAI 兼容接口（不经 crewai.LLM：它在长 system 提示下会返回空 content）
    max_tok = int(cfg.llm.get("max_tokens", 4096))
    sys_msg = BRIEF_ROLE.get(agent, "输出 JSON 结果。") + " 只输出 JSON，不要任何解释或 Markdown 围栏。"
    if rules_text:
        sys_msg += "\n\n【本阶段规则束（必须遵守）】\n" + rules_text
    sys_msg += system_footer
    attempts = max(1, int(retries) + 1)
    t0 = time.time()
    errors: list[str] = []
    for n in range(1, attempts + 1):
        t = time.time()
        try:
            raw = _http_chat(cfg, [{"role": "system", "content": sys_msg},
                                   {"role": "user", "content": prompt}], max_tok, timeout)
            obj, errs = normalize_output(model_cls, str(raw))
        except Exception as e:
            obj, errs = None, [str(e)[:150].strip() or type(e).__name__]
        dt = round(time.time() - t, 1)
        if obj is not None:
            print(f"[llm_json] {agent} attempt {n}/{attempts} OK ({dt}s)", file=sys.stderr)
            return obj, [], round(time.time() - t0, 1)
        err = errs[0] if errs else "未知错误"
        errors.append(f"attempt {n}/{attempts}: {err}")
        print(f"[llm_json] {agent} attempt {n}/{attempts} failed ({dt}s): {str(err)[:140]}",
              file=sys.stderr)
        if n >= attempts or not _is_retryable(err):
            break
        time.sleep(min(retry_backoff ** n, 10))
    return None, errors, round(time.time() - t0, 1)


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


def _mock(agent: str, model_cls, prompt: str = ""):
    """快速 mock：按契约给最小模板（供确定性流程/Gate/端到端验证）。

    ``prompt`` 仅供 BatchVerdict 分支解析待判定章节标题/原文；其余分支忽略，行为不变。
    """
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
    elif kind == "BatchVerdict":
        d = _mock_batch_verdict(prompt)
    elif kind == "ChipFunctionVerdict":
        d = _mock_chip_function(prompt)
    else:
        d = {}
    return model_cls.model_validate(_j.loads(_j.dumps(d)))


# --------------------------------------------------------------------------- #
# BatchVerdict mock：按标题关键词做确定性、保守的硬件约束判定
# --------------------------------------------------------------------------- #
# 丢弃优先：标题命中这些关键词 → is_hardware_constraint=False（并给 drop_reason）
# drop_reason 仅取噪声白名单（与 datasheet_to_rules.DROP_REASONS 对齐，descriptive 已废弃）
_MOCK_DROP_RULES = (
    (("版本", "修订"), "revision_history"),
    (("目录",), "toc"),
    (("术语", "缩略"), "terminology"),
    (("产品标识", "标识", "订购", "订货", "包装", "marking"), "ordering"),
    (("法律", "声明", "版权"), "legal"),
    (("框图", "结构图", "map"), "figure_caption"),
)
_MOCK_DROP_REASONS = ("revision_history", "toc", "toc_entry", "terminology", "ordering",
                      "packaging", "legal", "figure_caption", "cover")
# 标题硬护栏（与 datasheet_to_rules.MUST_KEEP_TITLE_RE 对齐）：命中即一律保留
_MOCK_MUST_KEEP_RE = re.compile(
    r"特性|电气|指标|参数|时序|复用|拓扑|布线|PCB|阻抗|等长|引脚|信号|电源|时钟|复位|"
    r"ESD|EMC|温度|热|校准|绝对最大|推荐工作|限制|约束|处理方式|使用|建议|指导|准则|要求",
    re.I,
)
# 保留关键词：标题命中任一 → 保守视为硬件约束
_MOCK_KEEP_KW = (
    "引脚", "信号", "电气", "电压", "电流", "电源", "供电", "电容", "时序", "复位",
    "时钟", "布线", "阻抗", "拓扑", "交换", "接口", "复用", "不使用", "校准", "pcb",
    "esd", "emc", "热", "温度", "启动", "配置", "微带", "带状", "残桩", "串扰",
    "回流", "叠层", "封装", "扣合", "装焊", "尺寸", "serdes", "mio", "io", "lsd",
    "额定", "最大", "特性",
)
_MOCK_CATEGORIES = (
    (("不使用",), "unused_pin"),
    (("启动", "配置"), "boot_config"),
    (("引脚", "信号"), "pin_definition"),
    (("电气", "电压", "电流", "额定", "最大", "dc", "ac"), "electrical"),
    (("电源", "供电", "电容"), "power"),
    (("时序", "复位", "时钟"), "timing"),
    (("拓扑", "交换"), "topology"),
    (("布线", "阻抗", "pcb", "叠层", "残桩", "串扰", "回流", "微带", "带状"), "pcb"),
    (("热", "温度"), "thermal"),
    (("esd", "emc"), "esd"),
    (("接口", "serdes", "mio"), "peripheral"),
)


def _mock_excerpts(text: str, limit: int = 3, cap: int = 200) -> list:
    """从章节原文按句子切出前 limit 条摘录（确定性、去噪）。"""
    import re as _re
    out = []
    for seg in _re.split(r"(?<=[。；\n])", str(text or "")):
        s = _re.sub(r"\s+", " ", seg).strip()
        if len(s) < 6:
            continue
        out.append(s[:cap])
        if len(out) >= limit:
            break
    return out


def _mock_section_verdict(num: str, title: str, text: str) -> dict:
    """单章标题关键词 → 保守判定（可复现）；无白名单噪声理由 → 一律保留。"""
    tl = str(title or "").replace(" ", "").lower()
    drop_reason = ""
    for kws, reason in _MOCK_DROP_RULES:
        if any(kw in tl for kw in kws):
            drop_reason = reason
            break
    keep = not drop_reason
    override = ""
    if _MOCK_MUST_KEEP_RE.search(str(title or "")):
        keep, drop_reason, override = True, "", "title_guard"
    elif not keep and drop_reason not in _MOCK_DROP_REASONS:
        keep, drop_reason, override = True, "", "reason_not_whitelisted"
    cats = []
    if keep:
        for kws, cat in _MOCK_CATEGORIES:
            if any(kw in tl for kw in kws) and cat not in cats:
                cats.append(cat)
    return {
        "num": str(num),
        "is_hardware_constraint": bool(keep),
        "categories": cats if keep else [],
        "constraints": _mock_excerpts(text) if keep else [],
        "must": [], "must_not": [], "params": {},
        "drop_reason": "" if keep else drop_reason,
        "override": override,
    }


def _mock_batch_verdict(prompt: str) -> dict:
    """解析 prompt 中的 <<<SECTION ...>>> 标记并逐章给出确定性判定。"""
    import re as _re
    secs = []
    pat = _re.compile(
        r"<<<SECTION num=(?P<num>[^\s>]+) title=(?P<title>.*?) line=(?P<line>\d+)>>>\n"
        r"(?P<text>.*?)<<<END num=[^>]*>>>", _re.S)
    for m in pat.finditer(str(prompt or "")):
        secs.append(_mock_section_verdict(m.group("num"), m.group("title"), m.group("text")))
    return {"sections": secs}

def err_to_str(errs) -> str:
    return "；".join(errs)[:220]


# --------------------------------------------------------------------------- #
# ChipFunctionVerdict mock：按 edn_symbol|model 关键词做确定性、保守的功能判定
# --------------------------------------------------------------------------- #
# 顺序匹配，命中即止（保守）；未命中一律 role="other"（“功能未确认”），不得影响其它契约 mock
_MOCK_CHIP_FUNCTION_RULES = (
    (("MAX32",), "接口", "interface", "RS-232 电平转换收发器"),
    (("MAX34", "SIT3490"), "接口", "interface", "RS-485 收发器"),
    (("TPS7", "BL93"), "电源", "power", "LDO 线性稳压器"),
    (("IS66", "SY8"), "电源", "power", "DC-DC 电源转换器"),
    (("XC6S", "XC7", "FPGA", "CPLD"), "主控", "mcu_soc", "FPGA/CPLD 可编程逻辑"),
    (("MS4553", "MS2574"), "接口", "interface", "电平转换器"),
    (("LT8918",), "接口", "interface", "HDMI 桥接芯片"),
    (("STC1",), "主控", "mcu_soc", "MCU 微控制器"),
    (("DCDC",), "电源", "power", "DC-DC 电源转换器"),
    (("PMIC",), "电源", "power", "PMIC 电源管理芯片"),
    (("LPDDR", "DDR"), "存储", "memory", "LPDDR/DDR 内存"),
    (("EMMC", "INAND"), "存储", "memory", "eMMC/NAND 存储"),
    (("GD25", "W25Q", "FLASH"), "存储", "memory", "SPI NOR Flash 存储"),
    (("SOC",), "主控", "soc", "主控 SoC"),
    (("ETHERNET",), "接口", "interface", "以太网 PHY/MAC"),
    (("PSM", "TVS", "ESD"), "保护", "protection", "TVS/ESD 静电保护阵列"),
    (("PMOS", "NMOS", "MOSFET"), "开关", "switch", "MOSFET 开关管"),
)


def _mock_chip_function(prompt: str) -> dict:
    """从 prompt 解析 model/edn_symbol，按关键词给确定性保守判定（可复现）。"""
    import re as _re
    txt = str(prompt or "")
    m = _re.search(r"edn_symbol=(\S+)\s+model=(.*)", txt)
    sym = m.group(1).strip() if m else ""
    model = m.group(2).splitlines()[0].strip() if m else ""
    key = f"{sym}|{model}".upper()
    for kws, cat, role, desc in _MOCK_CHIP_FUNCTION_RULES:
        if any(kw in key for kw in kws):
            return {"category": cat, "role": role, "description": desc,
                    "confidence": "LIKELY", "reason": "mock 关键词判定"}
    name = model or sym or "未知芯片"
    return {"category": "其他", "role": "other", "description": f"{name}（功能未确认）",
            "confidence": "UNCERTAIN", "reason": "mock 未命中关键词"}
