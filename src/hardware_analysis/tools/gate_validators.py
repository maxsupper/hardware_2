"""Gate 校验器 — 确定性门禁（G1 手册+BOM / G2 网表 / G3 分析 / G4 报告 / G5 审计 / G6 交付）。

全部 PASS/FAIL 由确定性脚本判定（不进 LLM）；产出 gates/G{n}.json（GateResult 契约）。
用法: python -m hardware_analysis.tools.gate_validators <gate> <workspace_dir>
"""
from __future__ import annotations
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hardware_analysis.models.contracts import GateCheck, GateResult, GateStatus
from hardware_analysis.workspace.manager import RunWorkspace
from hardware_analysis.common.conventions import CONV

REQUIRED_PREP = ["global_components.json", "global_nets.json",
                 "signal_chains.json", "merge_report.json",
                 "bom_entries.json", "refdes_function_map.json"]


def _check(checks, cid, status: GateStatus, expected, actual):
    checks.append(GateCheck(id=cid, status=status, expected=expected, actual=actual))


# ---------------- G1 prep_validate ----------------
def validate_prep(b_prep_dir: Path) -> GateResult:
    checks = []
    # 1) 必需文件存在且可解析
    for f in REQUIRED_PREP:
        p = b_prep_dir / f
        ok = p.exists() and p.stat().st_size > 0
        try:
            json.loads(p.read_text(encoding="utf-8"))
            parse_ok = ok
        except Exception:
            parse_ok = False
        _check(checks, f"PREP-{len(checks)+1:03d}", GateStatus.PASS if parse_ok else GateStatus.FAIL,
               f"{f} 存在且为合法JSON", "ok" if parse_ok else "缺失/非法")
    # 2) 信号链覆盖（全局网名 vs 链覆盖）——板级键 "板::网"
    try:
        nets = json.loads((b_prep_dir / "global_nets.json").read_text(encoding="utf-8"))
        chains = json.loads((b_prep_dir / "signal_chains.json").read_text(encoding="utf-8"))
        chain_nets = set()
        for c in chains:
            for seg in c.get("path", []):
                if isinstance(seg, dict):
                    chain_nets.add(f"{seg.get('board')}::{seg.get('net')}")
                else:
                    chain_nets.add(str(seg))
        missing = [n for n in nets if n not in chain_nets]
        _check(checks, "PREP-010", GateStatus.PASS if len(missing) <= len(nets) * 0.3 else GateStatus.WARNING,
               "多数全局网进入信号链", f"未入链 {len(missing)}/{len(nets)}")
    except Exception as e:
        _check(checks, "PREP-010", GateStatus.FAIL, "读 global_nets/signal_chains", str(e)[:80])
    # 3) 合并冲突
    try:
        rep = json.loads((b_prep_dir / "merge_report.json").read_text(encoding="utf-8"))
        conf = rep.get("component_conflicts", [])
        _check(checks, "PREP-011", GateStatus.PASS if not conf else GateStatus.FAIL,
               "无元件型号冲突", str(conf)[:80])
    except Exception as e:
        _check(checks, "PREP-011", GateStatus.FAIL, "读 merge_report", str(e)[:80])
    return _finalize("G1", "prep_validate", checks)


# ---------------- G3 数据完整性 (Wave0) ----------------
def validate_data(b_prep_dir: Path) -> GateResult:
    checks = []
    try:
        nets = json.loads((b_prep_dir / "global_nets.json").read_text(encoding="utf-8"))
        # 关键总线单连接抽查：net 不应只挂 0/1 个引脚（除电源/地/NC）
        singles = [n for n, e in nets.items() if len(e.get("joins", [])) <= 1 and n not in ("GND", "VCC", "NC")]
        _check(checks, "W0-001", GateStatus.PASS if len(singles) <= 20 else GateStatus.WARNING,
               "单连接网 ≤20", f"单连接 {len(singles)} 个")
    except Exception as e:
        _check(checks, "W0-001", GateStatus.FAIL, "读 global_nets", str(e)[:80])
    return _finalize("G3", "数据完整性(Wave0)", checks)


