#!/usr/bin/env python3
"""datasheet_to_rules — 数据手册「分章 → 批量 LLM 硬件约束判定 → 规则束」。

背景：E2000 ``raw/raw_platmform/E2000/数据手册.md`` 是 173 页 PDF 文本转储，无 markdown
标题；旧派生规则束把「修订记录/目录/术语/产品标识/纯功能描述」等非硬件内容一并收录，
371 条 / 155,520 tokens，既浪费预算又稀释 LLM 注意力。

本工具流程（可重跑、可审计、幂等）：
  1) **分章**：解析目录行 ``num title......page``（正则 ``^(\\d+(?:\\.\\d+)*)\\s+(\\S.*?)\\.{3,}\\s*(\\d+)\\s*$``），
     再在正文按「章节号+标题独占一行」定位起点，切成 ``[{num,title,line,end_line,text}]``
     （1-based，闭区间，与项目 refs 风格一致）；定位失败的章节并入前一章。
  2) **分批送 LLM**：章节按顺序打包（默认每批 ≤ ``--batch-chars`` 字符，不切断章节），
     每批一次 ``llm_json(..., BatchVerdict)`` 调用，判定每章是否硬件约束。
     保留：能力与限制（支持 X 最高到 Y/最高速率/插损/驱动能力）、资源冲突（互斥/共用）、
     外围要求（差分时钟/校准电阻/上下拉）、引脚定义/复用/不使用处理、电气特性、电源方案、
     上下电时序/复位/时钟、接口拓扑与布线、PCB/热/ESD/EMC、启动模式配置。
     丢弃：**只有**噪声白名单 —— 修订记录/目录/术语/订购包装/法律声明/纯图表编号说明。
     确定性硬护栏（修法 1/2，覆盖 LLM）：
       - ``descriptive`` 不再是合法丢弃理由；白名单外理由/空理由 → **强制保留**
         （``override=reason_not_whitelisted`` / ``no_reason``）；
       - 标题命中 ``MUST_KEEP_TITLE_RE`` → 一律保留（``override=title_guard``）。
  3) **产出**（只保留硬件约束，但必须可审计）：
     - ``rules/platform/<chip>/rules.json``（超 20000 tokens 预算拆 ``rules.partN.json``）
     - ``rules/platform/<chip>/filter_verdicts.json``  LLM 判定缓存（``sha1(PROMPT_VERSION+内容)`` → verdict）
     - ``rules/platform/<chip>/filter_manifest.json`` 审计清单（每章 keep/drop_reason + ``override`` + 汇总）
     - 同步 ``rules/index.json`` 中该平台 ``rules`` 字段。

幂等：判定按 ``sha1(PROMPT_VERSION + 章节 sha1)`` 缓存 → 内容未变时二次运行 **0 次 LLM**；
产物写入带稳定时间戳，内容一致则字节一致。``--force`` 覆盖缓存与旧产物。
``PROMPT_VERSION`` 变更 → 缓存全部失效并重新判定（修法 4）；运行末做同标题一致性自检 + override 统计（修法 5）。

用法::

    PYTHONPATH=src .venv/bin/python scripts/prepare_rules/datasheet_to_rules.py
    PYTHONPATH=src .venv/bin/python scripts/prepare_rules/datasheet_to_rules.py --force
    HARDWARE_MOCK=1 PYTHONPATH=src .venv/bin/python scripts/prepare_rules/datasheet_to_rules.py
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from hardware_analysis.agents.direct import llm_json                      # noqa: E402
from hardware_analysis.models.rules_contracts import (                     # noqa: E402
    BatchVerdict, RuleBundle, SectionVerdict,
)

SCHEMA_VERSION = "1.0"
# 提示词/判定逻辑版本：变更即令 filter_verdicts 缓存全部失效（修法 4）
PROMPT_VERSION = "v2"
DEFAULT_PLATFORM = "E2000"
DEFAULT_RAW = "raw/raw_platmform/E2000/数据手册.md"
BUDGET_TOKENS = 20000          # 单文件预算（与 platform_to_json.BUDGET_TOKENS 一致）
DEFAULT_BATCH_CHARS = 12000
STAGE = ["PH-2", "PH-3"]
GATE = "G3"

TOC_RE = re.compile(r"^(\d+(?:\.\d+)*)\s+(\S.*?)\.{3,}\s*(\d+)\s*$")

# 判定标准（同时写入 prompt；mock/失败兜底按标题关键词做同向的保守判定）
KEEP_CRITERIA = (
    "能力与限制（支持 X 最高到 Y/最高速率/插损/驱动能力/速率上限/不支持 AN 自协商）、"
    "资源冲突（不能同时使用/互斥/共用）、外围要求（100MHz 差分时钟/校准电阻/上拉下拉）、"
    "引脚定义与复用/不使用处理、电气特性（电压/电流/阻抗/容差/速率）、电源方案与供电域、"
    "上下电时序/复位/时钟、接口拓扑与布线（等长/阻抗/匹配）、PCB/热/ESD/EMC 设计要求、"
    "启动模式配置；\u201c支持…\u201d 形式的 bullet 能力清单亦属约束"
)
DROP_CRITERIA = (
    "修订记录、目录、术语缩略语、产品标识/订购/包装、法律声明、"
    "纯框图/图表的编号说明（title 或整章仅描述图表编号）；"
    "禁止用 descriptive 等宽泛理由丢弃含能力/限制/参数的章节"
)
# 允许丢弃的理由 = 噪声白名单（**descriptive 已移除**，不再是合法丢弃理由）
DROP_REASONS = ("revision_history", "toc", "toc_entry", "terminology", "ordering",
                "packaging", "legal", "figure_caption", "cover")
# 标题硬护栏（确定性，优先级高于 LLM 判定）：命中即一律保留
MUST_KEEP_TITLE_RE = re.compile(
    r"特性|电气|指标|参数|时序|复用|拓扑|布线|PCB|阻抗|等长|引脚|信号|电源|时钟|复位|"
    r"ESD|EMC|温度|热|校准|绝对最大|推荐工作|限制|约束|处理方式|使用|建议|指导|准则|要求",
    re.I,
)

SYS_FOOTER = (
    "\n\n【本次任务】你是硬件数据手册规则筛选器：判断章节是否为可执行的硬件设计约束，"
    "并抽取原文约束条目。默认倾向保留；只有修订记录/目录/术语缩略语/产品标识订购包装/"
    "法律声明/纯图表编号说明方可丢弃，**禁止**用 descriptive 之类宽泛理由丢弃含能力、"
    "限制、参数的章节。只输出一个 JSON 对象，键为 sections，禁止解释或 Markdown 围栏。"
)

# mock / LLM 失败兜底用的标题关键词（与 direct._mock 同向；此处独立实现，避免耦合私有函数）
_FB_DROP_RULES = (
    (("版本", "修订"), "revision_history"),
    (("目录",), "toc"),
    (("术语", "缩略"), "terminology"),
    (("产品标识", "标识", "订购", "订货", "包装", "marking"), "ordering"),
    (("法律", "声明", "版权"), "legal"),
    (("框图", "结构图", "map"), "figure_caption"),
)
_FB_KEEP_KW = (
    "引脚", "信号", "电气", "电压", "电流", "电源", "供电", "电容", "时序", "复位",
    "时钟", "布线", "阻抗", "拓扑", "交换", "接口", "复用", "不使用", "校准", "pcb",
    "esd", "emc", "热", "温度", "启动", "配置", "微带", "带状", "残桩", "串扰",
    "回流", "叠层", "封装", "扣合", "装焊", "尺寸", "serdes", "mio", "io", "lsd",
    "额定", "最大", "特性",
)
_FB_CATEGORIES = (
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


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #
def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _est_tokens_entries(entries: list[dict]) -> int:
    """与 rule_loader._est_tokens 完全一致：len(json)//16*10。"""
    return len(json.dumps(entries, ensure_ascii=False)) // 16 * 10


