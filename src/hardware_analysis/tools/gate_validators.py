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

# PF-004 官方引脚覆盖率阈值（可被 config.json 的 conventions.platform_coverage_min 覆盖）
PLATFORM_COVERAGE_MIN = 0.5


def _check(checks, cid, status: GateStatus, expected, actual):
    checks.append(GateCheck(id=cid, status=status, expected=expected, actual=actual))


# ---------------- 平台一致性（P4-C：PF-001/003/004 接入 G3） ----------------
def _platform_coverage_min() -> float:
    """PF-004 阈值：conventions.platform_coverage_min 可覆盖，默认 PLATFORM_COVERAGE_MIN。"""
    try:
        return float(CONV.cfg.get("platform_coverage_min", PLATFORM_COVERAGE_MIN))
    except (TypeError, ValueError):
        return PLATFORM_COVERAGE_MIN


def _find_rules_index(ws: Path) -> Path | None:
    """定位 rules/index.json：优先包根（与 platform_check.ROOT 一致），再从工作区向上回退。"""
    cands = [Path(__file__).resolve().parents[3] / "rules" / "index.json"]
    cands += [p / "rules" / "index.json" for p in (ws, *ws.parents)]
    seen = set()
    for c in cands:
        if c in seen:
            continue
        seen.add(c)
        if c.exists():
            return c
    return None


def _platform_keys(ws: Path) -> set[str]:
    """rules/index.json 的 platform 键集合（缺失/非法一律空集，不抛错）。"""
    idx = _find_rules_index(ws)
    if not idx:
        return set()
    try:
        d = json.loads(idx.read_text(encoding="utf-8"))
    except Exception:
        return set()
    pl = d.get("platform")
    return set(pl.keys()) if isinstance(pl, dict) else set()


def _find_platform_check(e_dir: Path, prep_dir: Path) -> Path | None:
    """PF-003/PF-004 产物定位：先 PH-3_深度分析/，再 PH-2_网表解析/。"""
    for c in (e_dir / "platform_check.json", prep_dir / "platform_check.json"):
        if c.exists() and c.stat().st_size > 0:
            return c
    return None