# ---------------- v2: G3 g2x_validate（PH-3 evidence 契约） ----------------
def validate_evidence(e_dir: Path) -> GateResult:
    checks = []
    evs = sorted(set(e_dir.glob("*.evidence.json")) | set(e_dir.glob("*_evidence.json"))) if e_dir.exists() else []
    sues = sorted(e_dir.glob("*_summary.json"))
    _check(checks, "G2X-001", GateStatus.PASS if evs else GateStatus.FAIL,
           "存在 evidence 文件", f"{len(evs)} 个")
    _check(checks, "G2X-002", GateStatus.PASS if sues else GateStatus.FAIL,
           "存在 summary 文件(≤5KB)", f"{len(sues)} 个")
    for s in sues:
        try:
            d = json.loads(s.read_text(encoding="utf-8"))
            size = s.stat().st_size
            findings = d.get("findings", [])
            bad_status = [f for f in findings if f.get("severity") not in
                          ("OK", "WARNING", "CRITICAL", "INFERRED", "UNVERIFIED")]
            ok = ("findings" in d) and (d.get("checks_count", 0) <= len(findings)) \
                 and not bad_status and size <= 5120
            _check(checks, f"G2X-{3:03d}", GateStatus.PASS if ok else GateStatus.FAIL,
                   f"{s.name} 契约合规(finding/severity/≤5KB)", f"{size}B findings={len(findings)} 非法={len(bad_status)}")
        except Exception as e:
            _check(checks, "G2X-003", GateStatus.FAIL, f"{s.name} 可读", str(e)[:60])
    return _finalize("G3", "g2x_validate", checks)


# ---------------- v2: G4 报告门（PH-4；LLM 内容审核由 Flow 阶段编排） ----------------
def validate_report(f_dir: Path) -> GateResult:
    checks = []
    rp = f_dir / "report.json"
    if not rp.exists():
        return _finalize("G4", "report_gate(结构)", [
            GateCheck(id="RF-001", status=GateStatus.FAIL, expected="report.json 存在", actual="缺失")])
    try:
        d = json.loads(rp.read_text(encoding="utf-8"))
        top = {"findings": "findings" in d, "tables": "tables" in d, "narrative": "narrative" in d}
        _check(checks, "RF-001", GateStatus.PASS if all(top.values()) else GateStatus.FAIL,
               "report 含 findings/tables/narrative 三字段", str(top))
        # 表格禁止截断：rows 与 columns 长度一致
        trunc = [t.get("title", "?") for t in d.get("tables", [])
                 if len(t.get("rows", [])) > 0 and t.get("columns") and
                 any(len(r) != len(t["columns"]) for r in t["rows"])]
        _check(checks, "RF-002", GateStatus.PASS if not trunc else GateStatus.FAIL,
               "表格无截断(行/列一致)", f"异常表 {len(trunc)} 个")
    except Exception as e:
        _check(checks, "RF-001", GateStatus.FAIL, "report.json 可解析", str(e)[:80])
    return _finalize("G4", "report_gate(结构层)", checks)


# ---------------- v2: G1 manual_validate（PH-1 手册索引） ----------------
def validate_manual_index(b_prep_dir: Path) -> GateResult:
    checks = []
    p = b_prep_dir / "manual_index.json"
    ok = p.exists() and p.stat().st_size > 0
    _check(checks, "MI-000", GateStatus.PASS if ok else GateStatus.FAIL,
           "manual_index.json 存在且非空", "ok" if ok else "缺失/空")
    if ok:
        d = json.loads(p.read_text(encoding="utf-8"))
        entries = d.get("entries", {})
        bp = b_prep_dir / "bom_entries.json"
        boms = json.loads(bp.read_text(encoding="utf-8")).get("entries", {}) if bp.exists() else {}
        u_keys = [k for k, v in boms.items() if CONV.is_active(v.get("refdes", ""))]
        missing = [k for k in u_keys if k not in entries]
        _check(checks, "MI-001", GateStatus.PASS if not missing else GateStatus.WARNING,
               "manual_index 覆盖 BOM 全部 U*", f"缺 {len(missing)}/{len(u_keys)}")
        bad = [k for k, e in entries.items()
               if not e.get("manual_path") and e.get("status") not in ("MISSING", "TRULY_MISSING", "UNVERIFIED")]
        _check(checks, "MI-002", GateStatus.PASS if not bad else GateStatus.FAIL,
               "无手册者须显式 MISSING/TRULY_MISSING/UNVERIFIED", f"违规 {len(bad)}")
        bad2 = [k for k, e in entries.items()
                if e.get("ic_type") not in ("SINK", "PASS_THRU", "POWER_SRC", "UNKNOWN", "UNVERIFIED")]
        _check(checks, "MI-003", GateStatus.PASS if not bad2 else GateStatus.FAIL,
               "ic_type ∈ {SINK,PASS_THRU,POWER_SRC,UNKNOWN,UNVERIFIED}", f"违规 {len(bad2)}")
    return _finalize("G1", "manual_validate", checks)


