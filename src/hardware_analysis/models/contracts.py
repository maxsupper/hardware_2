"""§4.x 数据契约 — Pydantic 模型（= rules.json 数据契约的强制结构）。

所有 LLM 输出 / Gate 校验 / 产物 JSON 均以此为准。
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


# ---------- 枚举（五级判定 / 置信度 / 门禁状态 / 手册状态） ----------
class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    OK = "OK"
    INFERRED = "INFERRED"
    UNVERIFIED = "UNVERIFIED"


class Confidence(str, Enum):
    DEFINITE = "DEFINITE"
    LIKELY = "LIKELY"
    UNCERTAIN = "UNCERTAIN"
    UNKNOWN = "UNKNOWN"


class GateStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"
    FORCED_PASS = "FORCED_PASS"


class ManualStatus(str, Enum):
    FOUND = "FOUND"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"
    UNVERIFIED = "UNVERIFIED"


# ---------- §4.5 通用顶层字段 ----------
class BaseDoc(BaseModel):
    schema_version: str = "1.0"
    kind: str
    status: str = "PASS"
    created_at: str = ""
    producer: str = ""
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ---------- Run 工作区 ----------
class RunManifest(BaseDoc):
    kind: str = "run_manifest"
    product: str = ""
    run_dir: str = ""
    phases: dict[str, str] = Field(default_factory=dict)  # PH-x -> PENDING/RUNNING/DONE
    gates: dict[str, str] = Field(default_factory=dict)   # Gx -> PENDING/...


# ---------- Step 0a（人工配置） ----------
class Step0aConfig(BaseDoc):
    kind: str = "step_0a"
    raw_user_response: str = ""
    manual_dir: str = "storge/refbook"
    extra_checks: list[str] = Field(default_factory=list)
    product: str = ""


# ---------- G0 手册检索 ----------
class IcEntry(BaseModel):
    refdes: str
    model: str
    ic_type: str = ""
    manual_path: str = ""
    status: ManualStatus = ManualStatus.MISSING
    attempted_sources: list[str] = Field(default_factory=list)


class G0Sources(BaseDoc):
    kind: str = "g0_sources"
    ics: dict[str, IcEntry] = Field(default_factory=dict)


# ---------- Gate 结果（§4.4） ----------
class GateCheck(BaseModel):
    id: str
    status: GateStatus
    expected: str = ""
    actual: str = ""


class GateResult(BaseDoc):
    kind: str = "gate_result"
    gate: str = ""
    checked_at: str = ""
    checks: list[GateCheck] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)


# ---------- Evidence（§4.2） ----------
class Finding(BaseModel):
    id: str = ""
    severity: Severity = Severity.OK
    confidence: Confidence = Confidence.DEFINITE
    object: str = ""
    result: str = ""
    source_refs: list[str] = Field(default_factory=list)


class EvidenceDoc(BaseDoc):
    kind: str = "evidence"
    evidence_type: str = ""
    producer: dict[str, str] = Field(default_factory=dict)   # {agent, task_id}
    coverage: dict[str, Any] = Field(default_factory=dict)   # {target,items_expected,items_checked,fill_rate}
    findings: list[Finding] = Field(default_factory=list)


# ---------- Evidence 摘要（§4.3, ≤5KB） ----------
class SummaryFinding(BaseModel):
    check: str
    status: Severity
    detail: str = Field(default="", max_length=80)


class SummaryDoc(BaseDoc):
    kind: str = "summary"
    section: str = ""
    scope: str = ""
    checks_count: int = 0
    findings: list[SummaryFinding] = Field(default_factory=list)
    tables: list[dict[str, Any]] = Field(default_factory=list)   # [{title, columns, rows}]
    narrative: dict[str, str] = Field(default_factory=dict)
    critical: int = 0
    warning: int = 0
    unverified: int = 0
    critical_items: list[str] = Field(default_factory=list)
    warning_items: list[str] = Field(default_factory=list)
    unverified_items: list[str] = Field(default_factory=list)


# ---------- 报告（report.json 三字段） ----------
class ReportDoc(BaseDoc):
    kind: str = "report"
    findings: list[SummaryFinding] = Field(default_factory=list)
    tables: list[dict[str, Any]] = Field(default_factory=list)
    narrative: dict[str, str] = Field(default_factory=dict)
