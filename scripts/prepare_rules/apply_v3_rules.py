"""apply_v3_rules — v3 规则固化（幂等，可重跑）.

目的：把「单一真源 / 禁内嵌邻接 / 规模守门」写成**通用规则**，确保下次解析任何项目都按此方案生成。
三层落地（缺一不可）：
  1) rules[]      : NG-006(结构单一真源) / NG-007(规模守门)  —— PH-2 规则束 NG-* 自动纳入
  2) dev_rules[]  : DEV-007(真源唯一化, 通用) / DEV-008(大图按需加载) —— 启动即读, 跨项目防重犯
  3) gates.G2     : 由 gate_validators.validate_netlist 强制检查 NG-006/NG-007（代码侧, 见 tools.md）
同时渲染 rules/check_list.md。
用法: PYTHONPATH=src .venv/bin/python scripts/prepare_rules/apply_v3_rules.py
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
RULES_JSON = ROOT / "rules" / "rules.json"
CHECKLIST_MD = ROOT / "docs" / "check_list.md"

# ---- 1) 规则文本（进 rules[]；PH-2 规则模式 NG-* 自动纳入）----
NEW_RULES = {
    "NG-006": ("单一真源：器件间连接仅由 devices[].pins 与 nets[].joins 承载；links[] 禁止内嵌邻接"
               "（无 upstream/downstream/via）；邻接按 side+joins 派生（GraphIndex），禁 GND/电源网 O(k²) 展开"),
    "NG-007": ("规模守门：netlist_graph.json ≤5MB（防重复内嵌导致平方膨胀）；超限须改派生/紧凑索引"),
    "NG-008": ("等值可证：图结构变更须提供等值证据（verify_adjacency：派生邻接 vs 基准逐条一致，含 model/kind）"),
}

# ---- 2) 代码生成硬性要求（dev_rules，通用、跨项目）----
NEW_DEV_RULES = [
    {"id": "DEV-007",
     "rule": "真源唯一化：任何产物 JSON，凡可由既有表派生的关联（邻接/成员表/索引）不得重复内嵌；"
             "新增字段前须评估复杂度与体积，禁止平方级(O(k²))展开；外部视图用访问器派生。",
     "enforce": True},
    {"id": "DEV-008",
     "rule": "大图按需访问：图产物>10MB 必须提供索引化/按需访问（GraphIndex），禁止『一次全量解析』为唯一消费方式。",
     "enforce": True},
]


def main() -> None:
    rj = json.loads(RULES_JSON.read_text(encoding="utf-8"))
    stage_of = {"NG-006": "PH-2", "NG-007": "PH-2", "NG-008": "PH-2"}
    added_rules = []
    for cid, title in NEW_RULES.items():
        st = stage_of[cid]
        rj["rules"][cid] = {"title": title, "source": f"v3_design::{st}::{ 'G2' if st=='PH-2' else 'G3'}",
                            "line": 0, "end_line": 0, "chars": len(title), "kind": "NG"}
        added_rules.append(cid)
    # dev_rules 追加（幂等：按 id 覆盖/新增）
    dr = rj.setdefault("dev_rules", {"schema_version": "1.0", "kind": "dev_rules",
                                     "note": "代码生成硬性要求（系统启动读取；人机同源）", "rules": []})
    have = {r["id"] for r in dr["rules"]}
    for nr in NEW_DEV_RULES:
        dr["rules"] = [r for r in dr["rules"] if r["id"] != nr["id"]] + [nr] if nr["id"] in have \
            else dr["rules"] + [nr]
    rj.setdefault("_audit", {})["v3_applied"] = {"rules": added_rules,
                                                 "dev_rules": [r["id"] for r in NEW_DEV_RULES],
                                                 "gate_enforced": ["G2:NG-006", "G2:NG-007"]}
    RULES_JSON.write_text(json.dumps(rj, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"rules.json 已更新：+{len(added_rules)} 规则 {added_rules} / dev_rules +{len(NEW_DEV_RULES)}")

    # ---- 3) 重渲染 check_list.md ----
    try:
        from scripts.prepare_rules.generate_rules import render_checklist  # type: ignore
        CHECKLIST_MD.write_text(render_checklist(rj), encoding="utf-8")
        print("check_list.md 已重渲染")
    except Exception:
        # 回退：简单渲染 NG-* 供人查阅
        lines = ["# 校验清单（rules.json 自动渲染）", ""]
        for cid, r in rj["rules"].items():
            if cid.startswith("NG-"):
                lines.append(f"- **{cid}** {r['title']}")
        lines += ["", "## 代码生成硬性要求（dev_rules）", ""]
        for r in rj["dev_rules"]["rules"]:
            lines.append(f"- **{r['id']}** {r['rule']}")
        CHECKLIST_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("check_list.md 已重渲染（回退渲染器）")


if __name__ == "__main__":
    main()
