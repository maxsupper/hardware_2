"""编号字典（canonical numbering dictionary）— 阶段1b 产物 A.

定义 raw 规则/条件/门禁 到 规范编号 的命名空间与映射规则。
设计原则: 编号稳定、可反查、无撞名；一切以 rules.json 单一事实源为准。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parents[2] / "raw"          # hardware_analysis/raw
DERIVE_DIR = Path(__file__).resolve().parents[2] / "docs" / "conflicts"

# ---------- 规范编号命名空间（ID 前缀 → 语义） ----------
# 与 §4.7 + 我们 PH/G/SA 重编号对齐
ID_NAMESPACES = {
    # 阶段规则（按 PH 归属）
    "PREP-":  "B 网表解析 规则(含跨EDN合并/信号链)",
    "G0-":    "C 手册检索 规则",
    "W0-":    "D 数据预检 检查项(Wave0)",
    "IC-":    "E 器件检查项",
    "PO-":    "E 供电/电源检查项(含电源树)",
    "CN-":    "E 连接器检查项",
    "DR-":    "E DDR 检查项",
    "PE-":    "E PCIe 检查项",
    "LS-":    "E 电平转换检查项",
    "PB-":    "E 外设检查项",
    "IF-":    "E 外设接口检查项(如 IF-I2C-001)",
    "SYN-":   "synthesis 检查项",
    "CONN-":  "连接器专项(CONN-J1-001)",
    "K-T":    "跨文件引用规则(如 K-T001=I2C强制上拉)",
    "SA-":    "F 审计自审标准(原 G0-G7)",
    "RF-":    "F 报告/交付规则",
    # 门禁与阶段
    "G<1..6>":   "流程门禁 (G1 手册+BOM/G2 网表/G3 分析/G4 报告/G5 审计/G6 交付)",
    "PH-":       "阶段 (PH-0..PH-6)",
    "BLOCK_":    "阻断条件实例(原 raw Block #[n])",
}

# ---------- 源文件 → 默认编号前缀（用于自动归类） ----------
FILE_DOMAIN_MAP = {
    "硬件评审者.md": "G0-",      # 手动映射由 renumber 覆盖
}
# raw 文件 → 类别/前缀建议
RAW_FILE_MAP = {
    "raw_roles/hardware-reviewer.md": {"kind": "角色+流程", "note": "含阶段/门禁/SA/数据契约，按节细分"},
    "raw_rules/引脚核对规则.md":        {"kind": "规则", "prefix": "IC-", "stage": "PH-4"},
    "raw_rules/引脚复用关系检查规则.md": {"kind": "规则", "prefix": "IC-", "stage": "PH-4", "sub": "MUX"},
    "raw_rules/引脚电平检查方案.md":     {"kind": "规则", "prefix": "LS-", "stage": "PH-4"},
    "raw_rules/接口电路检查规则.md":     {"kind": "规则", "prefix": "PB-", "stage": "PH-4"},
    "raw_rules/电源检查.md":            {"kind": "规则", "prefix": "PO-", "stage": "PH-4"},
    "raw_rules/证据文件Schema规范.md":   {"kind": "规则", "prefix": "SYN-", "stage": "全"},
}

# 各 raw 文件的"节标题"分割正则（接口电路无 Markdown 标题，用编号行）
SECTION_PATTERNS = {
    "默认":  r"^#{1,4}[ \t]+(\S.*)$",
    "接口电路检查规则.md": (
        r"^\s*#{1,4}[ \t]+(\S.*)$"          # Markdown 风格(若有)
        r"|^第[一二三四五六七八九十]+部分.*$"    # "第二部分：..."
        r"|^\d+\.\d+\s+.*$"                  # "2.1 电平转换芯片判定树"
    ),
}


@dataclass
class NumberingDict:
    namespaces: dict = field(default_factory=lambda: dict(ID_NAMESPACES))
    raw_map: dict = field(default_factory=lambda: dict(RAW_FILE_MAP))

    def prefix_for_file(self, rel_path: str) -> str:
        """返回该文件建议前缀；无则空串（由 renumber 决定）。"""
        base = Path(rel_path).name
        m = self.raw_map.get(rel_path) or next(
            (v for k, v in self.raw_map.items() if Path(k).name == base), {})
        return m.get("prefix", "")


def load_numbering_dict() -> NumberingDict:
    return NumberingDict()
