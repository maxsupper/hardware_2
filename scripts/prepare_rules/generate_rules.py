"""rules.json 生成器 — 阶段1c 产物 B.

从 inventory+mapping 生成 rules/rules.json（单一事实源）+ 渲染 rules/check_list.md。
只读 raw；幂等可重跑；输出与 reverse_check 保持闭合。
用法: python -m scripts.prepare_rules.generate_rules
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.prepare_rules.numbering_dict import DERIVE_DIR, RAW_DIR

ROOT = Path(__file__).resolve().parents[2]
RULES_JSON = ROOT / "rules" / "rules.json"
CHECKLIST_MD = ROOT / "rules" / "check_list.md"

# ---- 流程/门禁/角色（已确认设计的常量化，随设计变更改此表）----
PROCESS = [
    {"stage": "PH-0", "name": "输入准备", "owner": "human+flow", "gate": None,
     "rules": [], "batch_boundary": False},
    {"stage": "PH-1", "name": "手册检索+BOM预检(由BOM清单)", "owner": "hw_search",
     "gate": "G1", "rules": ["G0-*", "RG0-*", "MI-*"], "batch_boundary": True},
    {"stage": "PH-2", "name": "网表解析(netlist_graph+子agent分发)", "owner": "hw_prep",
     "gate": "G2", "rules": ["PREP-*", "NG-*"], "batch_boundary": False},
    {"stage": "PH-3", "name": "深度分析(芯片级并行<=5,只读netlist_graph+复核+回环)", "owner": "hw_analyze",
     "gate": "G3", "rules": ["IC-*", "PO-*", "CN-*", "DR-*", "PE-*", "LS-*", "PB-*", "IF-*", "CL-*"], "batch_boundary": True},
    {"stage": "PH-4", "name": "报告合成(report.json+渲染.md)", "owner": "hw_write",
     "gate": "G4", "rules": ["RF-*", "CT-*"], "batch_boundary": False},
    {"stage": "PH-5", "name": "审计复核", "owner": "hw_auditor",
     "gate": "G5", "rules": ["SA-*", "Q-*"], "batch_boundary": True},
    {"stage": "PH-6", "name": "闭环交付", "owner": "flow",
     "gate": "G6", "rules": [], "batch_boundary": False},
]
GATES = {
    "G1": {"name": "manual_bom_validate", "after": "PH-1", "note": "manual_index 覆盖全部U* + BOM解析无错误/条目非空/板号可识别"},
    "G2": {"name": "netlist_validate", "after": "PH-2", "note": "netlist_graph完备性：dangling=0/uncovered=0/devices全覆盖/跨板连续"},
    "G3": {"name": "g2x_validate", "after": "PH-3", "note": "evidence契约/填充率>=80%/接口覆盖(确定性)+复核回环<=3轮(计数独立)"},
    "G4": {"name": "报告审核门", "after": "PH-4", "note": "确定性结构校验 + LLM内容审核(规则+要求+内容,有界2轮)"},
    "G5": {"name": "审计门", "after": "PH-5", "note": "SA-1..8自审 + 证据链三方对照(确定性+审计输出)"},
    "G6": {"name": "闭环交付门", "after": "PH-6", "note": "未决项清空/定版/final+渲染.md"},
}
AGENTS = {
    "hw_review": {"type": "flow", "model": None,
                  "bootstrap": ["ROLE-*", "GATE-*"], "note": "编排器=Flow确定性裁判，非LLM"},
    "hw_search": {"type": "agent", "model": "flash", "bootstrap": ["CT-*", "G0-*"],
                  "tools": ["refbook_search", "web_search", "web_extract", "web_download"],
                  "note": "G0 手册检索；本地recursive+模糊→Tavily≥2策略→≥3次有效尝试→存档datasheet"},
    "hw_prep":   {"type": "agent", "model": "flash", "bootstrap": ["CT-*", "PREP-*"],
                  "tools": ["edn_parse", "edn_global_merge", "tracer"], "note": "网表解析+LLM兜底"},
    "hw_analyze": {"type": "agent", "model": "flash", "bootstrap": ["CT-*", "IC-*", "PO-*", "CN-*", "DR-*", "PE-*", "LS-*", "PB-*", "IF-*"],
                   "tools": ["tracer", "subgraph_extractor_d2", "manual_lookup", "power_tree_merger"],
                   "note": "深度分析+LLM补盲(共享D2子图)"},
    "hw_write":  {"type": "agent", "model": "flash", "bootstrap": ["RF-*", "CT-*"],
                  "tools": [], "note": "报告合成 report.json + 渲染.md"},
    "hw_auditor":{"type": "agent", "model": "flash", "bootstrap": ["SA-*", "Q-*", "RF-*"],
                  "tools": ["gate_validator"], "note": "审计+证据链，只审不改"},
    "hw_master": {"type": "agent", "model": "flash", "bootstrap": ["CT-*", "IC-*", "PO-*"],
                  "tools": ["refdes_map", "subgraph_extractor_d2", "manual_lookup"], "note": "按需故障分析顾问"},
}
PLATFORM_BUNDLES = {
    "E2000":  {"bundle": "rules/platform/E2000/", "sources": ["raw_platmform/E2000/数据手册.md", "raw_platmform/E2000/pinout.json"]},
    "RK3576": {"bundle": "rules/platform/RK3576/", "sources": ["raw_platmform/RK3576/hardware_check.md", "raw_platmform/RK3576/pinout.json", "raw_platmform/RK3576/pinout.md"]},
    "RK3588": {"bundle": "rules/platform/RK3588/", "sources": ["raw_platmform/RK3588/hardware_check.md", "raw_platmform/RK3588/pinout.json", "raw_platmform/RK3588/pinout.md"]},
    "RV1126B":{"bundle": "rules/platform/RV1126B/", "sources": ["raw_platmform/RV1126B/hardware_check.md", "raw_platmform/RV1126B/pinout.json", "raw_platmform/RV1126B/pinout.md"]},
}
PATH_MAP = {  # B-01 路径域映射（raw 约定 → 本项目）
    ".sisyphus/runs/{项目}-{时间戳}/": "storge/project/<产品>/",
    ".sisyphus/temp/": "<产品>/.run/temp/",
    ".sisyphus/evidence/": "storge/project/<产品>/PH-4_analyze/evidence/",
    "{REFBOOK_DIR}": "storge/refbook",
    "{DOWNLOAD_DIR}": "storge/datasheet",
    "报告输出(项目根)": "storge/project/<产品>/PH-5_report/",
}


def build_rules_json(mapping: dict) -> dict:
    c2r = mapping["canonical_to_raw"]
    rules = {}
    for cid, info in c2r.items():
        rules[cid] = {
            "title": info.get("title", "")[:100],
            "source": info["source"],
            "line": info["line"],
            "end_line": info["end_line"],
            "chars": info["body_chars"],
            "kind": cid.split("-")[0].split(":")[0],
        }
    return {
        "schema_version": "1.0",
        "kind": "rules_master_single_source",
        "config_ref": "config.json",
        "process": PROCESS,
        "gates": GATES,
        "agents": AGENTS,
        "rules": rules,
        "platform": PLATFORM_BUNDLES,
        "path_map": PATH_MAP,
        "_audit": {"raw_sections": mapping["raw_sections_total"], "canonical": len(c2r)},
    }


def render_checklist(rj: dict) -> str:
    L = ["# 硬件审查检查清单（流程 → 负责人 → 规则编号）\n",
         "> 由 rules/rules.json 自动渲染，**人工只维护 rules.json**，勿手改本文件。\n"]
    L.append("\n## 流程总表\n")
    L.append("| 阶段 | 名称 | 负责人 | 门禁 | 规则束 | 批次暂停 |")
    L.append("|---|---|---|---|---|---|")
    for p in rj["process"]:
        L.append(f"| {p['stage']} | {p['name']} | {p['owner']} | {p['gate'] or '-'} | "
                 f"{'、'.join(p['rules']) or '-'} | {'✔' if p['batch_boundary'] else ''} |")
    L.append("\n## 门禁\n")
    for g, v in rj["gates"].items():
        L.append(f"- **{g}**（{v['name']}）@ {v['after']}：{v['note']}")
    L.append("\n## 规则编目（按规范 ID，由 raw 清册迭代生成，共 "
             f"{len(rj['rules'])} 条）\n")
    L.append("| ID | 标题 | 源位置 | 行 |")
    L.append("|---|---|---|---|")
    for cid in sorted(rj["rules"]):
        r = rj["rules"][cid]
        L.append(f"| {cid} | {r['title'][:40]} | {r['source']} | {r['line']} |")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mapping", default=str(DERIVE_DIR / "mapping.json"))
    args = ap.parse_args()
    mapping = json.loads(Path(args.mapping).read_text(encoding="utf-8"))
    rj = build_rules_json(mapping)
    RULES_JSON.parent.mkdir(parents=True, exist_ok=True)
    CHECKLIST_MD.write_text(render_checklist(rj), encoding="utf-8")
    # 平台来源存在性直接并入 rules.json 的 platform 段（不再写 rules/platform/*/bundle.json 冗余文件）
    for chip, b in PLATFORM_BUNDLES.items():
        rj["platform"].setdefault(chip, {}).setdefault("sources", b["sources"])
        rj["platform"][chip]["sources_exist"] = {s: (RAW_DIR / s).exists() for s in b["sources"]}
    RULES_JSON.write_text(json.dumps(rj, ensure_ascii=False, indent=1), encoding="utf-8")
    print("注意：本脚本从 raw 重建 rules.json，会覆盖 apply_v2_rules 的 v2 修订；请随后重跑 apply_v2_rules。")
    print(f"已写: {RULES_JSON} | 规则条数 = {len(rj['rules'])}")
    print(f"已写: {CHECKLIST_MD}")
    print("平台 bundles:", ", ".join(PLATFORM_BUNDLES.keys()))


if __name__ == "__main__":
    main()
