from __future__ import annotations

"""规则束懒加载器 — 阶段4（从 rules.json 按阶段/门禁取规则）。

只加载当前阶段需要的规则（budget 限定），避免上下文溢出。
"""
import json, re, sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hardware_analysis.config import Config


def _match(rule_id: str, pattern: str) -> bool:
    if pattern.endswith("*"):
        return rule_id.startswith(pattern[:-1])
    return rule_id == pattern


def load_stage_bundle(rules_path: str | Path, stage: str, budget_tokens: int | None = None) -> dict:
    rj = json.loads(Path(rules_path).read_text(encoding="utf-8"))
    stage_cfg = next((p for p in rj["process"] if p["stage"] == stage), None)
    if not stage_cfg:
        return {"stage": stage, "rules": [], "chars": 0, "under_budget": True}
    patterns = stage_cfg.get("rules", [])
    picked = {cid: r for cid, r in rj["rules"].items()
              if any(_match(cid, p) for p in patterns)}
    chars = sum(r.get("chars", 0) for r in picked.values())
    cap = budget_tokens or Config().rule_bundle_tokens()
    under = chars <= cap
    return {"stage": stage, "patterns": patterns, "rule_ids": sorted(picked),
            "rules": picked, "chars": chars, "cap": cap,
            "under_budget": under, "budget_check": "OK" if under else "OVER"}


def load_dev_rules(rules_path: str | Path = "rules/rules.json") -> list[dict]:
    """加载代码生成硬性要求（rules.json 的 dev_rules 段）。"""
    rj = json.loads(Path(rules_path).read_text(encoding="utf-8"))
    return rj.get("dev_rules", {}).get("rules", [])


# ---------------------------------------------------------------------------
# P4-B：规则束索引 / 资产加载（rules/index.json → rules/common/* + platform/*）
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parents[3]


def _resolve(path: str | Path) -> Path:
    """相对路径优先按项目根解析，其次退回 cwd（保证任意 cwd 下可用）。"""
    p = Path(path)
    if p.is_absolute():
        return p
    cand = _ROOT / p
    return cand if cand.exists() else p


def load_index(index_path: str | Path = "rules/index.json") -> dict:
    """读 rules/index.json；不存在/解析失败 → {}（优雅降级）。"""
    p = _resolve(index_path)
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _load_entries(path: Path) -> list[dict]:
    """读单个规则资产文件的 entries[]（缺失/异常 → []）。"""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return []
    es = d.get("entries") if isinstance(d, dict) else None
    return [e for e in es if isinstance(e, dict)] if isinstance(es, list) else []


def _est_tokens(entries: list[dict]) -> int:
    """token 估算（规范式）：len(json.dumps(entries, ensure_ascii=False)) // 16 * 10。"""
    return len(json.dumps(entries, ensure_ascii=False)) // 16 * 10


class _EntryList(list):
    """规则 entries 列表（附带截断元信息；render_rules_text 据此追加显式告警）。

    仍为 list 子类 → 迭代/json/切片行为与普通 list 完全一致，不影响调用方。
    """
    truncated: bool = False
    dropped: list = []
    dropped_tokens: int = 0

    def __init__(self, seq=(), truncated: bool = False, dropped=None, dropped_tokens: int = 0):
        super().__init__(seq)
        self.truncated = bool(truncated)
        self.dropped = list(dropped or [])
        self.dropped_tokens = int(dropped_tokens or 0)


def truncation_warning(entries) -> str:
    """若 entries 携带截断元信息，返回显式告警文本（含完整被丢弃 ID 列表），否则空串。"""
    if not getattr(entries, "truncated", False):
        return ""
    ids = getattr(entries, "dropped", []) or []
    return ("\n\n⚠️ 本次规则束因预算被截断，以下规则未注入: "
            + ", ".join(str(i) for i in ids))


def _as_refs(ref) -> list[str]:
    if ref is None:
        return []
    return [str(x) for x in ref] if isinstance(ref, list) else [str(ref)]