def _est_tokens_chars(chars: int) -> int:
    return int(chars) // 16 * 10


def _write_stable(path: Path, build, force: bool = False) -> bool:
    """稳定写 JSON：``build(ts) -> dict``。内容（用旧 generated_at 重建）一致 → 复用旧 ts，
    保证内容未变时**字节一致**。返回 True=写入（内容有变），False=跳过（字节相同）。"""
    old = None
    if path.exists() and not force:
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            old = None
    ts = _now_iso()
    if isinstance(old, dict) and old.get("generated_at"):
        try:
            if build(old["generated_at"]) == old:
                ts = old["generated_at"]
        except Exception:
            pass
    data = json.dumps(build(ts), ensure_ascii=False, indent=1) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    cur = path.read_text(encoding="utf-8") if path.exists() else None
    if cur == data:
        return False
    path.write_text(data, encoding="utf-8")
    return True


# --------------------------------------------------------------------------- #
# 1) 分章
# --------------------------------------------------------------------------- #
def parse_toc(lines: list[str]) -> list[dict]:
    """解析目录点线行 → [{num,title,page,toc_line}]。"""
    toc = []
    for i, raw in enumerate(lines, start=1):
        m = TOC_RE.match(raw.strip())
        if m:
            toc.append({"num": m.group(1), "title": m.group(2).strip(),
                        "page": int(m.group(3)), "toc_line": i})
    return toc