# ---------------- v2: G2 bom_validate（PH-2 数据预检/Wave0） ----------------
def validate_bom(b_prep_dir: Path) -> GateResult:
    checks = []
    p = b_prep_dir / "bom_entries.json"
    ok = p.exists() and p.stat().st_size > 0
    _check(checks, "BOM-000", GateStatus.PASS if ok else GateStatus.FAIL,
           "bom_entries.json 存在", "ok" if ok else "缺失")
    if ok:
        d = json.loads(p.read_text(encoding="utf-8"))
        entries, errs = d.get("entries", {}), d.get("errors", [])
        _check(checks, "BOM-001", GateStatus.PASS if not errs else GateStatus.FAIL,
               "BOM 解析无错误", f"errors={len(errs)}")
        _check(checks, "BOM-002", GateStatus.PASS if entries else GateStatus.FAIL,
               "BOM 条目非空", f"entries={len(entries)}")
        boards = sorted({v.get("board", "X") for v in entries.values()})
        _check(checks, "BOM-003", GateStatus.PASS if len(boards) >= 1 else GateStatus.FAIL,
               "板号可识别", f"boards={boards}")
    return _finalize("G2", "bom_validate", checks)


# ---------------- v2: G1 manual_bom_validate（PH-1 手册检索+BOM预检，合并原 G1+G2） ----------------
def validate_manual_bom(b_prep_dir: Path) -> GateResult:
    """G1：manual_index 覆盖 + BOM 解析健康。"""
    checks = []
    p = b_prep_dir / "manual_index.json"
    ok = p.exists() and p.stat().st_size > 0
    _check(checks, "MI-000", GateStatus.PASS if ok else GateStatus.FAIL,
           "manual_index.json 存在且非空", "ok" if ok else "缺失/空")
    if ok:
        d = json.loads(p.read_text(encoding="utf-8"))
        entries = d.get("entries", {})
        bp = b_prep_dir / "bom_entries.json"
        boms = json.loads(bp.read_text(encoding="utf-8")).get("entries", {}) if bp.exists() else {}
        u_keys = [k for k, v in boms.items() if CONV.is_active(v.get("refdes", ""))]
        missing = [k for k in u_keys if k not in entries]
        _check(checks, "MI-001", GateStatus.PASS if not missing else GateStatus.WARNING,
               "manual_index 覆盖 BOM 全部 U*", f"缺 {len(missing)}/{len(u_keys)}")
        bad = [k for k, e in entries.items()
               if not e.get("manual_path") and e.get("status") not in ("MISSING", "TRULY_MISSING", "UNVERIFIED")]
        _check(checks, "MI-002", GateStatus.PASS if not bad else GateStatus.FAIL,
               "无手册者须显式 MISSING/TRULY_MISSING/UNVERIFIED", f"违规 {len(bad)}")
        bad2 = [k for k, e in entries.items()
                if e.get("ic_type") not in ("SINK", "PASS_THRU", "POWER_SRC", "UNKNOWN", "UNVERIFIED")]
        _check(checks, "MI-003", GateStatus.PASS if not bad2 else GateStatus.FAIL,
               "ic_type ∈ {SINK,PASS_THRU,POWER_SRC,UNKNOWN,UNVERIFIED}", f"违规 {len(bad2)}")
    bp = b_prep_dir / "bom_entries.json"
    bok = bp.exists() and bp.stat().st_size > 0
    _check(checks, "BOM-000", GateStatus.PASS if bok else GateStatus.FAIL,
           "bom_entries.json 存在", "ok" if bok else "缺失")
    if bok:
        bd = json.loads(bp.read_text(encoding="utf-8"))
        entries2, errs = bd.get("entries", {}), bd.get("errors", [])
        _check(checks, "BOM-001", GateStatus.PASS if not errs else GateStatus.FAIL,
               "BOM 解析无错误", f"errors={len(errs)}")
        _check(checks, "BOM-002", GateStatus.PASS if entries2 else GateStatus.FAIL,
               "BOM 条目非空", f"entries={len(entries2)}")
        _check(checks, "BOM-003", GateStatus.PASS if entries2 else GateStatus.FAIL,
               "板号可识别", f"boards={sorted({v.get('board','X') for v in entries2.values()})}")
    return _finalize("G1", "manual_bom_validate", checks)


