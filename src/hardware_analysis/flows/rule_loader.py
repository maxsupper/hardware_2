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


def _load_entries(path: Path, topic: str | None = None) -> list[dict]:
    """读单个规则资产文件的 entries[]（缺失/异常 → []）。

    ``topic`` 非空时给每条 entry 打 ``"_topic"``（仅内存：用新 dict 包装，不回写文件）。
    common 用 rules/index.json 的 ``common`` 键名；平台规则用 ``"platform:<芯片>"``。
    """
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return []
    es = d.get("entries") if isinstance(d, dict) else None
    if not isinstance(es, list):
        return []
    out = []
    for e in es:
        if not isinstance(e, dict):
            continue
        out.append({**e, "_topic": topic} if topic is not None else e)
    return out


def stage_topics(stage: str, platform: str = "",
                 index_path: str | Path = "rules/index.json") -> list[str]:
    """某阶段可用的规则主题名（common 键名 + 可选 `platform:<芯片>`）。

    顺序：load_policy[stage].common 原序 → platform 主题（若 policy.platform_rules 且芯片在 index）。
    缺 index/键一律返回 []（优雅降级）。
    """
    idx = load_index(index_path)
    pol = (idx.get("load_policy") or {}).get(stage) or {}
    out = [str(t) for t in (pol.get("common") or [])]
    plat = (idx.get("platform") or {}).get(platform) if platform else None
    if platform and pol.get("platform_rules") and isinstance(plat, dict):
        t = f"platform:{platform}"
        if t not in out:
            out.append(t)
    return out


def topics_for_device(device: dict, graph: dict, available_topics: list[str]) -> dict:
    """【冻结接口】按 PH-2 产出的 function.role 选 PH-3 规则主题。

    返回 ``{"topics":[...], "role":str, "reason":str, "fallback":bool}``：
      ① device["function"]["role"]；缺失/为空 → "other"
      ② topics = rule_topic_by_role[role]（role 不在表内 → other 行）；fallback=(role=="other")
      ③ 并入 rule_topic_baseline（去重，baseline 在前，顺序稳定）
      ④ 剔除非 available_topics 的名字
      ⑤ 主控(device['id']==graph['meta']['platform_device']) → topics=全部 available（role 保留）
    """
    from hardware_analysis.common.conventions import CONV   # 延迟导入（避免 common→direct→crew→assembler→rule_loader 循环）
    cfg = CONV.cfg
    role_table = cfg.get("rule_topic_by_role") or {}
    baseline = list(cfg.get("rule_topic_baseline") or [])
    all_on_unknown = bool(cfg.get("rule_topic_all_on_unknown", True))
    fn = (device.get("function") or {}) if isinstance(device, dict) else {}
    role = str(fn.get("role") or "").strip() or "other"
    fallback = False
    if role in role_table:
        role_topics = list(role_table.get(role) or [])
        fallback = (role == "other")
    else:                                    # 未知角色：按规范回退 other 行（受 all_on_unknown 控制）
        role = "other"
        role_topics = list(role_table.get("other") or []) if all_on_unknown else []
        fallback = True
    avail = [str(t) for t in (available_topics or [])]
    avail_set = set(avail)
    merged: list[str] = []
    for t in baseline + role_topics:         # ③ baseline 在前 + 去重保持稳定顺序
        if t not in merged:
            merged.append(t)
    merged = [t for t in merged if t in avail_set]   # ④ 剔除非可用主题

    platform_device = (graph.get("meta") or {}).get("platform_device") \
        if isinstance(graph, dict) else None
    is_main = bool(platform_device) and device.get("id") == platform_device
    if is_main:                             # ⑤ 主控：注入全部主题
        return {"topics": list(avail), "role": role,
                "reason": "主控器件：注入全部可用主题", "fallback": fallback}
    reason = (f"role={role}：基线+角色主题（{len(merged)} 项）" if not fallback
              else f"role={role}（未确认/未知）：注入全部可用主题（回落）")
    return {"topics": merged, "role": role, "reason": reason, "fallback": fallback}


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
                     budget_tokens: int | None = None, topics: list[str] | None = None,
                     include_platform: bool = True) -> dict:
    """按 load_policy 组装某阶段的规则束（通用主题 + 平台规则）。

    - common：读 index["common"][主题]["file"] 的 entries（rules/common/*.json）。
    - platform_rules：platform_rules==true 且 platform 命中 index["platform"] → 读其 rules
      （rules 可为字符串或文件列表，兼容 E2000）的 entries。
    - pinout：**绝不**把引脚数据放入返回值；仅返回 pinout_path 供工具按需查。
    - ``topics=None`` → 与旧版完全一致（向后兼容）；给定列表 → 仅加载列表内主题
      （common 键名 与/或 "platform:<芯片>"）；返回值新增 "topics_loaded"。
    - ``include_platform=False`` → 不加载平台规则（仍返回 pinout_path）。
    - tokens_est 超有效预算 cap → 按 entry 顺序截断（truncated=True, dropped=[完整ids]，
      over_budget_by=tokens_full-cap），不抛错。cap = min(budget_tokens|config, input_hard_cap)。
      拼接顺序：**平台规则在前、通用规则在后**；因平台规则更具体且是 P4-B 注入核心，
      截断（从尾部丢弃）时必须优先保住平台规则（否则 `platform_rules=true` 形同虚设）。
    """
    idx = load_index(index_path)
    base = _resolve(index_path).parent                # rules/
    policy = (idx.get("load_policy") or {}).get(stage) or {}

    topics_filter = None if topics is None else [str(t) for t in topics]
    entries: list[dict] = []
    sources: list[str] = []
    topics_loaded: list[str] = []
    platform_used, pinout_path = "", ""
    pentry = (idx.get("platform") or {}).get(platform) if platform else None
    plat_topic = f"platform:{platform}" if platform else ""
    want_platform = bool(platform and policy.get("platform_rules") and isinstance(pentry, dict)
                         and include_platform
                         and (topics_filter is None or plat_topic in topics_filter))
    if want_platform:
        for rel in _as_refs(pentry.get("rules")):
            got = _load_entries(base / rel, topic=plat_topic)
            if got:
                entries.extend(got)
                sources.append(str(base / rel))
                platform_used = platform
        if platform_used and plat_topic not in topics_loaded:
            topics_loaded.append(plat_topic)
    if platform and isinstance(pentry, dict):        # pinout_path 与是否加载平台规则无关
        pout = pentry.get("pinout")
        if pout:
            pinout_path = str(base / pout)

    for key in (policy.get("common") or []):
        if topics_filter is not None and key not in topics_filter:
            continue
        spec = (idx.get("common") or {}).get(key) or {}
        rel = spec.get("file") if isinstance(spec, dict) else None
        if not rel:
            continue
        got = _load_entries(base / rel, topic=key)
        if got:
            entries.extend(got)
            sources.append(str(base / rel))
            topics_loaded.append(key)

    cfg = Config()
    hard_cap = int(cfg.input_hard_cap() or 400000)   # 输入硬顶（< context_total，不可突破）
    eff = int(budget_tokens or cfg.rule_bundle_tokens())
    cap = min(eff, hard_cap)                          # 有效预算 = min(请求预算, 输入硬顶)
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
        dropped = [e.get("id") for e in entries[lo:]]   # 完整被丢弃 ID 列表（禁静默截断）
        dropped_tokens = _est_tokens(entries[lo:])

    over_budget_by = max(0, full_tokens - cap)

    return {"stage": stage, "platform": platform_used,
            "entries": _EntryList(kept, truncated=truncated, dropped=dropped,
                                  dropped_tokens=dropped_tokens),
            "rule_ids": [e.get("id") for e in kept],
            "tokens_est": _est_tokens(kept), "cap": cap,
            "under_budget": full_tokens <= cap,
            "sources": sources, "pinout_path": pinout_path,
            "topics_loaded": topics_loaded,
            "truncated": truncated, "dropped": dropped,
            "dropped_tokens": dropped_tokens,
            "over_budget_by": over_budget_by}


