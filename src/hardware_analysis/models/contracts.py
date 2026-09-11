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
    PARTIAL = "PARTIAL"             # 兼容
    FOUND_PARTIAL = "FOUND_PARTIAL"  # raw §2.4 词表
    MISSING = "MISSING"
    TRULY_MISSING = "TRULY_MISSING"  # raw §2.4 词表
    FOUND_COMPATIBLE = "FOUND_COMPATIBLE"  # 人工指定兼容型号
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
    refdes: str = ""          # 冗余字段：dict 键即 refdes，可缺省
    model: str
    ic_type: str = ""
    manual_path: Optional[str] = None
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
    status: GateStatus = GateStatus.PASS
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
    severity: Severity
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


# ================= v2 新增契约 =================

# ---------- PH-1 手册索引（位号→手册路径 表格，manual_index.json） ----------
class ManualIndexEntry(BaseModel):
    refdes: str
    board: str = ""
    model: str = ""
    ic_type: str = "UNKNOWN"          # SINK|PASS_THRU|POWER_SRC|UNKNOWN
    manual_path: Optional[str] = None
    status: ManualStatus = ManualStatus.MISSING
    attempted_sources: list[str] = Field(default_factory=list)
    pin_count: int = 0


class ManualIndex(BaseDoc):
    kind: str = "manual_index"
    product: str = ""
    entries: dict[str, ManualIndexEntry] = Field(default_factory=dict)   # key = "board::refdes"
    stats: dict[str, Any] = Field(default_factory=dict)


# ---------- PH-3 网表图 netlist_graph.json（v2.2） ----------
class NetlistDevice(BaseModel):
    id: str                              # "A::U6"
    board: str = ""
    refdes: str = ""
    model: str = ""                      # BOM 为准
    kind: str = "IC"                     # IC|CONNECTOR|PASSIVE|POWER|MECH|TESTPOINT
    source: dict[str, Any] = Field(default_factory=dict)   # {in_bom,in_edn,populated}
    ic: dict[str, Any] = Field(default_factory=dict)       # {manual_path,ic_type,channels}
    pins: dict[str, str] = Field(default_factory=dict)     # 脚 -> 网（全量）
    links: list[dict[str, Any]] = Field(default_factory=list)  # 上级/下级邻接
    depop: list[dict[str, Any]] = Field(default_factory=list)  # 不装占位


class NetlistNet(BaseModel):
    board: str = ""
    net: str = ""
    joins: list[dict[str, Any]] = Field(default_factory=list)   # [{refdes,pin}]
    alias_group: str = ""                # 0Ω 短接的别名网组
    kind: str = "signal"                 # signal|power|gnd


class NetlistPath(BaseModel):
    id: str = ""
    board: str = ""
    connector: str = ""
    pin: str = ""
    start_net: str = ""
    path: list[str] = Field(default_factory=list)
    endpoint_pins: list[str] = Field(default_factory=list)
    end_type: str = ""                   # CHIP|POWER|TO_CONNECTOR|STUB|OPEN_END
    bidirectional: str = "N/A"
    status: str = "OK"


class CrossBoardLink(BaseModel):
    a: str = ""                         # "A::J19.&134"
    b: str = ""                         # "B::J8.&134_B"
    net_a: str = ""
    net_b: str = ""
    method: str = "connector_pair"
    score: float = 0.0


class ConnectorPair(BaseModel):
    a: str = ""                         # "A::J19"
    b: str = ""                         # "B::J8"
    score: float = 0.0
    matched_pins: int = 0


class NetlistGraph(BaseDoc):
    kind: str = "netlist_graph"
    product: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)
    devices: list[NetlistDevice] = Field(default_factory=list)
    nets: list[NetlistNet] = Field(default_factory=list)
    paths: list[NetlistPath] = Field(default_factory=list)
    cross_board_links: list[CrossBoardLink] = Field(default_factory=list)
    connector_pairs: list[ConnectorPair] = Field(default_factory=list)
    diff_pairs: list[list[str]] = Field(default_factory=list)


# ---------- PH-3↔PH-4 回环协议 ----------
class ClarifyRequest(BaseModel):
    ref: str
    kind: str = "verify_trace"          # verify_trace|verify_ic_type|verify_merge
    device: str = ""
    pin: str = ""
    question: str = ""
    hypothesis: dict[str, Any] = Field(default_factory=dict)
    scope: dict[str, Any] = Field(default_factory=dict)   # {board,net,refdes}
    round: int = 1


class ClarifyResolution(BaseModel):
    ref: str
    result: str = "CONFIRMED"           # CONFIRMED|CORRECTED|UNRESOLVED
    round: int = 1
    evidence: dict[str, Any] = Field(default_factory=dict)
    apply_to: dict[str, Any] = Field(default_factory=dict)


# ---------- 通用检查契约（替代用 GateResult 当载体） ----------
class IcTypeVerdict(BaseModel):
    model: str = ""
    ic_type: str = "SINK"              # SINK|PASS_THRU|POWER_SRC|UNVERIFIED
    channels: list[dict[str, Any]] = Field(default_factory=list)  # PASS_THRU: {in:[..],out:[..]}
    reason: str = ""
    confidence: Confidence = Confidence.UNCERTAIN