# ---------------- v2: G2 netlist_validate（PH-2 netlist_graph 完备性） ----------------
def validate_netlist(b_prep_dir: Path) -> GateResult:
    checks = []
    p = b_prep_dir / "netlist_graph.json"
    ok = p.exists() and p.stat().st_size > 0
    _check(checks, "NG-000", GateStatus.PASS if ok else GateStatus.FAIL,
           "netlist_graph.json 存在", "ok" if ok else "缺失")
    if ok:
        d = json.loads(p.read_text(encoding="utf-8"))
        meta = d.get("meta", {})
        v = meta.get("validation", {})
        _check(checks, "NG-001", GateStatus.PASS if v.get("dangling_joins", 1) == 0 else GateStatus.FAIL,
               "dangling_joins=0（join 位号均在 devices）", f"dangling={v.get('dangling_joins')}")
        _check(checks, "NG-002", GateStatus.PASS if v.get("uncovered_pins", 1) == 0 else GateStatus.FAIL,
               "uncovered_pins=0（links 覆盖每脚）", f"uncovered={v.get('uncovered_pins')}")
        gc = b_prep_dir / "global_components.json"
        if gc.exists():
            n_gc = len(json.loads(gc.read_text(encoding="utf-8")))
            n_dev = len(d.get("devices", []))
            _check(checks, "NG-003", GateStatus.PASS if n_dev == n_gc else GateStatus.FAIL,
                   "devices 覆盖全部 (板,位号)", f"devices={n_dev} global={n_gc}")
        boards = meta.get("boards", [])
        _check(checks, "NG-004", GateStatus.PASS if len(boards) >= 1 else GateStatus.FAIL,
               "至少一板存在", f"boards={boards}")
        if len(boards) >= 2:
            xl = len(d.get("cross_board_links", []))
            _check(checks, "NG-005", GateStatus.PASS if xl > 0 else GateStatus.WARNING,
                   "多板时跨板连续已建立", f"cross_board_links={xl}")
    return _finalize("G2", "netlist_validate", checks)


# ---------------- v2: G5 audit_validate（PH-5 审计） ----------------
def validate_audit(ws_dir: Path) -> GateResult:
    checks = []
    ad = ws_dir / "PH-5_审计复核" / "audit.json"
    ok = ad.exists() and ad.stat().st_size > 0
    _check(checks, "G5-000", GateStatus.PASS if ok else GateStatus.FAIL,
           "audit.json 存在（PH-5 审计产出）", "ok" if ok else "缺失")
    if ok:
        try:
            d = json.loads(ad.read_text(encoding="utf-8"))
            st = d.get("status")
            _check(checks, "G5-001", GateStatus.PASS if st == "PASS" else GateStatus.FAIL,
                   "审计状态 PASS", f"status={st}")
            fails = [c for c in d.get("checks", []) if c.get("status") == "FAIL"]
            _check(checks, "G5-002", GateStatus.PASS if not fails else GateStatus.FAIL,
                   "审计无 FAIL 检查（SA-1..8）", f"fail 检查 {len(fails)}")
        except Exception as e:
            _check(checks, "G5-001", GateStatus.FAIL, "audit.json 可解析", str(e)[:60])
    # 证据链三方：evidence + summary + report
    e = ws_dir / "PH-3_深度分析"
    evs = sorted(set(e.glob("*.evidence.json")) | set(e.glob("*_evidence.json"))) if e.exists() else []
    sues = sorted(e.glob("*_summary.json")) if e.exists() else []
    _check(checks, "G5-003", GateStatus.PASS if evs else GateStatus.FAIL, "有 evidence", f"{len(evs)}")
    _check(checks, "G5-004", GateStatus.PASS if sues else GateStatus.FAIL, "有 summary", f"{len(sues)}")
    _check(checks, "G5-005", GateStatus.PASS if (ws_dir / "PH-4_报告合成" / "report.json").exists() else GateStatus.FAIL,
           "report.json 存在（证据链完整性）", "ok" if (ws_dir / "PH-4_报告合成" / "report.json").exists() else "缺失")
    return _finalize("G5", "audit_validate", checks)


