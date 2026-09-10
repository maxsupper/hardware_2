"""Gate 校验器 — 阶段3b 确定性门禁（G1/G3/G4/G5；G2 人机/ G6/G7 在 Flow 阶段编排）.

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

REQUIRED_PREP = ["global_components.json", "global_nets.json",
                 "cross_board_nets.json", "signal_chains.json", "merge_report.json",
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
    # 2) 信号链覆盖（全局网名 vs 链覆盖）
    try:
        nets = json.loads((b_prep_dir / "global_nets.json").read_text(encoding="utf-8"))
        chains = json.loads((b_prep_dir / "signal_chains.json").read_text(encoding="utf-8"))
        chain_nets = {n for c in chains for n in c.get("path", [])}
        missing = [n for n in nets if n not in chain_nets]
        _check(checks, "PREP-010", GateStatus.PASS if not missing else GateStatus.WARNING,
               "全部全局网进入信号链", f"未入链 {len(missing)} 个")
    except Exception as e:
        _check(checks, "PREP-010", GateStatus.FAIL, "读 global_nets/signal_chains", str(e)[:80])
    # 3) 合并冲突
    try:
        rep = json.loads((b_prep_dir / "merge_report.json").read_text(encoding="utf-8"))
        _check(checks, "PREP-011", GateStatus.PASS if not rep.get("component_conflicts") else GateStatus.FAIL,
               "无元件型号冲突", str(rep.get("component_conflicts", []))[:80])
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


# ---------------- G4 g2x_validate（evidence 契约） ----------------
def validate_evidence(e_dir: Path) -> GateResult:
    checks = []
    evs = sorted(e_dir.glob("*.evidence.json")) if e_dir.exists() else []
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
            bad_status = [f for f in findings if f.get("status") not in
                          ("OK", "WARNING", "CRITICAL", "INFERRED", "UNVERIFIED")]
            ok = ("findings" in d) and (d.get("checks_count", 0) <= len(findings)) \
                 and not bad_status and size <= 5120
            _check(checks, f"G2X-{3:03d}", GateStatus.PASS if ok else GateStatus.FAIL,
                   f"{s.name} 契约合规(finding/status/≤5KB)", f"{size}B findings={len(findings)} 非法={len(bad_status)}")
        except Exception as e:
            _check(checks, "G2X-003", GateStatus.FAIL, f"{s.name} 可读", str(e)[:60])
    return _finalize("G4", "g2x_validate", checks)


# ---------------- G5 报告门（结构层；LLM 内容审核由 Flow 阶段编排） ----------------
def validate_report(f_dir: Path) -> GateResult:
    checks = []
    rp = f_dir / "report.json"
    if not rp.exists():
        return _finalize("G5", "report_gate(结构)", [
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
    return _finalize("G5", "report_gate(结构层)", checks)


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
    fns = {"G1": ("B_prep", validate_prep), "G3": ("B_prep", validate_data),
           "G4": ("E_analyze", validate_evidence), "G5": ("F_report", validate_report)}
    subdir, fn = fns[gate]
    r = fn(ws / subdir)
    (ws / "gates" / f"{gate}.json").write_text(r.model_dump_json(indent=1), encoding="utf-8")
    return r.status.value


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("gate", choices=["G1", "G3", "G4", "G5"])
    ap.add_argument("workspace_dir", help="产品工作区（其下 B_prep/E_analyze/F_report）")
    ap.add_argument("--out", default=None, help="写 gates/G<n>.json")
    args = ap.parse_args()
    ws = Path(args.workspace_dir)
    fns = {"G1": ("B_prep", validate_prep), "G3": ("B_prep", validate_data),
           "G4": ("E_analyze", validate_evidence), "G5": ("F_report", validate_report)}
    subdir, fn = fns[args.gate]
    r = fn(ws / subdir)
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