def load_rule_assets(stage: str, platform: str = "", index_path: str | Path = "rules/index.json",
                     budget_tokens: int | None = None) -> dict:
    """按 load_policy 组装某阶段的规则束（通用主题 + 平台规则）。

    - common：读 index["common"][主题]["file"] 的 entries（rules/common/*.json）。
    - platform_rules：platform_rules==true 且 platform 命中 index["platform"] → 读其 rules
      （rules 可为字符串或文件列表，兼容 E2000）的 entries。
    - pinout：**绝不**把引脚数据放入返回值；仅返回 pinout_path 供工具按需查。
    - tokens_est 超 budget_tokens → 按 entry 顺序截断（truncated=True, dropped=[ids]），不抛错。
      拼接顺序：**平台规则在前、通用规则在后**；因平台规则更具体且是 P4-B 注入核心，
      截断（从尾部丢弃）时必须优先保住平台规则（否则 `platform_rules=true` 形同虚设）。
    """
    idx = load_index(index_path)
    base = _resolve(index_path).parent                # rules/
    policy = (idx.get("load_policy") or {}).get(stage) or {}

    entries: list[dict] = []
    sources: list[str] = []
    platform_used, pinout_path = "", ""
    pentry = (idx.get("platform") or {}).get(platform) if platform else None
    if platform and policy.get("platform_rules") and isinstance(pentry, dict):
        for rel in _as_refs(pentry.get("rules")):
            got = _load_entries(base / rel)
            if got:
                entries.extend(got)
                sources.append(str(base / rel))
                platform_used = platform
        pout = pentry.get("pinout")
        if pout:
            pinout_path = str(base / pout)

    for key in (policy.get("common") or []):
        spec = (idx.get("common") or {}).get(key) or {}
        rel = spec.get("file") if isinstance(spec, dict) else None
        if not rel:
            continue
        got = _load_entries(base / rel)
        if got:
            entries.extend(got)
            sources.append(str(base / rel))

    cap = int(budget_tokens or Config().rule_bundle_tokens())
    full_tokens = _est_tokens(entries)
    truncated, dropped, kept = False, [], entries
    dropped_tokens = 0
    if full_tokens > cap:                             # 按 entry 顺序截断（保留最长可容前缀）
        truncated = True
        lo, hi = 0, len(entries)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if _est_tokens(entries[:mid]) <= cap:
                lo = mid
            else:
                hi = mid - 1
        kept = entries[:lo]
        dropped = [e.get("id") for e in entries[lo:]]
        dropped_tokens = _est_tokens(entries[lo:])

    return {"stage": stage, "platform": platform_used,
            "entries": _EntryList(kept, truncated=truncated, dropped=dropped,
                                  dropped_tokens=dropped_tokens),
            "rule_ids": [e.get("id") for e in kept],
            "tokens_est": _est_tokens(kept), "cap": cap,
            "under_budget": full_tokens <= cap,
            "sources": sources, "pinout_path": pinout_path,
            "truncated": truncated, "dropped": dropped,
            "dropped_tokens": dropped_tokens}


def render_rules_text(entries: list[dict], max_chars: int = 30000,
                      per_entry_chars: int = 800) -> str:
    """把 entries 渲染为注入 LLM 的文本：`- [ID] title\n  text`（每条约 800 字，总长上限）。"""
    parts, total = [], 0
    for e in entries or []:
        rid = e.get("id", "")
        title = str(e.get("title", "") or "").strip()
        text = str(e.get("text", "") or "").strip()
        if per_entry_chars and len(text) > per_entry_chars:
            text = text[:per_entry_chars].rstrip() + "…"
        block = f"- [{rid}] {title}\n  {text}" if text else f"- [{rid}] {title}"
        if total + len(block) > max_chars:
            break
        parts.append(block)
        total += len(block) + 1
    text = "\n".join(parts)
    return text + truncation_warning(entries)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("stage")
    a = ap.parse_args()
    b = load_stage_bundle("rules/rules.json", a.stage)
    print(f"阶段 {a.stage}: 命中 {len(b['rule_ids'])} 条规则 | {b['chars']}字 / cap {b['cap']} | {b['budget_check']}")
    print("样例:", b["rule_ids"][:8])