def locate_sections(lines: list[str], toc: list[dict]) -> tuple[list[dict], list[dict]]:
    """在正文定位每章起点并切条；返回 (sections, merged)。

    - 正文起点 = 最后一个目录点线行之后，避免版本历史里的 ``2.4 ...`` 误判。
    - 定位失败的章节并入前一章（其正文天然落入前一章的 end_line 区间）。
    """
    dotted = [i for i, l in enumerate(lines, start=1) if "...." in l]
    body_start = (max(dotted) + 1) if dotted else 1

    located: list[tuple[int, dict]] = []
    merged: list[dict] = []
    last_located_num = ""
    for e in toc:
        pat = re.compile(r"^\s*" + re.escape(e["num"]) + r"\s+" + re.escape(e["title"]) + r"\s*$")
        hit = None
        for j in range(body_start, len(lines) + 1):
            if pat.match(lines[j - 1]):
                hit = j
                break
        if hit is None:
            merged.append({"num": e["num"], "title": e["title"], "into": last_located_num})
            continue
        located.append((hit, e))
        last_located_num = e["num"]

    located.sort(key=lambda x: x[0])
    sections = []
    for idx, (line, e) in enumerate(located):
        end = located[idx + 1][0] - 1 if idx + 1 < len(located) else len(lines)
        text = "\n".join(lines[line - 1:end])
        sections.append({"num": e["num"], "title": e["title"], "line": line,
                         "end_line": end, "text": text})
    return sections, merged


def section_sha1(sec: dict) -> str:
    return _sha1(f"{sec['num']}\n{sec['title']}\n{sec['text']}")


def cache_key(sec: dict) -> str:
    """判定缓存键 = sha1(PROMPT_VERSION + 章节内容 sha1)；PROMPT_VERSION 变更 → 缓存失效（修法 4）。"""
    return _sha1(f"{PROMPT_VERSION}\n{section_sha1(sec)}")


def pack_batches(sections: list[dict], batch_chars: int) -> list[list[dict]]:
    """按顺序打包（不切断章节）；单章超限则独占一批。"""
    batches: list[list[dict]] = []
    cur: list[dict] = []
    cur_chars = 0
    for sec in sections:
        n = len(sec["text"])
        if cur and cur_chars + n > batch_chars:
            batches.append(cur)
            cur, cur_chars = [], 0
        cur.append(sec)
        cur_chars += n
    if cur:
        batches.append(cur)
    return batches


