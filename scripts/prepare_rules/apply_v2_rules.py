"""apply_v2_rules — 将 v2 修订（阶段换位/netlist_graph/回环/门禁重排）实际写回 rules.json.

原则：**不改既有 218 条规则的规则内容**；仅改 process/gates/agents 结构元数据 + 新增 MI/NG/CL 条目。
幂等可重跑；同时重渲染 rules/check_list.md。
用法: python -m scripts.prepare_rules.apply_v2_rules
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
RULES_JSON = ROOT / "rules" / "rules.json"
CHECKLIST_MD = ROOT / "rules" / "check_list.md"

NEW_RULES = {
    "MI-001": ("manual_index 覆盖 BOM 全部 U* 位号，无手册者须显式 MISSING/TRULY_MISSING/UNVERIFIED", "PH-1", "G1"),
    "MI-002": ("ic_type ∈ {SINK,PASS_THRU,POWER_SRC,UNVERIFIED}；PASS_THRU 必须有 channels", "PH-1", "G1"),
    "MI-003": ("手册检索链：refbook 本地优先 → 未中 Tavily≥2 策略 → 合计≥3 次有效尝试", "PH-1", "G1"),
    "NG-001": ("netlist_graph：devices 覆盖全部 (板,位号)，pins 为全量引脚", "PH-3", "G3"),
    "NG-002": ("links 覆盖每个非串联器件引脚（uncovered=0）；纯芯片间网 side=bi", "PH-3", "G3"),
    "NG-003": ("跨板仅经 cross_board_links（连接器按脚号一一配对，禁 GND 塌缩）", "PH-3", "G3"),
    "NG-004": ("0Ω 两端归 alias_group；差分对 _P/_N 归 diff_pairs；电源环路 side=pwr", "PH-3", "G3"),
    "NG-005": ("dangling_joins=0（每个 join 的位号存在于 devices）；BOM/EDN 冲突以 BOM 为准", "PH-3", "G3"),
    "CL-001": ("PH-4↔PH-3 回环 request/resolution 为 JSON、有界≤3 轮、计数独立；3 轮未决→UNVERIFIED 进待核清单", "PH-4", "G4"),
    "CL-002": ("PH-4 不得读原始 EDN/xlsx，仅读 netlist_graph.json（除走回环定向复查）", "PH-4", "G4"),
}

PROCESS = [
    {"stage": "PH-0", "name": "输入准备", "owner": "human+flow", "gate": None, "rules": [], "batch_boundary": False},
    {"stage": "PH-1", "name": "手册检索+BOM预检(由BOM清单)", "owner": "hw_search", "gate": "G1",
     "rules": ["G0-*", "RG0-*", "MI-*"], "batch_boundary": True},
    {"stage": "PH-2", "name": "网表解析(netlist_graph+子agent分发)", "owner": "hw_prep", "gate": "G2",
     "rules": ["PREP-*", "NG-*"], "batch_boundary": False},
    {"stage": "PH-3", "name": "深度分析(芯片级并行<=5,只读netlist_graph+复核+回环)", "owner": "hw_analyze", "gate": "G3",
     "rules": ["IC-*", "PO-*", "CN-*", "DR-*", "PE-*", "LS-*", "PB-*", "IF-*", "CL-*"], "batch_boundary": True},
    {"stage": "PH-4", "name": "报告合成(report.json+渲染.md)", "owner": "hw_write", "gate": "G4",
     "rules": ["RF-*", "CT-*"], "batch_boundary": False},
    {"stage": "PH-5", "name": "审计复核", "owner": "hw_auditor", "gate": "G5",
     "rules": ["SA-*", "Q-*"], "batch_boundary": True},
    {"stage": "PH-6", "name": "闭环交付", "owner": "flow", "gate": "G6", "rules": [], "batch_boundary": False},
]

GATES = {
    "G1": {"name": "manual_bom_validate", "after": "PH-1", "note": "manual_index 覆盖全部U* + BOM解析无错误/条目非空/板号可识别"},
    "G2": {"name": "netlist_validate", "after": "PH-2", "note": "netlist_graph完备性：dangling=0/uncovered=0/devices全覆盖/跨板连续"},
    "G3": {"name": "g2x_validate", "after": "PH-3", "note": "evidence契约/填充率>=80%/接口覆盖(确定性)+复核回环<=3轮(计数独立)"},
    "G4": {"name": "报告审核门", "after": "PH-4", "note": "确定性结构校验 + LLM内容审核(规则+要求+内容,有界2轮)"},
    "G5": {"name": "审计门", "after": "PH-5", "note": "SA-1..8自审 + 证据链三方对照(确定性+审计输出)"},
    "G6": {"name": "闭环交付门", "after": "PH-6", "note": "未决项清空/定版/final+渲染.md"},
}


def apply(rj: dict) -> dict:
    rj["process"] = PROCESS
    rj["gates"] = GATES
    a = rj["agents"]
    a["hw_search"].update({
        "bootstrap": ["CT-*", "G0-*", "MI-*"],
        "tools": ["refbook_search", "web_search", "web_extract", "web_download", "manual_index"],
        "note": "PH-1 由 BOM(Word/Excel) 取唯一 IC 型号检索；产 manual_index.json + ic_type 判定"})
    a["hw_prep"].update({
        "bootstrap": ["CT-*", "PREP-*", "NG-*"],
        "tools": ["edn_parse", "edn_global_merge", "bom_parse", "refdes_map", "tracer", "netlist_graph"],
        "note": "PH-3 网表解析 + netlist_graph 组装 + 按接插件数量子 agent 分发合并"})
    a["hw_analyze"].update({
        "bootstrap": ["CT-*", "IC-*", "PO-*", "CN-*", "DR-*", "PE-*", "LS-*", "PB-*", "IF-*", "CL-*"],
        "tools": ["netlist_slice", "subgraph_extractor_d2", "manual_lookup", "power_tree_merger"],
        "note": "PH-4 只读 netlist_graph.json；兼做 tracer 判定复核；不清晰走回环(≤3轮)请求 PH-3 重核"})
    a["hw_review"]["note"] = ("Flow 确定性裁判：PH-0..6 新序(G1手册+BOM/G2网表/G3分析/G4报告/G5审计/G6交付)；"
                             "Gate FAIL 单向阻断；协调 PH-2↔PH-3 回环(≤3轮,计数独立)")
    for cid, (title, stage, gate) in NEW_RULES.items():
        rj["rules"][cid] = {"title": title, "source": f"v2_design::{stage}::{gate}",
                            "line": 0, "end_line": 0, "chars": len(title), "kind": cid.split("-")[0]}
    for cid, st in (("NG-001", "PH-2"), ("NG-002", "PH-2"), ("NG-003", "PH-2"), ("NG-004", "PH-2"),
                    ("NG-005", "PH-2"), ("CL-001", "PH-3"), ("CL-002", "PH-3")):
        if cid in rj["rules"]:
            rj["rules"][cid]["source"] = f"v2_design::{st}::{'G2' if st == 'PH-2' else 'G3'}"
    aud = rj.setdefault("_audit", {})
    aud["v2_applied"] = "2026-09-11: process换位/gates重排/agents更新 + 新增 MI/NG/CL " \
                        f"{len(NEW_RULES)} 条（既有218条内容未改）"
    return rj


def main() -> None:
    rj = json.loads(RULES_JSON.read_text(encoding="utf-8"))
    before = len(rj["rules"])
    rj = apply(rj)
    RULES_JSON.write_text(json.dumps(rj, ensure_ascii=False, indent=1), encoding="utf-8")
    # 重渲染 check_list.md（复用生成器纯函数）
    from scripts.prepare_rules.generate_rules import render_checklist
    CHECKLIST_MD.write_text(render_checklist(rj), encoding="utf-8")
    print(f"rules.json 已更新：规则 {before} → {len(rj['rules'])}（新增 {len(NEW_RULES)}）")
    print("process:", " → ".join(f"{p['stage']}/{p['name'].split('(')[0]}" for p in rj["process"]))
    print("gates  :", " ".join(f"{g}={v['name']}" for g, v in rj["gates"].items()))
    print("check_list.md 已重渲染")


if __name__ == "__main__":
    main()
