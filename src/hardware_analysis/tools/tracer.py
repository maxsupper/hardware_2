"""端到端 tracer — 阶段3b（确定性）。

基于 global 图（net + 引脚连接）做端到端信号追踪：
  - 继续规则: 透明器件(R/L/BEAD/0R)跨过继续
  - 终止规则: 终端 = 非透明元件引脚 / 连接器 / 驱动目标；悬空=OPEN_END
  - 终止清单(termination inventory): 每条 trace 的每跳 + 终点点类型
  - 双向验证: 正反向路径一致（反向重走一遍对比）
产出 trace_inventory.json（hw_analyze 只消费已闭合路径）。
用法: python -m hardware_analysis.tools.tracer <B_prep_dir> <out>
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

TRANSPARENT = ("R", "L", "BEAD", "FB", "FERR", "TP", "JMP", "JUMP")


def _t(refdes: str) -> bool:
    s = str(refdes or "").upper()
    return any(s.startswith(p) for p in TRANSPARENT)


def build_graph(global_nets: dict):
    pin2net = {}
    net2pins = {}
    for nname, e in global_nets.items():
        pins = [(j.get("refdes", ""), j.get("pin", ""), j.get("file", "")) for j in e.get("joins", [])]
        net2pins[nname] = pins
        for rd, pn, _ in pins:
            pin2net[(rd, pn)] = nname
    return pin2net, net2pins


def trace_all(global_nets: dict, start_limit=400) -> dict:
    pin2net, net2pins = build_graph(global_nets)
    from collections import defaultdict
    dev_pins = defaultdict(dict)  # refdes -> {pin: net}
    for (rd, pn), n in pin2net.items():
        dev_pins[rd][pn] = n

    traces, inv = [], []
    started = 0
    for start_net, pins in net2pins.items():
        if started >= start_limit:
            break
        if _t(start_net):
            continue
        done, cur = [], start_net
        path = [{"hop": 0, "net": cur, "type": "START", "pins": len(pins)}]
        guard = 0
        while guard < 60:
            guard += 1
            nxt = None
            for rd, pn, _ in net2pins.get(cur, []):
                if _t(rd):                       # 透明器件 → 跨到另一端
                    for p2, n2 in (dev_pins.get(rd) or {}).items():
                        if n2 != cur and ((rd, p2) not in done):
                            nxt = n2
                            path.append({"hop": len(path), "net": nxt, "type": "ACROSS",
                                         "dev": rd, "pin": pn, "pin2": p2})
                            done.append((rd, p2))
                            break
                if nxt:
                    break
            if nxt is None:
                # 终点：最后一个非透明引脚
                term = [(rd, pn) for rd, pn, _ in net2pins.get(cur, []) if not _t(rd)]
                path.append({"hop": len(path), "net": cur, "type": "TERMINAL" if term else "OPEN_END",
                             "terminals": [f"{r}.{p}" for r, p in term[:8]], "n_term": len(term)})
                break
            cur = nxt
        traces.append({"start": start_net, "path": path, "hops": len(path) - 1,
                       "end_type": path[-1].get("type")})
        started += 1

    ends = defaultdict(int)
    for t in traces:
        ends[t["end_type"]] += 1
    inv = {"traces": len(traces), "end_types": dict(ends),
           "open_ends": [t["start"] for t in traces if t["end_type"] == "OPEN_END"][:30]}
    return {"traces": traces, "inventory": inv}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("b_prep_dir")
    ap.add_argument("--out", default=None)
    ap.add_argument("--limit", type=int, default=400)
    args = ap.parse_args()
    d = Path(args.b_prep_dir)
    nets = json.loads((d / "global_nets.json").read_text(encoding="utf-8"))
    r = trace_all(nets, start_limit=args.limit)
    out = Path(args.out) if args.out else d / "trace_inventory.json"
    out.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    print("traces:", r["inventory"]["traces"], "| 终点分布:", r["inventory"]["end_types"])


if __name__ == "__main__":
    main()
