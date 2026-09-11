#!/usr/bin/env python3
"""test_platforms — 全平台链路回归（RK3588 / RK3576 / RV1126B / E2000）.

对每个平台逐一验证「识别 → 规则加载(不截断/不注入引脚数据) → platform_check → G3 门禁」。
用真实 netlist_graph 造副本（把主控 model 改为 <芯片>X，脚数 889 ≥ 各平台 min_pins）。
任一平台失败 → 退出码非 0。

用法: PYTHONPATH=src .venv/bin/python scripts/selfcheck/test_platforms.py
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from hardware_analysis.tools.netlist_graph import _load_platform_specs  # noqa: E402
from hardware_analysis.flows.rule_loader import load_rule_assets  # noqa: E402
from hardware_analysis.tools import platform_check as pc  # noqa: E402
from hardware_analysis.tools import gate_validators as gv  # noqa: E402

PLATFORMS = ["RK3588", "RK3576", "RV1126B", "E2000"]
REAL_GRAPH = ROOT / "storge" / "project" / "FL-25-E-MR203" / "PH-2_网表解析" / "netlist_graph.json"
SOC_ID = "A::U6"
SOC_MODEL_SUFFIX = "X"


def _load_real_graph() -> dict:
    return json.loads(REAL_GRAPH.read_text(encoding="utf-8"))


def _graph_with_model(chip: str) -> dict:
    """真实图副本：主控 A::U6 的 model → <chip>X（脚数不变 889）。"""
    d = _load_real_graph()
    for dev in d.get("devices", []):
        if dev.get("id") == SOC_ID:
            dev["model"] = chip + SOC_MODEL_SUFFIX
    d.setdefault("meta", {})["platform"] = chip
    return d


def _detect_by_specs(model: str, npins: int) -> list[str]:
    """用 rules/index.json 的 detect(model_regex+min_pins) 判定命中平台。"""
    specs = _load_platform_specs(ROOT)
    hits = []
    for chip, spec in specs.items():
        rx = str(spec.get("model_regex") or chip)
        if re.search(rx, model, re.I) and npins >= int(spec.get("min_pins") or 0):
            hits.append(chip)
    return hits


def run_platform(chip: str) -> None:
    """逐项断言；任一 assert 失败即抛出。"""
    graph = _graph_with_model(chip)
    soc = next((d for d in graph.get("devices", []) if d.get("id") == SOC_ID), None)
    assert soc is not None, f"{SOC_ID} 不存在"
    npins = len(soc.get("pins") or {})
    assert npins >= 100, f"{SOC_ID} 脚数异常 {npins}"

    # 1) 识别：model=<chip>X → 唯一命中该平台
    hits = _detect_by_specs(soc["model"], npins)
    assert hits == [chip], f"识别失败 model={soc['model']} hits={hits}"

    # 2) 规则加载：不截断 / 不丢规则 / 不注入引脚数据
    a = load_rule_assets("PH-3", platform=chip)
    assert a["truncated"] is False, f"规则束被截断 dropped={len(a.get('dropped', []))}"
    assert a["dropped"] == [], f"存在被丢弃规则 {a['dropped']}"
    assert a["entries"], "规则束为空"
    assert a["pinout_path"].endswith(f"platform/{chip}/pinout.json"), \
        f"pinout_path 异常 {a['pinout_path']}"
    blob = json.dumps(a["entries"], ensure_ascii=False)
    assert "power_domain" not in blob and "by_pin" not in blob, "引脚数据被注入规则束"

    with tempfile.TemporaryDirectory() as td:
        prep = Path(td) / "PH-2_网表解析"
        e_dir = Path(td) / "PH-3_深度分析"
        prep.mkdir(parents=True)
        e_dir.mkdir(parents=True)
        (prep / "netlist_graph.json").write_text(
            json.dumps(graph, ensure_ascii=False), encoding="utf-8")

        # 3) 引脚核对（函数入口 platform_check.run）
        rep = pc.run(prep, chip)
        assert rep["platform"] == chip, f"platform_check 平台={rep['platform']}"
        assert rep["coverage"]["fill_rate"] > 0, "覆盖率 fill_rate 为 0"

        # 4) G3 门禁：PH-3_深度分析/platform_check.json + PH-2 netlist_graph
        (e_dir / "platform_check.json").write_text(
            json.dumps(rep, ensure_ascii=False), encoding="utf-8")
        res = gv.validate_evidence(e_dir)
        ids = {c.id for c in res.checks}
        assert {"PF-001", "PF-003", "PF-004"} <= ids, f"G3 缺 PF 检查 {sorted(ids)}"


def main() -> int:
    assert REAL_GRAPH.exists(), f"缺少真实网表 {REAL_GRAPH}"
    results: dict[str, bool] = {}
    for chip in PLATFORMS:
        try:
            run_platform(chip)
            results[chip] = True
            print(f"[{chip}] PASS")
        except Exception as e:  # noqa: BLE001
            results[chip] = False
            print(f"[{chip}] FAIL: {type(e).__name__}: {e}")
    line = " / ".join(f"{c} {'PASS' if results[c] else 'FAIL'}" for c in PLATFORMS)
    all_pass = all(results[c] for c in PLATFORMS)
    print(f"{line}  => {'ALL PASS' if all_pass else 'FAIL'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
