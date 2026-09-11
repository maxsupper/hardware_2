"""apply_v4_rules — v4 规则固化（幂等，可重跑）.

目的：把「方向语义/追踪/差分对/双向验证/落点」「平台识别/加载/官方引脚核对/覆盖率」
写成通用规则，确保下次解析任何项目都按此方案生成。三层落地（缺一不可）：
  1) rules[]      : NG-010..NG-014 / PF-001..PF-005
                    —— PH-2 规则束 NG-* 自动纳入；PF-* 通配符新增到 PH-2/PH-3 规则束
  2) dev_rules[]  : DEV-009(规范先行) / DEV-010(权威来源不重复定义) / DEV-011(md→json 校验护栏)
                    —— 启动即读, 跨项目防重犯
  3) gates        : G2 强制 NG-010..014, G3 强制 PF-002/003/004（gate_enforced 审计登记）
同时渲染 rules/check_list.md。

注意：generate_rules.py 会从 raw 重建 rules.json 并覆盖本脚本增补；
     故本补丁必须在 generate_rules 之后重跑（与 apply_v2/apply_v3 同序）。

用法: PYTHONPATH=src .venv/bin/python scripts/prepare_rules/apply_v4_rules.py
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
RULES_JSON = ROOT / "rules" / "rules.json"
CHECKLIST_MD = ROOT / "docs" / "check_list.md"

# ---- 1) 规则文本（进 rules[]）----
# 条目格式与既有完全一致：{title, source, line, end_line, chars, kind}
# title 即规则正文；chars = len(title)
NEW_RULES = {
    "NG-010": ("方向语义与权威来源：links[].side∈{up,down,bi,pwr,nc}，同网络内 side 必须一致"
               "（冲突须显式标注待核）；电源/地判定必须使用 conventions 权威配置(power_net_regex)，"
               "禁止在工具代码内自造正则", "PH-2", "G2", "NG"),
    "NG-011": ("追踪规则：起点=接插件脚，止于有源落点；可跨越件=2脚R/L/BEAD/FB/FERR/JMP/0R 且两端网非电源地"
               "(conventions.is_series_passive)；最大跨器件层数 trace_max_hops=6；先判本网有源落点→已抵达不再跨件；"
               "访问集防绕圈(同一(板,网)只进一次)；超出记 DEPTH_EXCEEDED、绕圈记 OSCILLATION", "PH-2", "G2", "NG"),
    "NG-012": ("差分对语义：识别 _P/_N、P/N、H/L、+/- 命名（conventions.diff_pair_key）；"
               "差分对成员网视为同一逻辑信号，跨到配对搭档=原地打转→不前进；追到任一端芯片即视为抵达",
               "PH-2", "G2", "NG"),
    "NG-013": ("双向验证：正向止于有源落点(芯片)、反向止于起点接插件(对称停止)；正反路径集合一致且两端互达→OK；"
               "否则 MISMATCH 必须带原因分类(OSCILLATION/DEPTH_EXCEEDED/NO_ACTIVE_END/REVERSE_NOT_HOME/"
               "PATH_DIFF/POWER_BRIDGE)；落点非芯片→N/A", "PH-2", "G2", "NG"),
    "NG-014": ("落点判定：CHIP=落点有源(U*)脚；TO_CONNECTOR=落点接插件(J*/CN*/P*)；POWER=落电源/地轨；"
               "OPEN_END=本网无其他成员；STUB=仅到无源件未达有源", "PH-2", "G2", "NG"),
    "PF-001": ("平台识别：PH-2 须按 rules/index.json 的 platform.detect 规则（型号正则+最小引脚数）识别主控平台，"
               "写入 netlist_graph.meta.platform；无法匹配须记 WARNING 并允许后续人工指定", "PH-2", "G2", "PF"),
    "PF-002": ("平台规则加载：PH-3 须按 rules/index.json 的 load_policy 加载 common/*.json + "
               "platform/<芯片>/rules.json 注入 LLM；引脚数据 pinout.json 不进 LLM，由 platform_check 工具按需查询单条",
               "PH-3", "G3", "PF"),
    "PF-003": ("官方引脚核对：SoC/DDR/PMIC/eMMC 的引脚功能与电平域必须以 platform/<芯片>/pinout.json 官方表为权威"
               "(IC-007/IC-008)；不一致记 FAIL，无官方表记 WARNING", "PH-3", "G3", "PF"),
    "PF-004": ("核对覆盖率：G3 须报告引脚核对覆盖率=已核对脚数/应核对脚数；覆盖率低于阈值或存在未解释不一致 → "
               "门禁不得 PASS", "PH-3", "G3", "PF"),
    "PF-005": ("规则束预算：PH-3 全量规则束(common+platform)必须在 rule_bundle_tokens 预算内(≥58K)完整注入；"
               "发生截断时必须在日志与提示词中显式列出被丢弃规则 ID，禁止静默截断；"
               "若预算不足须先扩容而非裁剪规则", "PH-3", "G3", "PF"),
}

# ---- 前缀通配符：新增到对应阶段规则束（幂等：存在即不重复追加）----
# PH-2 仅纳入 PF-001（平台识别在 PH-2 完成）；PH-3 以 PF-* 纳入其余 PF 规则
STAGE_PATTERN_ADD = {
    "PH-2": ["PF-001*"],
    "PH-3": ["PF-*"],
}

# ---- 2) 代码生成硬性要求（dev_rules，通用、跨项目）----
NEW_DEV_RULES = [
    {"id": "DEV-009",
     "rule": "规范先行：规范(rules)是唯一权威，代码必须服从规范；实现与规范不一致时改代码而非改规范；"
             "规范缺参数化条款时须先补规范再实现。",
     "enforce": True},
    {"id": "DEV-010",
     "rule": "权威来源不重复定义：同一判定(电源/地、透明件、差分对等)只允许一处权威定义(conventions)，"
             "任何工具不得自造等价逻辑。",
     "enforce": True},
    {"id": "DEV-011",
     "rule": "md→json 转换须过 Pydantic 校验、带 source_sha1 增量、带 tokens_est 预算护栏"
             "(单文件>20k tokens 须再拆分)，并登记 src/tools.md。",
     "enforce": True},
]

GATE_ENFORCED = ["G2:NG-010..014", "G3:PF-002/003/004"]


def apply(rj: dict) -> dict:
    """幂等应用 v4 增补：rules / process 通配符 / dev_rules / _audit。"""
    # 1) rules[]：按 ID 覆盖或新增（dict 保序，重跑覆盖原位，顺序稳定）
    added_rules = []
    for cid, (title, stage, gate, kind) in NEW_RULES.items():
        rj.setdefault("rules", {})[cid] = {
            "title": title, "source": f"v4_design::{stage}::{gate}",
            "line": 0, "end_line": 0, "chars": len(title), "kind": kind,
        }
        added_rules.append(cid)

    # 2) process[]：给对应阶段追加前缀通配符（存在即跳过，保证幂等）
    for p in rj.get("process", []):
        adds = STAGE_PATTERN_ADD.get(p.get("stage"))
        if not adds:
            continue
        pats = p.setdefault("rules", [])
        for pat in adds:
            if pat not in pats:
                pats.append(pat)

    # 3) dev_rules[]：按 id 原位替换或追加（幂等、顺序稳定）
    dr = rj.setdefault("dev_rules", {"schema_version": "1.0", "kind": "dev_rules",
                                     "note": "代码生成硬性要求（系统启动读取；人机同源）", "rules": []})
    pos = {r["id"]: i for i, r in enumerate(dr["rules"])}
    for nr in NEW_DEV_RULES:
        if nr["id"] in pos:
            dr["rules"][pos[nr["id"]]] = nr
        else:
            pos[nr["id"]] = len(dr["rules"])
            dr["rules"].append(nr)

    # 4) _audit：登记 v4 落地
    rj.setdefault("_audit", {})["v4_applied"] = {
        "rules": added_rules,
        "dev_rules": [r["id"] for r in NEW_DEV_RULES],
        "gate_enforced": GATE_ENFORCED,
    }
    return rj


def main() -> None:
    rj = json.loads(RULES_JSON.read_text(encoding="utf-8"))
    before = len(rj.get("rules", {}))
    rj = apply(rj)
    RULES_JSON.write_text(json.dumps(rj, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"rules.json 已更新：规则 {before} → {len(rj['rules'])}（新增 {len(NEW_RULES)}）")

    # ---- 3) 重渲染 check_list.md ----
    try:
        from scripts.prepare_rules.generate_rules import render_checklist  # type: ignore
        CHECKLIST_MD.write_text(render_checklist(rj), encoding="utf-8")
        print("check_list.md 已重渲染")
    except Exception:
        # 回退：简单渲染 NG-*/PF-* 供人查阅
        lines = ["# 校验清单（rules.json 自动渲染）", ""]
        for cid in sorted(rj["rules"]):
            if cid.startswith(("NG-", "PF-")):
                lines.append(f"- **{cid}** {rj['rules'][cid]['title']}")
        lines += ["", "## 代码生成硬性要求（dev_rules）", ""]
        for r in rj["dev_rules"]["rules"]:
            lines.append(f"- **{r['id']}** {r['rule']}")
        CHECKLIST_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("check_list.md 已重渲染（回退渲染器）")


if __name__ == "__main__":
    main()
