"""Flow 编排器 — 阶段4（v2：新阶段序 PH-0..7 + Gate 断点/批次暂停 + 人机 checkpoint + 中间文件清理）.

硬件_review=确定性 Flow（裁判）。v2 阶段序（已确认）：
  PH-0 输入准备 → PH-1 手册检索(由BOM, G1) → PH-2 数据预检Wave0(G2) →
  PH-3 网表解析/ netlist_graph + 子agent分发(G3) → PH-4 深度分析(只读netlist_graph+复核+回环,G4) →
  PH-4 报告合成(G4) → PH-5 审计复核(G5) → PH-6 闭环交付(G6)
中间文件（.run/temp 下带时间戳）即用即清，收尾 cleanup。
"""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from hardware_analysis.config import Config
from hardware_analysis.workspace.manager import RunWorkspace
from hardware_analysis.flows.rule_loader import load_stage_bundle

# v2：批次暂停点 = 手册缺失确认(PH-1) / 分析批次(PH-4) / 审计(PH-6)
BATCH_BOUNDARY = {"PH-1": "G1", "PH-3": "G3", "PH-5": "G5"}
TEMP_PATTERNS = ("*.components.json", "*.nets.json")   # edn_parse 中间产物（带时间戳）


class Orchestrator:
    def __init__(self, product: str, cfg: Config | None = None,
                 projects_dir: str = "storge/project", input_dir: str = "project"):
        self.product = product
        self.cfg = cfg or Config()
        self.projects_dir = Path(projects_dir)
        self.input_dir = Path(input_dir) / product
        self.ws = RunWorkspace(self.projects_dir, product)
        self.state = {"product": product, "current": "IDLE",
                      "phases": {f"PH-{i}": "PENDING" for i in range(8)},
                      "gates": {f"G{i}": "PENDING" for i in range(1, 7)},
                      "errors": [], "paused": False, "pause_reason": ""}
        self.auto_pass = False

    # ---------- 日志 ----------
    def _log(self, type_, **kw):
        self.ws.log({"type": type_, "phase": self.state["current"], **kw})

    def _set(self, key, val):
        self.state[key] = val
        self.ws.write_state(self.state)

    def _set_gate(self, gate, status):
        self.state["gates"][gate] = status
        self.ws.write_state(self.state)

    def _p0(self, *p) -> Path: return self.ws.dir / "PH-0_输入准备" / Path(*p)
    def _p1(self, *p) -> Path: return self.ws.dir / "PH-1_手册检索" / Path(*p)
    def _p2(self, *p) -> Path: return self.ws.dir / "PH-2_网表解析" / Path(*p)
    def _p3(self, *p) -> Path: return self.ws.dir / "PH-3_深度分析" / Path(*p)
    def _p4(self, *p) -> Path: return self.ws.dir / "PH-4_报告合成" / Path(*p)
    def _p5(self, *p) -> Path: return self.ws.dir / "PH-5_审计复核" / Path(*p)
    def _p6(self, *p) -> Path: return self.ws.dir / "PH-6_闭环交付" / Path(*p)

    # ---------- PH-0 输入准备 ----------
    def _act_ph0(self):
        step = self._p0("step_0a.json")
        if step.exists():
            return
        status = "PASS" if self.auto_pass else "BLOCKED"
        step.write_text(json.dumps({
            "schema_version": "1.0", "kind": "step_0a", "status": status,
            "product": self.product, "manual_dir": "storge/refbook",
            "extra_checks": [], "raw_user_response": "auto" if self.auto_pass else ""},
            ensure_ascii=False, indent=1), encoding="utf-8")
        if not self.auto_pass:
            self._pause("等待人工确认 step_0a（manual_dir/extra_checks）")

    # ---------- PH-1 手册检索 + BOM 预检 ----------
    def _act_ph1(self):
        boms = (sorted(self.input_dir.glob("*.xlsx")) + sorted(self.input_dir.glob("*.XLSX"))
                + sorted(self.input_dir.glob("*.docx")) + sorted(self.input_dir.glob("*.DOCX"))
                + sorted(self.input_dir.glob("*.xls")) + sorted(self.input_dir.glob("*.doc")))
        if not boms:
            raise RuntimeError(f"project/{self.product} 下无 BOM 输入（xlsx/docx）")
        self._r(f"bom_parse {' '.join(map(str, boms))} --out {self._p1('bom_entries.json')}")
        self._r(f"manual_index {self._p1('bom_entries.json')} --out {self._p1('manual_index.json')} "
                f"--refbook storge/refbook --product {self.product}")
        # BOM 预检（原 PH-2 并入 PH-1）：产出 precheck.json，由 G1 一并校验
        boms_j = json.loads(self._p1("bom_entries.json").read_text(encoding="utf-8"))
        entries = boms_j.get("entries", {})
        pre = {"kind": "precheck", "stage": "PH-1", "status": "PASS",
               "bom_refdes": len(entries),
               "boards": sorted({v.get("board", "?") for v in entries.values()}),
               "bom_errors": boms_j.get("errors", [])}
        (self._p1("precheck.json")).write_text(json.dumps(pre, ensure_ascii=False, indent=1), encoding="utf-8")
        self._log("ph1_done", boms=[b.name for b in boms], bom_refdes=pre["bom_refdes"])
        self._ic_type_llm()      # LLM 判定 ic_type 并回写 manual_index.json（mock 走 SINK）

    def _ic_type_llm(self):
        """对 manual_index 中每颗唯一 IC 判定 ic_type（SINK/PASS_THRU/POWER_SRC）。
        走可复用 LLMChecker（含持久化缓存）；契约 = IcTypeVerdict。"""
        from hardware_analysis.common.llm_check import LLMChecker
        from hardware_analysis.models.contracts import IcTypeVerdict
        p = self._p1("manual_index.json")
        if not p.exists():
            return
        mi = json.loads(p.read_text(encoding="utf-8"))
        checker = LLMChecker(self.ws.dir / ".run" / "llm_cache.json")
        seen = {}
        for key, e in mi.get("entries", {}).items():
            model = e.get("model") or ""
            if not model or model in seen:
                continue
            obj, meta = checker.run(
                "hw_search",
                f"判定 IC 型号 {model} 的类型：SINK(信号落点)/PASS_THRU(电平转换/收发器,给通道)/POWER_SRC(电源源)。",
                IcTypeVerdict,
                payload={"model": model, "manual": e.get("manual_path"), "status": e.get("status")})
            t = obj.ic_type if (obj and obj.ic_type in ("SINK", "PASS_THRU", "POWER_SRC")) else "SINK"
            seen[model] = t
            self._log("ic_type", model=model, ic_type=t, cached=meta.get("cached"))
        for key, e in mi.get("entries", {}).items():
            if e.get("ic_type", "UNKNOWN") == "UNKNOWN":
                e["ic_type"] = seen.get(e.get("model"), "SINK")
        p.write_text(json.dumps(mi, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---------- PH-2 网表解析（netlist_graph + 子 agent 分发） ----------
    def _act_ph2(self):
        edns = sorted(self.input_dir.glob("*.EDN")) + sorted(self.input_dir.glob("*.edn"))
        if not edns:
            raise RuntimeError(f"project/{self.product} 下无 EDN 输入")
        temp = self.ws.temp
        temp.mkdir(parents=True, exist_ok=True)
        for e in edns:
            self._r(f"edn_parse {e} --out {temp}")
            self._log("edn_parsed", file=e.name)
        self._r(f"edn_global_merge {temp} {self._p2()}")
        self.cleanup_temp()                       # 即用即清：合并后删中间文件
        self._r(f"refdes_map {self._p2()} --bom {self._p1('bom_entries.json')}")
        self._r(f"tracer {self._p2()}")
        self._r(f"netlist_graph {self._p2()} --groups 0 --product {self.product} "
                f"--manual-index {self._p1('manual_index.json')}")
        self._log("ph2_done", edns=[e.name for e in edns])

    # ---------- PH-3 深度分析（只读 netlist_graph.json + 复核 + 回环） ----------
    def _act_ph3(self):
        from hardware_analysis.agents.direct import llm_json
        from hardware_analysis.models.contracts import SummaryDoc, EvidenceDoc, Finding
        g = self._p2("netlist_graph.json")
        if not g.exists():
            raise RuntimeError("PH-3 需要 netlist_graph.json（PH-2 未产出）")
        doc = json.loads(g.read_text(encoding="utf-8"))
        ics = [d for d in doc["devices"] if d["kind"] == "IC" and d["source"].get("populated")]
        e = self._p3(); e.mkdir(parents=True, exist_ok=True)
        notes = self._p3("clarify_requests.jsonl")
        for d in ics:
            # slice：本 IC + 相关 nets/paths + 手册前置
            slice_ = {"task": "analyze_ic", "device": d,
                      "paths": [p for p in doc["paths"] if any(d["refdes"] in ep for ep in p["endpoint_pins"])][:20],
                      "manual": d.get("ic", {}).get("manual_path")}
            obj, errs, sec = llm_json("hw_analyze",
                f"分析 IC {d['id']}({d['model']})：引脚/VCCIO/供电/外围；并**复核** tracer 判定 "
                f"ic_type={d['ic'].get('ic_type')} 是否正确；输出 summary(§4.3)。输入切片:"
                + json.dumps(slice_, ensure_ascii=False)[:2000], SummaryDoc)
            if obj:
                (e / f"{d['refdes']}_summary.json").write_text(
                    json.dumps(obj.model_dump(), ensure_ascii=False, indent=1), encoding="utf-8")
                # evidence 契约（§4.2）：findings + coverage
                n_pin = len(d.get("pins", {}))
                ev = EvidenceDoc(
                    kind="evidence", evidence_type="ic_analysis",
                    producer={"agent": "hw_analyze", "task_id": d["id"]},
                    coverage={"target": d["id"], "items_expected": n_pin,
                              "items_checked": min(len(obj.findings), n_pin),
                              "fill_rate": round(min(len(obj.findings), n_pin) / max(n_pin, 1), 3)},
                    findings=[Finding(severity=f.severity, object=d["id"], result=f.detail,
                                      source_refs=[f"netlist_graph::{d['id']}"])
                              for f in obj.findings])
                (e / f"{d['refdes']}_evidence.json").write_text(
                    ev.model_dump_json(exclude_none=True, indent=1), encoding="utf-8")
            self._log("icon_ok" if obj else "icon_err", refdes=d["refdes"], kind="analyze", sec=sec,
                      err=("" if obj else "；".join(errs)[:100]))
        # 回环：对 STUB/OPEN_END/ic_type 未定 → request → PH-3 定向重读源 EDN 复核（≤3 轮）
        try:
            from hardware_analysis.tools import clarify
            req = e / "clarify_requests.jsonl"
            clarify.emit_requests(self._p2(), req)
            res = clarify.resolve(self.product, self._p2(), req, e / "clarify_resolutions.jsonl")
            self._log("clarify_done", requests=len(res))
        except Exception as ex:
            self._log("clarify_err", err=str(ex)[:120])

    # ---------- PH-4 报告合成 ----------
    def _act_ph4(self):
        from hardware_analysis.agents.direct import llm_json
        from hardware_analysis.models.contracts import ReportDoc
        e = self._p3()
        sums = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in e.glob("*_summary.json")}
        obj, errs, sec = llm_json("hw_write",
            "汇总 summary 为 report：findings[](check,severity,detail)/tables[](title,columns,rows完整不截断)"
            "/narrative{}" + ("；输入: " + json.dumps(sums, ensure_ascii=False)[:2200] if sums else "(无输入)"),
            ReportDoc)
        f = self._p4(); f.mkdir(parents=True, exist_ok=True)
        (f / "report.json").write_text(json.dumps(
            obj.model_dump(exclude_none=True) if obj else {"_err": "；".join(errs)[:200]},
            ensure_ascii=False, indent=1), encoding="utf-8")
        self._log("write_done", sec=sec, ok=obj is not None)

    # ---------- PH-5 审计 ----------
    def _act_ph5(self):
        from hardware_analysis.agents.direct import llm_json
        from hardware_analysis.models.contracts import GateResult
        obj, errs, sec = llm_json("hw_auditor",
            "对 evidence/report 执行 SA-1..8 自审+证据链核对，只审不改。输出 GateResult(gate=G5,status,checks[])",
            GateResult)
        f = self._p5(); f.mkdir(parents=True, exist_ok=True)
        (f / "audit.json").write_text(json.dumps(
            obj.model_dump(exclude_none=True) if obj else {"_err": "；".join(errs)[:200]},
            ensure_ascii=False, indent=1), encoding="utf-8")
        self._log("audit_done", sec=sec, ok=obj is not None)

    # ---------- PH-6 闭环交付 ----------
    def _act_ph6(self):
        rp = self._p4("report.json")
        (self._p6()).mkdir(parents=True, exist_ok=True)
        final = self._p6("final_report.json")
        if rp.exists():
            import shutil
            shutil.copy(rp, final)                   # 定版产物（G6 校验依据）
        sp = self._p6("delivery.json")
        sp.write_text(json.dumps({
            "kind": "delivery", "product": self.product, "status": "DELIVERED",
            "final_report": str(final), "unresolved": []}, ensure_ascii=False, indent=1), encoding="utf-8")
        self._log("ph6_done")

    # ---------- 基础设施 ----------
    def _r(self, cmd: str):
        env = {"PYTHONPATH": "src", "PATH": "/usr/bin:/bin:/usr/local/bin"}
        p = subprocess.run(f"{sys.executable} -m hardware_analysis.tools.{cmd}",
                           shell=True, capture_output=True, text=True, env=env, cwd=str(Path.cwd()))
        if p.returncode != 0:
            self._log("tool_failed", cmd=cmd, stderr=p.stderr[-300:])
            raise RuntimeError(f"tool {cmd} exit={p.returncode}: {p.stderr[-200:]}")
        self._log("tool_ok", cmd=cmd)

    def cleanup_temp(self) -> int:
        return self.ws.clean_temp(TEMP_PATTERNS, keep_dir=True)

    def _pause(self, reason: str):
        self._set("paused", True); self._set("pause_reason", reason)
        self._log("human_block", reason=reason)

    def _gate(self, gate: str, fn):
        r = fn()
        (self.ws.dir / "gates" / f"{gate}.json").write_text(r.model_dump_json(indent=1), encoding="utf-8")
        self._set_gate(gate, r.status.value)
        self._log(f"gate_{'passed' if r.status.value == 'PASS' else 'failed'}", gate=gate, summary=r.summary)
        if r.status.value != "PASS":
            self._set("errors", self.state["errors"] + [f"{gate} FAIL"])
            return False
        return True

    # ---------- 主流程 ----------
    def run(self, auto_pass_gates=False):
        self.auto_pass = auto_pass_gates
        from hardware_analysis.tools import gate_validators as gv
        from hardware_analysis.flows.rule_loader import load_dev_rules
        dev = load_dev_rules()                       # 启动读取：代码生成硬性要求
        try:
            self.ws.create()
            self._log("dev_rules_loaded", count=len(dev),
                      rules=[d["id"] for d in dev])
            self._set("current", "PH-0"); self.state["phases"]["PH-0"] = "RUNNING"
            self._act_ph0()
            self.state["phases"]["PH-0"] = "DONE"
            for ph, act, gate, gatefn in [
                ("PH-1", self._act_ph1, "G1", lambda: gv.validate_manual_bom(self._p1())),
                ("PH-2", self._act_ph2, "G2", lambda: gv.validate_netlist(self._p2())),
                ("PH-3", self._act_ph3, "G3", lambda: gv.validate_evidence(self._p3())),
                ("PH-4", self._act_ph4, "G4", lambda: gv.validate_report(self._p4())),
                ("PH-5", self._act_ph5, "G5", lambda: gv.validate_audit(self.ws.dir)),
                ("PH-6", self._act_ph6, "G6", lambda: gv.validate_delivery(self.ws.dir)),
            ]:
                self._set("current", ph); self.state["phases"][ph] = "RUNNING"
                act()
                self.state["phases"][ph] = "DONE"
                if gate:
                    if not self._gate(gate, gatefn):
                        self._set("current", f"{ph}:{gate} FAIL")
                        return self.state
                    if ph in BATCH_BOUNDARY and not auto_pass_gates:
                        if not self._resume_or_pause(None):
                            return self.state
            self._set("current", "DONE")
        except Exception as e:
            self._set("current", f"ERROR:{type(e).__name__}")
            self.state["errors"].append(str(e))
            self._log("error", msg=str(e))
        finally:
            self.cleanup_temp()                   # 最终也清理中间文件
            self._set("errors", self.state["errors"])
        return self.state

    def _resume_or_pause(self, nxt):
        if self.auto_pass:
            self._log("batch_auto_continue", at=self.state["current"])
            return True
        self._set("paused", True); self._set("pause_reason", "批次边界，等待人工确认继续")
        self._log("batch_pause", at=self.state["current"])
        return False


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("product")
    ap.add_argument("--auto-pass", action="store_true")
    a = ap.parse_args()
    s = Orchestrator(a.product).run(auto_pass_gates=a.auto_pass)
    print(json.dumps(s, ensure_ascii=False, indent=1))
