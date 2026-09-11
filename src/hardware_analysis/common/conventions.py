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
    "power_net_regex": r"^(GND|AGND|DGND|VSS|VCC|VDD|VBAT|VIN|VBUS|\+|-)\d*",
    "diff_pair_regex": r"^(.*?)[_\-]?([PN])$",
    "board_regex": r"-([A-Z])_V\d",            # 主；回退见 board_fallback_regex
    "board_fallback_regex": r"-([A-Z])_",
    "board_unknown": "X",
    # 可调阈值（魔法数字集中处）
    "connector_pair_min_signal": 3,           # 连接器配对所需最少信号命中
    "fanout_min_neighbors": 3,                # >此值判 FANOUT
    "trace_guard": 60,                        # 追踪防环上限（跳）
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
        m = self._diff.match(str(net or ""))
        return (m.group(1), m.group(2)) if m else None

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
