"""CLI — 硬件审查工具入口。

用法:
  python -m hardware_analysis.cli run --product <名称> [--auto-pass]
  python -m hardware_analysis.cli prep|validate|search|analyze|write|audit|finalize --product <名称>
  python -m hardware_analysis.cli web            (启动 web 调试面板)
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hardware_analysis.flows.orchestrator import Orchestrator
from hardware_analysis.tools import gate_validators as gv


def add_product(sub):
    sub.add_argument("--product", required=True)
    sub.add_argument("--ws", default="storge/project")
    return sub


def main() -> None:
    ap = argparse.ArgumentParser("硬件原理图自动审查 + 故障分析")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run"); add_product(r); r.add_argument("--auto-pass", action="store_true")
    for name, fn in [("prep", "PH-1"), ("validate", "G3"), ("search", "PH-2"),
                     ("analyze", "PH-4"), ("write", "PH-5"), ("audit", "PH-6"), ("finalize", "PH-7")]:
        s = sub.add_parser(name)
        add_product(s)

    args = ap.parse_args()
    if args.cmd == "run":
        st = Orchestrator(args.product, projects_dir=args.ws).run(auto_pass_gates=args.auto_pass)
        print(json.dumps({"current": st["current"], "errors": st["errors"],
                          "gates": st["gates"]}, ensure_ascii=False, indent=1))
    elif args.cmd in ("prep", "validate"):
        ws = Path(args.ws) / args.product
        if args.cmd == "prep":
            Orchestrator(args.product, projects_dir=args.ws)._act_ph1()
        print("gate G1:", gv.main_gate_cli(ws, "G1"))
    else:
        print(f"{args.cmd}: agent 阶段（阶段5 已接线，见 agents/crew.py）")


if __name__ == "__main__":
    main()
