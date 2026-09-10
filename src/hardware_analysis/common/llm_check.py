"""通用 LLM 检查器 — 统一"角色 + 任务 + 契约 + 缓存 + 宽松归一".

复用点：所有阶段的 LLM 判定（ic_type/引脚核对/复核/审计…）走同一入口，避免各阶段内联
f-string prompt；支持按 key 的**持久化缓存**（换模型可复用；同 payload 不重复调网关）。
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path
from typing import Any

from hardware_analysis.agents.direct import llm_json, BRIEF_ROLE


def _key(agent: str, task: str, payload: Any) -> str:
    blob = f"{agent}||{task}||{json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)}"
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


class LLMChecker:
    """可复用检查器：run() 统一缓存 + 契约校验 + 归一化。"""

    def __init__(self, cache_path: str | Path | None = None):
        self.cache_path = Path(cache_path) if cache_path else None
        self._cache: dict = {}
        if self.cache_path and self.cache_path.exists():
            try:
                self._cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except Exception:
                self._cache = {}
        self.stats = {"hit": 0, "miss": 0, "error": 0}

    def _flush(self):
        if self.cache_path:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self._cache, ensure_ascii=False, indent=1), encoding="utf-8")

    def run(self, agent: str, task: str, contract, payload: Any = None,
            prompt: str | None = None, use_cache: bool = True, **llm_kw) -> tuple:
        """返回 (obj, meta)。obj 为契约对象或 None；meta 含 errors/sec/cached/key。"""
        key = _key(agent, task, payload if payload is not None else prompt)
        if use_cache and key in self._cache:
            self.stats["hit"] += 1
            obj, errs = _rehydrate(contract, self._cache[key])
            return obj, {"errors": errs, "sec": 0.0, "cached": True, "key": key}
        self.stats["miss"] += 1
        full = prompt or self.build_prompt(agent, task, payload)
        obj, errs, sec = llm_json(agent, full, contract, **llm_kw)
        if obj is not None:
            self._cache[key] = obj.model_dump()
            self._flush()
        else:
            self.stats["error"] += 1
        return obj, {"errors": errs, "sec": sec, "cached": False, "key": key}

    @staticmethod
    def build_prompt(agent: str, task: str, payload: Any) -> str:
        """三段式：角色(BRIEF_ROLE) 由 llm_json 注入；此处组装 任务 + 输入。"""
        body = "" if payload is None else "\n输入:\n" + json.dumps(payload, ensure_ascii=False)[:6000]
        return f"任务: {task}{body}"


def _rehydrate(contract, data: dict) -> tuple:
    from hardware_analysis.agents.crew import normalize_output
    return normalize_output(contract, json.dumps(data, ensure_ascii=False))


# 便捷函数（默认无持久化缓存；需要缓存时显式传 cache_path）
def run_check(agent: str, task: str, contract, payload: Any = None,
              prompt: str | None = None, cache_path: str | Path | None = None, **kw) -> tuple:
    return LLMChecker(cache_path).run(agent, task, contract, payload, prompt, **kw)
