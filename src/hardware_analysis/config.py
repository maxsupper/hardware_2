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
        self.web = self._data["web"]
        self.paths = self._data["paths"]
        self.budget = dict(self._data["budget"])
        self.budget["context_total"] = HARD_CONTEXT_LIMIT  # 钳制，永不可突破

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
        return int(self.budget.get("rule_bundle_tokens", 40000))
