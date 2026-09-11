"""P3-A 规则接收契约 — md→json 转换产物的强制结构（Pydantic）。

定义 `rules/common/*.json` 的统一信封与规则条目：
    RuleBundle { schema_version, kind="rule_bundle", scope, source,
                 source_sha1, generated_at, tokens_est, entries[] }
    RuleEntry  { id, title, stage[], gate, params{}, must[], must_not[],
                 text, refs[] }
    Ref        { src, line, end_line }

所有模型 `extra="forbid"`：字段缺失/多余一律拒收，保证下游只吃冻结格式。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    """统一基类：禁止未声明字段（extra="forbid"）。"""

    model_config = ConfigDict(extra="forbid")


class Ref(_Strict):
    """规则条目的原文出处（行号 1-based，闭区间）。"""

    src: str
    line: int = Field(ge=1)
    end_line: int = Field(ge=1)


class RuleEntry(_Strict):
    """一条规则条目（对应 md 中一个 ##/###... 标题块）。"""

    id: str
    title: str
    stage: list[str] = Field(default_factory=list)
    gate: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    must: list[str] = Field(default_factory=list)
    must_not: list[str] = Field(default_factory=list)
    text: str
    refs: list[Ref] = Field(default_factory=list)


class RuleBundle(_Strict):
    """一个规则文件（或拆分分片）的完整 JSON 信封。"""

    schema_version: str = "1.0"
    kind: str = "rule_bundle"
    scope: str
    source: str
    source_sha1: str
    generated_at: str
    tokens_est: int = Field(ge=0)
    entries: list[RuleEntry] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 数据手册「分章 → 硬件约束判定」契约（datasheet_to_rules.py 专用）
#
# 判定标准（与 prompt 中文字保持一致）：
#   保留（is_hardware_constraint=True）：能力与限制（支持 X 最高到 Y/最高速率/插损/
#     驱动能力）、资源冲突（不能同时使用/互斥/共用）、外围要求（差分时钟/校准电阻/
#     上拉下拉）、引脚定义/复用/不使用处理、电气特性（电压/电流/阻抗/容差/速率）、
#     电源方案与供电域、上下电时序/复位/时钟、接口拓扑与布线要求（等长/阻抗/匹配）、
#     PCB/热/ESD/EMC 设计要求、启动模式配置；"支持…" 形式的 bullet 能力清单亦属约束。
#   丢弃（is_hardware_constraint=False）：**仅**噪声白名单 —— 修订记录、目录、术语
#     缩略语、产品标识/订购/包装、法律声明、纯框图/图表的编号说明。
#   ``descriptive`` 不再是合法丢弃理由；调用方对白名单外理由/空理由强制保留
#   （override=reason_not_whitelisted / no_reason），标题命中硬护栏则 override=title_guard。
# 说明：本组模型保持宽松（extra 默认 ignore），以免 LLM 多返回 ``reason`` 等字段
# 导致整批判定被 Pydantic 拒收；字段缺失由调用方按保守策略兜底。
# --------------------------------------------------------------------------- #
class SectionVerdict(BaseModel):
    """单章判定结果（datasheet_to_rules 的 LLM 输出单元）。

    保留标准见本段上方注释；``drop_reason`` 仅允许噪声白名单：
    revision_history/toc/toc_entry/terminology/ordering/packaging/legal/
    figure_caption/cover（``descriptive`` 已废弃）。``override`` 记录确定性护栏
    是否覆盖了 LLM 判定：title_guard / reason_not_whitelisted / no_reason（空=无覆盖）。
    """

    num: str
    is_hardware_constraint: bool
    categories: list[str] = []      # 例: pin_definition/electrical/power/timing/topology/pcb/thermal/esd/peripheral/unused_pin/boot_config
    constraints: list[str] = []     # 该章中可执行的硬件约束条目（原文摘录，1~5 条；不含则空）
    must: list[str] = []
    must_not: list[str] = []
    params: dict[str, Any] = {}
    drop_reason: str = ""           # 非硬件约束时的理由（仅噪声白名单）
    override: str = ""              # 硬护栏覆盖标记：title_guard/reason_not_whitelisted/no_reason

    @model_validator(mode="before")
    @classmethod
    def _lenient(cls, data):
        """宽松兜底：LLM 给 null/字符串布尔/裸字符串列表时不整批拒收。"""
        if not isinstance(data, dict):
            return data
        d = dict(data)
        if d.get("num") is not None:
            d["num"] = str(d["num"])
        v = d.get("is_hardware_constraint")
        if isinstance(v, str):
            d["is_hardware_constraint"] = v.strip().lower() in ("true", "yes", "1", "y", "是")
        for k in ("categories", "constraints", "must", "must_not"):
            val = d.get(k)
            if val is None:
                d[k] = []
            elif isinstance(val, str):
                d[k] = [val]
        if d.get("params") is None:
            d["params"] = {}
        if d.get("drop_reason") is None:
            d["drop_reason"] = ""
        if d.get("override") is None:
            d["override"] = ""
        return d


class BatchVerdict(BaseModel):
    """一次 LLM 调用覆盖的整批章节判定。"""

    sections: list[SectionVerdict] = []

    @model_validator(mode="before")
    @classmethod
    def _lenient(cls, data):
        """宽松兜底：``sections`` 缺失/为 null → []（避免整批被拒收）。"""
        if isinstance(data, list):
            return {"sections": data}
        if isinstance(data, dict):
            d = dict(data)
            if d.get("sections") is None:
                d["sections"] = []
            return d
        return data