# --------------------------------------------------------------------------- #
# 2) 判定（LLM + 兜底）
# --------------------------------------------------------------------------- #
def build_prompt(batch: list[dict]) -> str:
    parts = [
        "请判定下列每个章节是否为「硬件设计约束」，并抽取可执行的硬件约束条目。\n",
        "【属于硬件约束 → is_hardware_constraint=true，必须保留】\n"
        "①能力与限制：\u201c支持 X 最高到 Y / 最高速率 / 插损 / 驱动能力 / 速率上限 / "
        "不支持 AN 自协商\u201d等；\n"
        "②资源冲突：\u201c不能同时使用 / 互斥 / 共用 / 二选一\u201d等；\n"
        "③外围要求：\u201c需要提供 100MHz 差分时钟 / 校准电阻 / 上拉下拉\u201d等；\n"
        "④电平/电流/阻抗/容差/速率/时序/引脚定义与复用/不使用处理/上下电时序/复位/时钟/"
        "PCB 布线（等长、阻抗匹配、拓扑）/热/ESD/EMC/校准/启动配置等一切可执行约束。\n"
        "重要：\u201c支持…\u201d\u201c最高…\u201d\u201c不支持…\u201d形式的 bullet 能力清单属于硬件约束，"
        "不得因为它是 bullet 列表或功能描述就判为 descriptive。\n",
        "【只有以下才算非约束 → is_hardware_constraint=false，且 drop_reason 必须取白名单之一】\n"
        "revision_history（修订记录）| toc / toc_entry（目录）| terminology（术语缩略语）| "
        "ordering（产品标识/订购）| packaging（包装）| legal（法律声明）| "
        "figure_caption（纯框图/图表的编号说明：title 或整章仅描述图表编号）| cover（封面）。\n"
        "禁止使用 descriptive 或其它未列出的理由；若章节含任何硬件约束，必须保留。\n",
        "【输出】只输出一个 JSON 对象，形如：\n"
        '{"sections":[{"num":"<章节号>","is_hardware_constraint":true,'
        '"categories":["pin_definition"|"electrical"|"power"|"timing"|"topology"|"pcb"|'
        '"thermal"|"esd"|"peripheral"|"unused_pin"|"boot_config"],'
        '"constraints":["原文摘录，保留章节 1~5 条且非空；丢弃章节为 []"],'
        '"must":[],"must_not":[],"params":{},'
        '"drop_reason":"保留时为空串；丢弃时取上述白名单之一"}]}\n'
        "必须覆盖下面列出的每一个 num，不得遗漏；不要输出解释或 Markdown 围栏。\n",
        "【待判定章节】\n",
    ]
    for sec in batch:
        parts.append(f"<<<SECTION num={sec['num']} title={sec['title']} line={sec['line']}>>>\n")
        parts.append(sec["text"].rstrip("\n") + "\n")
        parts.append(f"<<<END num={sec['num']}>>>\n")
    return "".join(parts)


def fallback_verdict(sec: dict) -> dict:
    """LLM 整批失败/漏章时的确定性保守兜底（按标题关键词）。

    找不到**白名单噪声理由**时一律保留（不再用 descriptive 兜底丢弃）。
    """
    tl = (sec["title"] or "").replace(" ", "").lower()
    drop_reason = ""
    for kws, reason in _FB_DROP_RULES:
        if any(kw in tl for kw in kws):
            drop_reason = reason
            break
    keep = not drop_reason          # 无白名单噪声理由 → 保守保留
    cats = []
    if keep:
        for kws, cat in _FB_CATEGORIES:
            if any(kw in tl for kw in kws) and cat not in cats:
                cats.append(cat)
    excerpts = []
    for seg in re.split(r"(?<=[。；\n])", sec["text"]):
        s = re.sub(r"\s+", " ", seg).strip()
        if len(s) >= 6:
            excerpts.append(s[:200])
        if len(excerpts) >= 3:
            break
    return {
        "num": sec["num"], "is_hardware_constraint": bool(keep),
        "categories": cats if keep else [], "constraints": excerpts if keep else [],
        "must": [], "must_not": [], "params": {},
        "drop_reason": drop_reason,
    }


def verdict_to_dict(v) -> dict:
    if isinstance(v, SectionVerdict):
        return v.model_dump()
    return dict(v)


def _norm_drop_reason(raw, title: str) -> str:
    """把 LLM 自由文本/中文理由归一到**噪声白名单**；无法归一时返回 ""（→ 触发强制保留）。

    ``descriptive`` 等宽泛理由不再映射到任何白名单项 → 返回 "" → override=reason_not_whitelisted。
    """
    s = str(raw or "").strip()
    if s in DROP_REASONS:
        return s
    tl = f"{s} {title}".lower()
    for kws, reason in (
        (("修订", "版本", "历史", "revision"), "revision_history"),
        (("目录", "toc"), "toc"),
        (("术语", "缩略", "terminology"), "terminology"),
        (("标识", "订购", "订货", "包装", "ordering", "packaging", "marking"), "ordering"),
        (("法律", "声明", "版权", "legal"), "legal"),
        (("框图", "pin map", "figure", "caption", "图片", "插图"), "figure_caption"),
    ):
        if any(k in tl for k in kws):
            return reason
    return ""


