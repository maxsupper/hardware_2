#!/usr/bin/env python3
"""test_topic_trim — PH-3 规则束按 IC 角色裁剪验收（PF-007 / PF-008）.

真实数据下逐 IC 断言：
  1) topics_for_device 返回的 topics 必须**包含** rule_topic_by_role[role] 的全部（不得少于角色表）；
  2) render_rules_text_ex 对该 IC **不发生截断**（dropped 为空）；
  3) 主控（meta.platform_device）的 topics == 全部可用主题；
  4) 打印角色分布、规则束总量 before(每颗全量×IC数) → after(逐颗裁剪)、下降百分比、fallback 颗数；
  5) 任一条不满足 → 退出码非 0（并要求下降 ≥25%）。

用法: PYTHONPATH=src .venv/bin/python scripts/selfcheck/test_topic_trim.py
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from hardware_analysis.flows.rule_loader import (  # noqa: E402
    load_rule_assets, render_rules_text_ex, topics_for_device, stage_topics)
from hardware_analysis.common.conventions import CONV  # noqa: E402

PRODUCT = "FL-25-E-MR203"
GRAPH = ROOT / "storge" / "project" / PRODUCT / "PH-2_网表解析" / "netlist_graph.json"
MIN_DROP_PCT = 25.0


def main() -> int:
    assert GRAPH.exists(), f"缺少真实网表 {GRAPH}"
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    meta = graph.get("meta") or {}
    platform = str(meta.get("platform") or "")
    platform_device = meta.get("platform_device")
    ics = [d for d in graph.get("devices", [])
           if d.get("kind") == "IC" and (d.get("source") or {}).get("populated")]
    assert ics, "netlist_graph 无 kind=IC 且 populated 的器件"

    available = stage_topics("PH-3", platform=platform)
    assert available, "PH-3 可用主题为空"

    full_assets = load_rule_assets("PH-3", platform=platform)
    full_text, full_dropped = render_rules_text_ex(full_assets["entries"])
    before = len(full_text) * len(ics)

    role_table = CONV.cfg.get("rule_topic_by_role") or {}
    role_dist: collections.Counter = collections.Counter()
    fails: list[str] = []
    after = 0
    truncated = 0
    fallback = 0
    trimmed_any = False
    n_ok = 0

    for d in ics:
        did = d.get("id", "?")
        sel = topics_for_device(d, graph, available)
        role = sel["role"]
        role_dist[role] += 1
        if sel.get("fallback"):
            fallback += 1

        # 1) topics ⊇ rule_topic_by_role[role]
        need = role_table.get(role, role_table.get("other", []))
        missing = [t for t in need if t not in sel["topics"]]
        if missing:
            fails.append(f"{did} role={role} 缺主题 {missing}")

        # 2) 渲染不截断 + after 累计（逐颗重算）
        try:
            assets = load_rule_assets("PH-3", platform=platform, topics=sel["topics"],
                                      include_platform=(did == platform_device))
            text, dropped = render_rules_text_ex(assets["entries"])
        except Exception as e:  # noqa: BLE001
            fails.append(f"{did} 规则束加载/渲染异常: {type(e).__name__}: {e}")
            continue
        if dropped:
            truncated += 1
            fails.append(f"{did} 规则束被截断 dropped={dropped[:5]}")
        after += len(text)
        if len(sel["topics"]) < len(available):
            trimmed_any = True
        n_ok += 1
    if full_dropped:
        fails.append(f"全量规则束被截断 dropped={len(full_dropped)}")

    # 3) 主控 topics == 全部可用主题
    main_dev = next((d for d in ics if d.get("id") == platform_device), None)
    if main_dev is None:
        fails.append(f"未找到主控器件 {platform_device}")
    else:
        selm = topics_for_device(main_dev, graph, available)
        if selm["topics"] != available:
            fails.append(f"主控 {platform_device} topics={selm['topics']} != 全部 {available}")

    drop_pct = (1 - after / before) * 100 if before else 0.0
    if drop_pct < MIN_DROP_PCT:
        fails.append(f"规则束下降 {drop_pct:.1f}% < 要求 {MIN_DROP_PCT:.0f}%")
    if not trimmed_any:
        fails.append("没有任何 IC 发生主题裁剪（规则束未按角色生效）")

    n = len(ics)
    print(f"角色分布: {dict(sorted(role_dist.items()))}")
    print(f"fallback(role=other/未知) 颗数: {fallback}/{n}")
    print(f"规则束 before(每颗全量×{n}) = {before:,} chars")
    print(f"规则束 after (逐颗裁剪)     = {after:,} chars")
    print(f"截断 IC 数: {truncated}（要求 0）")
    for f in fails:
        print(f"  [FAIL] {f}")

    ok = not fails
    verdict = "PASS" if ok else "FAIL"
    print(f"TOPIC-TRIM: {n} ICs {'PASS' if ok else 'FAIL'}, {truncated} truncated, "
          f"rules {before:,} -> {after:,} chars (-{drop_pct:.0f}%)  => {verdict}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
