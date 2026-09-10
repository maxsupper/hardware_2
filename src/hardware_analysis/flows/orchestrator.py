"""Flow 编排器 — 阶段4（PH-0..7 状态机 + Gate 断点/批次暂停 + checkpoint 人机 + run.log/state）.

硬件_review=确定性 Flow（裁判）：
  阶段推进 → 跑阶段(s)→ Gate 校验 → PASS 放行 / FAIL 阻断(带原因) / 批次边界暂停等人工。
分层通过 Act 扩展点接入现场:
  act_ph1_prep(树)等为确定性现成实现；act_ph2_search/act_ph4_analyze/act_ph5_write/
  act_ph6_audit 默认 stub(阶段5 注入 agent)，未注入则以 .run 状态记录"待注入"。
"""
from __future__ import annotations
import json, subprocess, sys, traceback
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from hardware_analysis.config import Config
from hardware_analysis.workspace.manager import RunWorkspace
from hardware_analysis.flows.rule_loader import load_stage_bundle

BATCH_BOUNDARY = {"PH-2": "G2", "PH-4": "G4", "PH-6": "G6"}


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
                      "gates": {f"G{i}": "PENDING" for i in range(1, 8)},
                      "errors": [], "paused": False, "pause_reason": ""}

    # ---------- 日志 ----------
    def _log(self, type_, **kw):
        self.ws.log({"type": type_, "phase": self.state["current"], **kw})

    def _set(self, key, val):
        self.state[key] = val
        self.ws.write_state(self.state)

    def _set_gate(self, gate, status):
        self.state["gates"][gate] = status
        self.ws.write_state(self.state)

    # ---------- 确定性阶段(现成实现) ----------
    def _act_ph0(self):
        w = self.ws.dir
        step = w / "step_0a.json"
        if not step.exists():                       # 无手工配置 → 落默认确认文件
            if self.auto_pass:
                step.write_text(json.dumps({
                    "schema_version": "1.0", "kind": "step_0a", "status": "PASS",
                    "product": self.product, "manual_dir": "storge/refbook",
                    "extra_checks": [], "raw_user_response": "auto"},
                    ensure_ascii=False, indent=1), encoding="utf-8")
            else:
                step.write_text(json.dumps({
                    "schema_version": "1.0", "kind": "step_0a", "status": "BLOCKED",
                    "product": self.product, "manual_dir": "storge/refbook",
                    "extra_checks": [], "raw_user_response": ""}, ensure_ascii=False, indent=1), encoding="utf-8")
                self._pause(f"等待人工确认 step_0a（manual_dir/extra_checks）")

    def _act_ph1(self):
        """PH-1 网表解析: 逐 EDN → 全局合并 → 信号链 → BOM → 位号映射。"""
        edns = sorted(self.input_dir.glob("*.EDN")) + sorted(self.input_dir.glob("*.edn"))
        if not edns:
            raise RuntimeError(f"project/{self.product} 下无 EDN 输入")
        temp = self.ws.dir / ".run" / "temp"
        temp.mkdir(parents=True, exist_ok=True)
        for e in edns:
            self._r(f"edn_parse {e} --out {temp}")
            self._log("edn_parsed", file=e.name)
        self._r(f"edn_global_merge {temp} {self.ws.dir / 'B_prep'}")
        boms = sorted(self.input_dir.glob("*.xlsx")) + sorted(self.input_dir.glob("*.XLSX"))
        if boms:
            self._r(f"bom_parse {' '.join(map(str, boms))} --out {self.ws.dir / 'B_prep' / 'bom_entries.json'}")
        self._r(f"refdes_map {self.ws.dir / 'B_prep'}")
        self._r(f"tracer {self.ws.dir / 'B_prep'}")
        self._log("ph1_done", edns=[e.name for e in edns])

    def _act_ph3(self):
        """PH-3 数据预检(确定性)。"""
        self._r(f"gate_validators G3 {self.ws.dir}")
        self._log("ph3_done")

    # ---------- 阶段5 注入点(默认 stub) ----------
    def _act_ph2(self):  self._log("ph2_stub", note="hw_search agent 待阶段5注入")
    def _act_ph4(self):  self._log("ph4_stub", note="hw_analyze agent 待阶段5注入")
    def _act_ph5(self):  self._log("ph5_stub", note="hw_write agent 待阶段5注入")
    def _act_ph6(self):  self._log("ph6_stub", note="hw_auditor agent 待阶段5注入")
    def _act_ph7(self):  self._log("ph7_done")

    # ---------- 基础设施 ----------
    def _r(self, cmd: str):
        env = {"PYTHONPATH": "src", "PATH": "/usr/bin:/bin:/usr/local/bin"}
        p = subprocess.run(f"{sys.executable} -m hardware_analysis.tools.{cmd}",
                           shell=True, capture_output=True, text=True, env=env, cwd=str(Path.cwd()))
        if p.returncode != 0:
            self._log("tool_failed", cmd=cmd, stderr=p.stderr[-300:])
            raise RuntimeError(f"tool {cmd} exit={p.returncode}: {p.stderr[-200:]}")
        self._log("tool_ok", cmd=cmd)

    def _pause(self, reason: str):
        self._set("paused", True); self._set("pause_reason", reason)
        self._log("human_block", reason=reason)

    def _gate(self, gate: str, fn):
        r = fn()
        (self.ws.dir / "gates" / f"{gate}.json").write_text(
            r.model_dump_json(indent=1), encoding="utf-8")
        self._set_gate(gate, r.status.value)
        self._log(f"gate_{'passed' if r.status.value == 'PASS' else 'failed'}", gate=gate,
                  summary=r.summary)
        if r.status.value != "PASS":
            self._set("errors", self.state["errors"] + [f"{gate} FAIL"])
            return False
        return True

    # ---------- 主流程 ----------
    def run(self, auto_pass_gates=False):
        self.auto_pass = auto_pass_gates
        try:
            self.ws.create()
            self._set("current", "PH-0"); self.state["phases"]["PH-0"] = "RUNNING"
            self._act_ph0()
            if not self._resume_or_pause("PH-1"):
                return self.state
            self.state["phases"]["PH-0"] = "DONE"
            for ph, act, gate, gatefn in [
                ("PH-1", self._act_ph1, "G1", lambda: __import__(
                    "hardware_analysis.tools.gate_validators", fromlist=["x"]).validate_prep(self.ws.dir / "B_prep")),
                ("PH-2", self._act_ph2, None, None),
                ("PH-3", self._act_ph3, None, None),
                ("PH-4", self._act_ph4, None, None),
                ("PH-5", self._act_ph5, None, None),
                ("PH-6", self._act_ph6, None, None),
                ("PH-7", self._act_ph7, None, None),
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
            self._set("errors", self.state["errors"])
        return self.state

    def _resume_or_pause(self, nxt):
        if getattr(self, "auto_pass", False):
            self._log("batch_auto_continue", at=self.state["current"])
            return True
        self._set("paused", True); self._set("pause_reason", f"批次边界，等待人工确认继续")
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
