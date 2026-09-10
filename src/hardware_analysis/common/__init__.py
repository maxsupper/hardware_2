"""通用层：约定单一来源 + 可复用 LLM 检查器。"""
from hardware_analysis.common.conventions import CONV, Conventions, DEFAULTS, with_overrides  # noqa: F401
from hardware_analysis.common.llm_check import LLMChecker, run_check  # noqa: F401