def _append_platform_checks(checks, e_dir: Path) -> None:
    """PF-001 平台识别 / PF-003 官方核对无 FAIL / PF-004 覆盖率门限（+ PF-005 官方表缺口）。

    WARNING 不影响 G3 整体（_finalize 仅 FAIL 致门禁 FAIL）；缺产物/缺 platform 一律优雅降级。
    """
    ws = e_dir.parent
    prep_dir = ws / "PH-2_网表解析"

    meta_platform = ""
    gp = prep_dir / "netlist_graph.json"
    if gp.exists():
        try:
            meta_platform = str((json.loads(gp.read_text(encoding="utf-8")).get("meta") or {})
                                .get("platform") or "").strip()
        except Exception:
            meta_platform = ""

    pc_path = _find_platform_check(e_dir, prep_dir)
    pc = None
    if pc_path is not None:
        try:
            pc = json.loads(pc_path.read_text(encoding="utf-8"))
        except Exception:
            pc = None
    keys = _platform_keys(ws)

    # ---- PF-001 主控平台已识别（netlist_graph.meta.platform 非空且在 rules/index.json 中）----
    if meta_platform and meta_platform in keys:
        _check(checks, "PF-001", GateStatus.PASS, "主控平台已识别",
               f"{meta_platform}(来源=netlist_graph.meta.platform)")
    else:
        _check(checks, "PF-001", GateStatus.WARNING, "主控平台已识别",
               meta_platform or "NO_PLATFORM_MATCH")

    # ---- PF-003 官方引脚核对产物存在且无 FAIL ----
    if pc is None:
        _check(checks, "PF-003", GateStatus.WARNING,
               "官方引脚核对产物存在且无 FAIL", "无官方引脚核对产物")
    else:
        findings = pc.get("findings") or []
        fails = [f for f in findings if str(f.get("severity", "")).upper() == "FAIL"]
        loc = f"{pc_path.parent.name}/platform_check.json"
        if fails:
            f0 = fails[0] if isinstance(fails[0], dict) else {}
            _check(checks, "PF-003", GateStatus.FAIL,
                   "官方引脚核对产物存在且无 FAIL",
                   f"{loc} FAIL={len(fails)} 示例={f0.get('check','?')}@{f0.get('object','?')}")
        else:
            _check(checks, "PF-003", GateStatus.PASS,
                   "官方引脚核对产物存在且无 FAIL",
                   f"{loc} findings={len(findings)} FAIL=0")

    # ---- PF-004 覆盖率门限 +（缺口>0 额外 WARNING，说明官方表有缺口而非设计错误）----
    thr = _platform_coverage_min()
    if pc is None:
        _check(checks, "PF-004", GateStatus.WARNING,
               f"官方引脚覆盖率 ≥ {thr:g}", "无覆盖数据")
        return
    cov = pc.get("coverage") or {}
    st = pc.get("stats") or {}
    rate = cov.get("fill_rate")
    checked = cov.get("items_checked", st.get("pins_total", 0))
    expected = cov.get("items_expected", 0)
    missing = int(st.get("missing_in_pinout", 0) or 0)
    dom = int(st.get("domain_mismatch", 0) or 0)
    tgt = f"{pc.get('platform','') or '-'}/{pc.get('device','') or cov.get('target','') or '-'}"
    if isinstance(rate, (int, float)):
        detail = f"{tgt} 覆盖 {checked}/{expected}={float(rate):.3f} 缺口={missing} 域不一致={dom}"
        status = GateStatus.PASS if float(rate) >= thr else GateStatus.FAIL
    else:
        detail = f"{tgt} 无 fill_rate 缺口={missing} 域不一致={dom}"
        status = GateStatus.WARNING
    _check(checks, "PF-004", status, f"官方引脚覆盖率 ≥ {thr:g}", detail)
    if missing > 0:
        _check(checks, "PF-005", GateStatus.WARNING,
               "官方引脚表缺口已记录(非设计错误)",
               f"{tgt} 官方表缺 {missing} 脚（WARNING，非设计错误）")


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
def _expected_ic_refdes(e_dir: Path) -> list[str]:
    """从 PH-2 的 netlist_graph 取应分析 IC 的**产物键**集合（kind==IC 且 source.populated，PF-010）。

    键与 PH-3 产物文件名一致：有板号 → ``<board>_<refdes>``，否则 ``<refdes>``（跨板 refdes 可重复，
    必须按板唯一化，否则 summary 互相覆盖）。仅列表用于 "缺失位号"；路径：<ws>/PH-2_网表解析。
    """
    g = e_dir.parent / "PH-2_网表解析" / "netlist_graph.json"
    if not g.exists():
        return []
    try:
        d = json.loads(g.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for dv in d.get("devices", []):
        if dv.get("kind") == "IC" and (dv.get("source") or {}).get("populated"):
            b = str(dv.get("board") or "").strip()
            r = str(dv.get("refdes") or dv.get("id") or "").strip()
            r = r.replace("::", "_").replace("/", "_")
            key = f"{b}_{r}" if b else r
            if key:
                out.append(key)
    return sorted(set(out))


def validate_evidence(e_dir: Path, expected_ic_count: int | None = None) -> GateResult:
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
    # ---- G3X-001 覆盖率门禁（PF-010）：summary 数 ≥ 应分析 IC 数 ----
    produced = {s.name[:-len("_summary.json")] for s in sues if s.name.endswith("_summary.json")}
    if expected_ic_count is None:
        _check(checks, "G3X-001", GateStatus.WARNING, "summary 数 ≥ 应分析 IC 数",
               f"实际 summary={len(sues)}；未提供 expected_ic_count（未知应分析数）")
    else:
        expected_refs = _expected_ic_refdes(e_dir)
        missing = [r for r in expected_refs if r not in produced]
        if len(sues) >= expected_ic_count:
            _check(checks, "G3X-001", GateStatus.PASS,
                   f"summary 数 ≥ 应分析 IC 数({expected_ic_count})",
                   f"summary={len(sues)}/{expected_ic_count}")
        else:
            miss_txt = (" 缺失位号=" + ",".join(missing[:20])) if missing else ""
            _check(checks, "G3X-001", GateStatus.FAIL,
                   f"summary 数 ≥ 应分析 IC 数({expected_ic_count})",
                   f"summary={len(sues)} < 期望={expected_ic_count}{miss_txt}")
    _append_platform_checks(checks, e_dir)   # P4-C: PF-001/003/004（+PF-005 官方表缺口）
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
        # NG-006：单一真源——links 不得内嵌邻接表（邻接由 pins+joins 派生）
        emb = v.get("embedded_adjacency")
        if emb is None:                       # 兼容：未写入 meta 时直接从 devices 判定
            emb = sum(1 for dv in d.get("devices", []) for lk in dv.get("links", [])
                      if lk.get("upstream") or lk.get("downstream") or "via" in lk)
        _check(checks, "NG-006", GateStatus.PASS if emb == 0 else GateStatus.FAIL,
               "单一真源：links 不内嵌邻接（无 upstream/downstream/via）", f"embedded={emb}")
        # NG-010：同网络内 side 必须一致（残余混合 side = 0；raw 冲突已归并）
        sc = v.get("side_conflicts", {})
        sc_count = sc.get("count") if isinstance(sc, dict) else sc
        sc_count = 0 if sc_count is None else sc_count
        sc_norm = sc.get("normalized") if isinstance(sc, dict) else None
        _check(checks, "NG-010", GateStatus.PASS if sc_count == 0 else GateStatus.FAIL,
               "同网络内 side 一致（无混合 side）",
               f"side_conflicts={sc_count} 归并={sc_norm}")
        # NG-011：最大跨器件层数 trace_max_hops 内（DEPTH_EXCEEDED = 0）
        paths = d.get("paths", [])
        depth_exceeded = sum(1 for p in paths if p.get("depth_exceeded"))
        minv = meta.get("trace_limits", {})
        depth_exceeded = max(depth_exceeded, int(minv.get("depth_exceeded", 0) or 0))
        obs_hops = max((len(p.get("path", [])) - 1 for p in paths), default=0)
        _check(checks, "NG-011", GateStatus.PASS if depth_exceeded == 0 else GateStatus.FAIL,
               "追踪深度 ≤ trace_max_hops（depth_exceeded=0）",
               f"depth_exceeded={depth_exceeded} 实测最大层数={obs_hops}")
        # NG-012：差分对成员视为同一逻辑信号（差分引发的 OSCILLATION = 0）
        osc = sum(1 for p in paths if p.get("oscillation") or p.get("reason") == "OSCILLATION")
        _check(checks, "NG-012", GateStatus.PASS if osc == 0 else GateStatus.FAIL,
               "差分对不原地打转（OSCILLATION=0）", f"oscillation={osc}")
        # NG-007：规模守门——防 O(k²) 重复内嵌（体积不随网格平方膨胀）
        mb = p.stat().st_size / 1048576
        _check(checks, "NG-007", GateStatus.PASS if mb <= 5 else GateStatus.FAIL,
               "netlist_graph.json ≤5MB（防 O(k²) 重复内嵌）", f"{mb:.3f}MB")
        # NG-015：PH-2 必须产出芯片功能（kind=IC 且已贴装 → function.description/role 非空）
        ics = [dv for dv in d.get("devices", [])
               if dv.get("kind") == "IC" and (dv.get("source") or {}).get("populated")]
        miss_fn = [dv.get("id") or dv.get("refdes") for dv in ics
                   if not str((dv.get("function") or {}).get("description") or "").strip()
                   or not str((dv.get("function") or {}).get("role") or "").strip()]
        _check(checks, "NG-015", GateStatus.PASS if not miss_fn else GateStatus.FAIL,
               "所有 kind=IC 且 populated 的器件 function.description/role 非空",
               f"IC={len(ics)} 缺功能={len(miss_fn)}" + (f" 样例={miss_fn[:5]}" if miss_fn else ""))
        # NG-016：芯片功能来源分布（unknown=0 → PASS；否则 WARNING）
        cf = meta.get("chip_function")
        if not isinstance(cf, dict):
            _check(checks, "NG-016", GateStatus.WARNING,
                   "芯片功能来源分布已记录(edn_symbol/llm/unknown)且 unknown=0", "meta.chip_function 缺失")
        else:
            by_src = cf.get("by_source") or {}
            unknown = int(by_src.get("unknown", 0) or 0)
            _check(checks, "NG-016", GateStatus.PASS if unknown == 0 else GateStatus.WARNING,
                   "芯片功能来源分布已记录(edn_symbol/llm/unknown)且 unknown=0",
                   f"by_source={by_src}")
        # NG-017：PH-2 输出规范（netlist_graph schema）必需键齐全 + links 无内嵌邻接 + schema_version=3.1
        miss17 = []
        for k in ("schema_version", "kind", "product", "status", "meta", "devices", "nets",
                  "paths", "cross_board_links", "connector_pairs", "diff_pairs"):
            if k not in d:
                miss17.append(f"top.{k}")
        for k in ("boards", "devices", "nets", "paths", "platform", "platform_device",
                  "platform_detect", "cross_board_links", "connector_pairs", "sub_agent_groups",
                  "trace_limits", "end_types", "validation", "chip_function"):
            if k not in meta:
                miss17.append(f"meta.{k}")
        for dv in d.get("devices", []):
            did = dv.get("id") or dv.get("refdes") or "?"
            req = ["id", "board", "refdes", "model", "kind", "source", "ic", "pins",
                   "links", "depop"]
            if dv.get("kind") == "IC" and (dv.get("source") or {}).get("populated"):
                req.append("function")
            for k in req:
                if k not in dv:
                    miss17.append(f"device[{did}].{k}")
            for k in ("in_bom", "in_edn", "populated", "edn_symbol"):
                if k not in (dv.get("source") or {}):
                    miss17.append(f"device[{did}].source.{k}")
            icv = dv.get("ic")
            if not isinstance(icv, dict):
                miss17.append(f"device[{did}].ic")
            elif icv:                       # 非空才要求子键（非 IC 无手册信息，ic={}）
                for k in ("manual_path", "ic_type", "manual_status", "channels"):
                    if k not in icv:
                        miss17.append(f"device[{did}].ic.{k}")
            if "function" in dv:
                for k in ("category", "role", "description", "source", "confidence",
                          "evidence", "nets", "power_domains"):
                    if k not in (dv.get("function") or {}):
                        miss17.append(f"device[{did}].function.{k}")
        for nt in d.get("nets", []):
            for k in ("board", "net", "joins", "kind", "alias_group"):
                if k not in nt:
                    miss17.append(f"net[{nt.get('net', '?')}].{k}")
        for pt in d.get("paths", []):
            for k in ("id", "board", "connector", "pin", "start_net", "path", "endpoint_pins",
                      "end_type", "bidirectional", "status", "hops", "reason",
                      "depth_exceeded", "oscillation"):
                if k not in pt:
                    miss17.append(f"path[{pt.get('id', '?')}].{k}")
        emb17 = sum(1 for dv in d.get("devices", []) for lk in dv.get("links", [])
                    if lk.get("upstream") or lk.get("downstream") or "via" in lk)
        if emb17:
            miss17.append(f"links.embedded_adjacency={emb17}")
        sv = str(d.get("schema_version", ""))
        if sv != "3.1":
            miss17.append(f"schema_version={sv}(期望3.1)")
        _check(checks, "NG-017", GateStatus.PASS if not miss17 else GateStatus.FAIL,
               "netlist_graph schema 合规(顶层+meta+devices+nets+paths 必需键齐全/links 无内嵌邻接/schema_version=3.1)",
               (f"缺失或违规={len(miss17)} 样例={miss17[:8]}" if miss17
                else "全部必需键齐全 links 无内嵌邻接 schema_version=3.1"))
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