def apply_guards(sec: dict, verdict: dict) -> dict:
    """确定性硬护栏（覆盖 LLM 判定），返回带 ``override`` 的新 verdict。

    1) 标题命中 ``MUST_KEEP_TITLE_RE`` → 强制保留（override=title_guard）；
    2) keep=false 但 ``drop_reason`` 不在 ``DROP_REASONS`` 白名单 → 强制保留
       （override=reason_not_whitelisted）；
    3) keep=false 但理由为空 → 强制保留（override=no_reason）。

    原始 LLM 理由存入 ``llm_reason``（随缓存留痕），二次运行按同一输入重算 → 幂等。
    """
    v = dict(verdict)
    raw = str(v.get("llm_reason") if v.get("llm_reason") is not None
              else (v.get("drop_reason") or "")).strip()
    v["llm_reason"] = raw
    keep = bool(v.get("is_hardware_constraint"))
    reason = _norm_drop_reason(raw, sec["title"])
    override = ""
    if MUST_KEEP_TITLE_RE.search(sec["title"] or ""):
        keep, reason, override = True, "", "title_guard"
    elif not keep:
        if not raw:
            keep, reason, override = True, "", "no_reason"
        elif reason not in DROP_REASONS:
            keep, reason, override = True, "", "reason_not_whitelisted"
    v["is_hardware_constraint"] = keep
    v["drop_reason"] = "" if keep else reason
    v["override"] = override
    return v


# --------------------------------------------------------------------------- #
# 3) 产出
# --------------------------------------------------------------------------- #
def entry_from(section: dict, verdict: dict, seq: int, src_rel: str) -> dict:
    constraints = [str(c).strip() for c in (verdict.get("constraints") or []) if str(c).strip()]
    text = "\n".join(constraints).strip()
    if not text:                                    # 保底：LLM 未给条目时保留章节摘要（截断，不整章塞入）
        text = section["text"].strip()
        if len(text) > 1500:
            text = text[:1500].rstrip() + "…"
    return {
        "id": f"PF-E2000-{seq:03d}",
        "title": f"{section['num']} {section['title']}",
        "stage": list(STAGE),
        "gate": GATE,
        "params": dict(verdict.get("params") or {}),
        "must": list(verdict.get("must") or []),
        "must_not": list(verdict.get("must_not") or []),
        "text": text,
        "refs": [{"src": src_rel, "line": section["line"], "end_line": section["end_line"]}],
    }


def pack_parts(entries: list[dict]) -> list[list[dict]]:
    parts: list[list[dict]] = []
    cur: list[dict] = []
    for e in entries:
        trial = cur + [e]
        if cur and _est_tokens_entries(trial) > BUDGET_TOKENS:
            parts.append(cur)
            cur = [e]
        else:
            cur = trial
    if cur:
        parts.append(cur)
    return parts or [[]]


