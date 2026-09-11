"""通用约定 — 单一来源（EDA 位号前缀 / 电源网 / 透明件 / 连接器 / 差分对 / 板号 / 脚名归一）.

目的：消除各工具里重复的 `_board_of`、`TRANSPARENT/_CONN/_MECH`、电源正则等硬编码；
全部可用 config.json 的 `conventions` 段（非规则键）覆盖，换项目/EDA 无需改代码。
"""
from __future__ import annotations
import re

DEFAULTS: dict = {
    "active_prefixes": ["U"],                                   # 有源器件（芯片/模组）
    "connector_prefixes": ["J", "CN", "P", "CON"],              # 连接器/接插件
    "mech_prefixes": ["H", "MH"],                               # 结构/安装孔
    "testpoint_prefixes": ["TP"],                               # 测试点
    "passive_prefixes": ["R", "C", "L", "FB", "D", "Q", "Y", "X", "F", "BEAD", "LED", "SW"],
    "transparent_prefixes": ["R", "L", "BEAD", "FB", "FERR", "TP", "JMP", "JUMP", "0R"],
    "power_net_regex": r"^((GND|AGND|DGND|PGND|VSS|VCC|VDD|VBAT|VIN|VBUS|VREF|AVDD|DVDD|IOVDD|[+-]\d|\d+V\d*))",
    "diff_pair_regex": r"^(.*?)[_\-]?([PNHL])$",      # 主：_P/_N  P/N  H/L
    "diff_pair_plusminus_regex": r"^(.*?)$",            # 辅：+/- 尾缀（与上式配合，见 diff_pair_key）
    "board_regex": r"-([A-Z])_V\d",            # 主；回退见 board_fallback_regex
    "board_fallback_regex": r"-([A-Z])_",
    "board_unknown": "X",
    # 可调阈值（魔法数字集中处）
    "connector_pair_min_signal": 3,           # 连接器配对所需最少信号命中
    "fanout_min_neighbors": 3,                # >此值判 FANOUT
    "trace_guard": 60,                        # 追踪防环上限（绝对保险，NG-011 另有 trace_max_hops）
    # NG-011：追踪规则（可被 config.json 的 conventions 段覆盖）
    "trace_max_hops": 6,                      # 最大跨器件层数（用户确认：6）
    "series_passive_prefixes": ["R", "L", "BEAD", "FB", "FERR", "JMP", "JUMP", "0R"],  # 可跨越的真串联件
    "series_passive_max_pins": 2,             # 串联件必须只有 2 脚
    "stop_at_active_net": True,               # 先本网有源落点→ 已抵达，不再跨无源件
    "diff_pair_equivalent": True,             # 差分对成员网视为同一逻辑信号（跨到搭档=原地打转）
}


class Conventions:
    def __init__(self, overrides: dict | None = None):
        self.cfg = {**DEFAULTS, **(overrides or {})}
        self._pwr = re.compile(self.cfg["power_net_regex"], re.I)
        self._diff = re.compile(self.cfg["diff_pair_regex"])
        self._board = re.compile(self.cfg["board_regex"])
        self._board_fb = re.compile(self.cfg["board_fallback_regex"])

    def _has(self, refdes: str, key: str) -> bool:
        r = str(refdes or "").upper()
        return any(r.startswith(p) for p in self.cfg[key])

    # ---- 位号种类 ----
    def is_active(self, refdes): return self._has(refdes, "active_prefixes")
    def is_connector(self, refdes): return self._has(refdes, "connector_prefixes")
    def is_mech(self, refdes): return self._has(refdes, "mech_prefixes")
    def is_testpoint(self, refdes): return self._has(refdes, "testpoint_prefixes")
    def is_passive(self, refdes): return self._has(refdes, "passive_prefixes")
    def is_transparent(self, refdes): return self._has(refdes, "transparent_prefixes")

    def kind_of(self, refdes: str) -> str:
        if self.is_active(refdes): return "IC"
        if self.is_testpoint(refdes): return "TESTPOINT"
        if self.is_mech(refdes): return "MECH"
        if self.is_connector(refdes): return "CONNECTOR"
        if self.is_passive(refdes): return "PASSIVE"
        return "OTHER"

    # ---- 网络 ----
    def is_power_net(self, net: str) -> bool:
        return bool(self._pwr.match(str(net or "").strip()))

    def diff_pair_key(self, net: str):
        """差分对键 — 支持 `_P/_N`、`P/N`、`H/L`、`+/-`（NG-012）。返回 (base, tag) 或 None。"""
        s = str(net or "").strip()
        if s.endswith("+") or s.endswith("-"):
            return (s[:-1], "PM")
        m = self._diff.match(s)
        if m and not m.group(1).endswith(("_", "-")):
            return (m.group(1), m.group(2))
        return None

    def is_series_passive(self, refdes: str, pins: dict) -> bool:
        """真串联件（NG-011）：2 脚且两端网络均非电源/地，且位号属可跨越前缀。"""
        r = str(refdes or "").upper()
        if not any(r.startswith(p) for p in self.cfg["series_passive_prefixes"]):
            return False
        if len(pins or {}) != self.cfg["series_passive_max_pins"]:
            return False
        return not any(self.is_power_net(n) for n in pins.values())

    # ---- 板号 ----
    def board_of(self, name: str) -> str:
        m = self._board.search(name) or self._board_fb.search(name)
        return m.group(1) if m else self.cfg["board_unknown"]

    # ---- 归一 ----
    @staticmethod
    def pin_norm(pin: str) -> str:
        p = str(pin or "").strip().lstrip("&")
        return re.sub(r"_[AB]$", "", p).lower()

    @staticmethod
    def net_norm(net: str) -> str:
        return re.sub(r"_[AB]$", "", str(net or "")).upper()


# 默认单例（自动叠加 config.json 的 conventions 段；只用标准库，避免与 config.py 循环依赖）
def _load_config_overrides() -> dict:
    try:
        import json as _json
        from pathlib import Path as _P
        for cand in (_P("config.json"), _P(__file__).resolve().parents[3] / "config.json"):
            if cand.exists():
                return _json.loads(cand.read_text(encoding="utf-8")).get("conventions", {}) or {}
    except Exception:
        pass
    return {}


def apply_overrides(overrides: dict | None) -> "Conventions":
    """运行时原地覆盖单例 CONV（供程序化调整/测试）。"""
    merged = {**CONV.cfg, **(overrides or {})}
    CONV.__init__(merged)
    return CONV


CONV = Conventions(_load_config_overrides())


def with_overrides(overrides: dict | None) -> Conventions:
    return Conventions({**CONV.cfg, **(overrides or {})})
