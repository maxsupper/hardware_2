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

from pydantic import BaseModel, ConfigDict, Field


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