def main() -> int:
    ap = argparse.ArgumentParser(description="数据手册分章 → LLM 硬件约束判定 → 规则束")
    ap.add_argument("--platform", default=DEFAULT_PLATFORM)
    ap.add_argument("--raw", default=DEFAULT_RAW, help="数据手册 md（相对项目根）")
    ap.add_argument("--batch-chars", type=int, default=DEFAULT_BATCH_CHARS)
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--force", action="store_true", help="忽略缓存与旧产物，全部重新判定")
    args = ap.parse_args()

    platform = args.platform
    raw_path = ROOT / args.raw
    out_dir = ROOT / "rules" / "platform" / platform
    index_path = ROOT / "rules" / "index.json"
    src_rel = args.raw.replace("\\", "/")

    raw_text = raw_path.read_text(encoding="utf-8")
    src_sha = _sha1(raw_text)
    lines = raw_text.split("\n")
    print(f"[datasheet] {src_rel} sha1={src_sha[:12]} lines={len(lines)} chars={len(raw_text)}")

    toc = parse_toc(lines)
    sections, merged = locate_sections(lines, toc)
    print(f"[toc] 目录 {len(toc)} 条 | 正文定位 {len(sections)} 章 | 并入 {len(merged)} 条"
          + (f" {merged}" if merged else ""))

    # ---- 缓存：sha1(PROMPT_VERSION+章节) → verdict（修法 4：版本不符 → 整批失效）----
    cache_path = out_dir / "filter_verdicts.json"
    cache: dict = {}
    if cache_path.exists() and not args.force:
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            if data.get("prompt_version") == PROMPT_VERSION:
                cache = data.get("verdicts") or {}
            else:
                print(f"[cache] prompt_version={data.get('prompt_version')!r} != {PROMPT_VERSION!r} → 缓存失效")
        except Exception:
            cache = {}
    resolved: dict[str, dict] = {}
    for sec in sections:
        h = cache_key(sec)
        if h in cache:
            v = dict(cache[h])
            v["num"] = sec["num"]                      # 章节号以本次分章为准
            resolved[h] = v

    todo = [s for s in sections if cache_key(s) not in resolved]
    batches = pack_batches(todo, args.batch_chars)
    all_batches = pack_batches(sections, args.batch_chars)   # 全量分批（跨运行确定性）
    print(f"[batch] 待判定 {len(todo)} 章 / 共 {len(sections)} 章 | 缓存命中 {len(resolved)} | 批次 {len(batches)}")

    calls = 0
    for bi, batch in enumerate(batches, start=1):
        prompt = build_prompt(batch)
        obj, errs, secs = None, [], 0.0
        for attempt in range(args.retries + 1):
            calls += 1
            obj, errs, secs = llm_json("hw_filter", prompt, BatchVerdict,
                                       timeout=args.timeout, system_footer=SYS_FOOTER)
            if obj is not None:
                break
            print(f"[llm] batch {bi}/{len(batches)} 第 {attempt + 1} 次失败: {errs}，重试")
            if attempt < args.retries:
                time.sleep(1.5 * (attempt + 1))
        got = {}
        if obj is not None:
            for s in obj.sections:
                got[str(s.num)] = verdict_to_dict(s)
        for sec in batch:
            v = got.get(sec["num"])
            is_fb = v is None
            if is_fb:
                v = fallback_verdict(sec)              # 漏章/失败 → 确定性兜底（留痕）
            v["fallback"] = is_fb
            resolved[cache_key(sec)] = v
        print(f"[llm] batch {bi}/{len(batches)}: {len(batch)} 章 {len(prompt)} chars -> "
              f"{'ok' if obj is not None else 'FAIL'} ({secs}s)")

    fallback_nums = [s["num"] for s in sections if resolved[cache_key(s)].get("fallback")]
    for sec in sections:                                   # 硬护栏：标题 + 理由白名单（覆盖 LLM，修法 1/2）
        resolved[cache_key(sec)] = apply_guards(sec, resolved[cache_key(sec)])
    ov_stats = collections.Counter(resolved[cache_key(s)].get("override") or "" for s in sections)
    ov_counts = {k: ov_stats.get(k, 0)
                 for k in ("title_guard", "reason_not_whitelisted", "no_reason")}
    print(f"[llm] 调用次数={calls} | 缓存命中={len(sections) - len(todo)} | 兜底章节={fallback_nums or '无'}")
    print(f"[guard] override 统计={json.dumps(ov_counts, ensure_ascii=False)}")

    # ---- 规则束（只保留硬件约束）----
    kept_secs = [s for s in sections if resolved[cache_key(s)].get("is_hardware_constraint")]
    entries: list[dict] = []
    seq = 0
    for sec in kept_secs:
        seq += 1
        entries.append(entry_from(sec, resolved[cache_key(sec)], seq, src_rel))

    parts = pack_parts(entries)
    desired: list[str] = []
    for pi, part in enumerate(parts):
        name = "rules.json" if len(parts) == 1 else f"rules.part{pi + 1}.json"
        desired.append(name)
        rel = f"platform/{platform}/{name}"

        def build(ts, part=part):
            return {
                "schema_version": SCHEMA_VERSION, "kind": "platform_rules",
                "scope": f"platform/{platform}", "source": src_rel, "source_sha1": src_sha,
                "generated_at": ts, "tokens_est": _est_tokens_entries(part), "entries": part,
            }
        RuleBundle.model_validate(build(_now_iso()))   # 契约校验（extra="forbid"）
        wrote = _write_stable(out_dir / name, build, force=args.force)
        print(f"[rules] {rel} entries={len(part)} tokens_est={_est_tokens_entries(part)} "
              f"{'WRITE' if wrote else 'SKIP(byte-identical)'}")

    # 清理陈旧分片（rules_01.json / rules.partN.json / rules.json 中被替换者）
    for old in sorted(out_dir.glob("rules*.json")):
        if old.name not in desired:
            old.unlink()
            print(f"[rules] 删除陈旧分片 platform/{platform}/{old.name}")

    # ---- 判定缓存 ----
    def build_cache(ts):
        vs = {}
        for sec in sections:
            v = dict(resolved[cache_key(sec)])
            v["num"] = sec["num"]
            v["title"] = f"{sec['num']} {sec['title']}"
            vs[cache_key(sec)] = v
        return {"schema_version": SCHEMA_VERSION, "kind": "filter_verdicts",
                "prompt_version": PROMPT_VERSION,
                "source": src_rel, "source_sha1": src_sha, "generated_at": ts,
                "batching": {"batch_chars": args.batch_chars, "batches": len(all_batches)},
                "verdicts": dict(sorted(vs.items()))}

    _write_stable(cache_path, build_cache, force=args.force)

    # ---- 审计清单 ----
    dropped = [s for s in sections if not resolved[cache_key(s)].get("is_hardware_constraint")]
    reason_dist = collections.Counter(
        resolved[cache_key(s)].get("drop_reason") or "" for s in dropped)

    def build_manifest(ts):
        sec_rows = []
        for sec in sections:
            v = resolved[cache_key(sec)]
            keep = bool(v.get("is_hardware_constraint"))
            sec_rows.append({
                "num": sec["num"], "title": sec["title"], "line": sec["line"],
                "end_line": sec["end_line"], "chars": len(sec["text"]),
                "keep": keep,
                "drop_reason": "" if keep else (v.get("drop_reason") or ""),
                "override": v.get("override") or "",
                "categories": list(v.get("categories") or []),
            })
        chars_before = sum(len(s["text"]) for s in sections)
        chars_after = sum(len(e["text"]) for e in entries)
        return {
            "schema_version": SCHEMA_VERSION, "kind": "filter_manifest",
            "source": src_rel, "source_sha1": src_sha, "generated_at": ts,
            "criteria": {"keep": KEEP_CRITERIA, "drop": DROP_CRITERIA,
                         "drop_reasons": list(DROP_REASONS),
                         "prompt_version": PROMPT_VERSION},
            "summary": {
                "sections_total": len(sections), "kept": len(kept_secs), "dropped": len(dropped),
                "chars_before": chars_before, "chars_after": chars_after,
                "tokens_before": _est_tokens_chars(chars_before),
                "tokens_after": _est_tokens_chars(chars_after),
                "overrides": ov_counts,
            },
            "merged_sections": merged,
            "fallback_sections": fallback_nums,
            "sections": sec_rows,
        }

    _write_stable(out_dir / "filter_manifest.json", build_manifest, force=args.force)

    # ---- 同步 rules/index.json（仅该平台 rules 字段）----
    idx = json.loads(index_path.read_text(encoding="utf-8"))
    if len(desired) == 1:
        rules_ref = f"platform/{platform}/{desired[0]}"
    else:
        rules_ref = [f"platform/{platform}/{n}" for n in desired]
    idx.setdefault("platform", {}).setdefault(platform, {})["rules"] = rules_ref
    data = json.dumps(idx, ensure_ascii=False, indent=1) + "\n"
    if index_path.read_text(encoding="utf-8") != data:
        index_path.write_text(data, encoding="utf-8")
        print(f"[index] rules <- {rules_ref}")
    else:
        print("[index] rules 无变化（SKIP）")

    chars_before = sum(len(s["text"]) for s in sections)
    chars_after = sum(len(e["text"]) for e in entries)

    # ---- 修法 5：同标题一致性自检 + override / 丢弃理由统计 ----
    title_keep: dict[str, set] = {}
    for sec in sections:
        title_keep.setdefault(sec["title"], set()).add(
            bool(resolved[cache_key(sec)].get("is_hardware_constraint")))
    inconsistent = {t: sorted(v) for t, v in title_keep.items() if len(v) > 1}
    if inconsistent:
        print(f"[consistency] ⚠️ 同标题判定不一致 = {len(inconsistent)}: "
              + "; ".join(f"{t}{v}" for t, v in list(inconsistent.items())[:10]))
    else:
        print("[consistency] 同标题判定不一致 = 0")
    print(f"[override] {json.dumps(ov_counts, ensure_ascii=False)}")
    print(f"[drop] 丢弃理由分布={json.dumps(dict(sorted(reason_dist.items())), ensure_ascii=False)}")
    print(f"[manifest] sections={len(sections)} kept={len(kept_secs)} dropped={len(dropped)} "
          f"chars {chars_before}→{chars_after} tokens~{_est_tokens_chars(chars_before)}"
          f"→{_est_tokens_chars(chars_after)}")
    print(f"[done] 规则文件: {desired} | 保留 {len(entries)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