# ---------------- v2: G6 delivery_validate（PH-6 闭环交付） ----------------
def validate_delivery(ws_dir: Path) -> GateResult:
    checks = []
    prior = [f"G{i}" for i in range(1, 6)]
    gp = ws_dir / "gates"
    missing = [g for g in prior if not (gp / f"{g}.json").exists()]
    _check(checks, "G6-000", GateStatus.PASS if not missing else GateStatus.FAIL,
           "前序门禁文件 G1..G5 齐全", f"缺 {missing}")
    failed = [g for g in prior if (gp / f"{g}.json").exists()
              and json.loads((gp / f"{g}.json").read_text(encoding="utf-8")).get("status") != "PASS"]
    _check(checks, "G6-001", GateStatus.PASS if not failed else GateStatus.FAIL,
           "前序门禁 G1..G5 全 PASS", f"FAIL={failed}")
    rp = ws_dir / "PH-4_报告合成" / "report.json"
    _check(checks, "G6-002", GateStatus.PASS if rp.exists() else GateStatus.FAIL,
           "report.json 存在", "ok" if rp.exists() else "缺失")
    _check(checks, "G6-003", GateStatus.PASS if (ws_dir / "PH-6_闭环交付" / "final_report.json").exists() else GateStatus.FAIL,
           "定版 final_report.json 存在（PH-6 产物）",
           "ok" if (ws_dir / "PH-6_闭环交付" / "final_report.json").exists() else "缺失")
    crit = []
    if rp.exists():
        try:
            r = json.loads(rp.read_text(encoding="utf-8"))
            crit = [f for f in r.get("findings", []) if f.get("severity") == "CRITICAL"]
        except Exception:
            crit = []
    _check(checks, "G6-004", GateStatus.PASS if not crit else GateStatus.WARNING,
           "无 CRITICAL 未决项", f"critical={len(crit)}")
    return _finalize("G6", "delivery_validate", checks)


def _finalize(gate, name, checks) -> GateResult:
    passed = sum(1 for c in checks if c.status == GateStatus.PASS)
    failed = sum(1 for c in checks if c.status == GateStatus.FAIL)
    warn = sum(1 for c in checks if c.status == GateStatus.WARNING)
    status = GateStatus.PASS if failed == 0 else GateStatus.FAIL
    r = GateResult(gate=gate, status=status, producer="gate_validators",
                   checked_at=datetime.now(timezone.utc).isoformat(),
                   checks=checks, summary={"pass": passed, "fail": failed, "warning": warn},
                   inputs=[], outputs=[f"gates/G{gate}.json"])
    return r


def main_gate_cli(ws_dir, gate):
    ws = Path(ws_dir)
    fns = _GATE_FNS()
    subdir, fn = fns[gate]
    r = fn(ws / subdir)
    (ws / "gates" / f"{gate}.json").write_text(r.model_dump_json(indent=1), encoding="utf-8")
    return r.status.value


def _GATE_FNS() -> dict:
    """v2 门禁映射：G1=手册+BOM G2=网表 G3=分析 G4=报告 G5=审计 G6=交付。"""
    return {"G1": ("PH-1_手册检索", validate_manual_bom),
            "G2": ("PH-2_网表解析", validate_netlist),
            "G3": ("PH-3_深度分析", validate_evidence),
            "G4": ("PH-4_报告合成", validate_report),
            "G5": (".", validate_audit),
            "G6": (".", validate_delivery)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("gate", choices=["G1", "G2", "G3", "G4", "G5", "G6"])
    ap.add_argument("workspace_dir", help="产品工作区（其下 PH-1_手册检索/PH-2_网表解析/PH-3_深度分析/PH-4_报告合成）")
    ap.add_argument("--out", default=None, help="写 gates/G<n>.json")
    args = ap.parse_args()
    ws = Path(args.workspace_dir)
    subdir, fn = _GATE_FNS()[args.gate]
    r = fn((ws / subdir).resolve())
    out = Path(args.out) if args.out else ws / "gates" / f"{args.gate}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(r.model_dump_json(indent=1), encoding="utf-8")
    print(f"{args.gate}: status={r.status.value} | checks={len(r.checks)} "
          f"(pass={r.summary['pass']} fail={r.summary['fail']} warn={r.summary['warning']})")
    for c in r.checks:
        if c.status != GateStatus.PASS:
            print(f"   [{c.status.value}] {c.id}: {c.expected} | actual={c.actual}")


if __name__ == "__main__":
    main()