def render_rules_text_ex(entries: list[dict], max_chars: int | None = None,
                        per_entry_chars: int = 800) -> tuple[str, list[str]]:
    """渲染规则束为文本，返回 ``(text, dropped_rule_ids)``。

    ``max_chars=None``（新默认）= **不截断**（PF-008）；显式传入且超限时才截断（丢弃尾部完整 ID，
    并在文本末尾追加显式告警）。``per_entry_chars`` 仅截单条正文（不丢弃规则）。
    """
    parts, total, dropped = [], 0, []
    es = list(entries or [])
    for i, e in enumerate(es):
        rid = e.get("id", "")
        title = str(e.get("title", "") or "").strip()
        text = str(e.get("text", "") or "").strip()
        if per_entry_chars and len(text) > per_entry_chars:
            text = text[:per_entry_chars].rstrip() + "…"
        block = f"- [{rid}] {title}\n  {text}" if text else f"- [{rid}] {title}"
        if max_chars is not None and total + len(block) > max_chars:
            dropped = [str(x.get("id")) for x in es[i:]]
            break
        parts.append(block)
        total += len(block) + 1
    text = "\n".join(parts)
    text += truncation_warning(entries)        # 预算级截断（load_rule_assets 写入的元信息）
    if dropped:
        more = " …" if len(dropped) > 20 else ""
        text += (f"\n\n⚠️ 规则束超 max_chars={max_chars} 被截断，丢弃 {len(dropped)} 条规则: "
                 + ", ".join(dropped[:20]) + more)
    return text, dropped


def render_rules_text(entries: list[dict], max_chars: int | None = None,
                      per_entry_chars: int = 800) -> str:
    """兼容旧签名：默认**不截断**（旧默认 30000 已废弃，PF-008）。显式传 max_chars 时截断并告警。"""
    text, _ = render_rules_text_ex(entries, max_chars=max_chars, per_entry_chars=per_entry_chars)
    return text


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("stage")
    a = ap.parse_args()
    b = load_stage_bundle("rules/rules.json", a.stage)
    print(f"阶段 {a.stage}: 命中 {len(b['rule_ids'])} 条规则 | {b['chars']}字 / cap {b['cap']} | {b['budget_check']}")
    print("样例:", b["rule_ids"][:8])
