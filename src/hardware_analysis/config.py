"""config 加载 — 读取 config.json（默认）或环境变量覆盖。

原则: config.json 为配置源（硬顶 512K 不可变）；LLM_API_KEY / TAVILY_API_KEY 可覆盖。
"""
from __future__ import annotations
import os
from pathlib import Path

HARD_CONTEXT_LIMIT = 512 * 1024  # ⛔ 512K 硬顶，不可修改


class Config:
    def __init__(self, path: str | Path = "config.json"):
        import json
        self._path = Path(path)
        self._data = json.loads(self._path.read_text(encoding="utf-8"))
        self.llm = self._data["llm"]
        self.llm.setdefault("request_timeout", 180)   # PF-009：LLM 请求超时（秒），缺省 180
        self.web = self._data["web"]
        self.paths = self._data["paths"]
        self.budget = dict(self._data["budget"])
        self.budget["context_total"] = HARD_CONTEXT_LIMIT  # 钳制，永不可突破
        self.conventions = dict(self._data.get("conventions", {}))  # EDA 约定/阈值覆盖

    @property
    def llm_api_key(self) -> str:
        return os.environ.get("LLM_API_KEY") or self.llm.get("apiKey", "")

    @property
    def tavily_key(self) -> str:
        return os.environ.get("TAVILY_API_KEY") or self.web.get("apiKey", "")

    def resolved_path(self, key: str, *, under: str = "storge") -> Path:
        """按 paths 解析相对路径。key 如 'products' → storge/project。"""
        st = self.paths.get("storge", {})
        if key in st:
            return Path(st[key])
        return Path(self.paths.get(key, key))

    def rule_bundle_tokens(self) -> int:
        return int(self.budget.get("rule_bundle_tokens", 100000))

    def input_hard_cap(self) -> int:
        """输入硬顶（不可突破）；缺省 400000。"""
        return int(self.budget.get("input_hard_cap", 400000))

    def request_timeout(self) -> int:
        """LLM 单次请求超时（秒）；缺省 180（可被 config.json llm.request_timeout 覆盖）。"""
        return int(self.llm.get("request_timeout", 180))
