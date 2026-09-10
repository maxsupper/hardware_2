"""端到端 tracer — 阶段3b（v2：接口优先，符合 raw 引脚核对规则）.

规则(A 方案):
  起点 = 接插件(J*)引脚；跨透明器件(R/L/BEAD/0R)追踪 → 落到芯片/驱动端引脚；
  反向验证：从落点芯片引脚回追，两路径必须一致；否则 BIDIR_MISMATCH。
  终点判定: CHIP(芯片引脚) / TO_CONNECTOR(到另一接插件) / OPEN_END(悬空) / STUCK(卡住)
电源例外: 轨 → PMIC SW/输出（另passthrough，这里先做接口主线）。
用法: python -m hardware_analysis.tools.tracer <B_prep_dir>
"""
from __future__ import annotations
import argparse, json, sys
from collections import defaultdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hardware_analysis.common.conventions import CONV


def _is_power(net: str) -> bool:
    return CONV.is_power_net(net)


def _t(refdes: str) -> bool:
    return CONV.is_transparent(refdes)


def _is_active(refdes: str) -> bool:
    return CONV.is_active(refdes)


def _is_conn(refdes: str) -> bool:
    return CONV.is_connector(refdes)


def build_index(global_nets: dict):
    net2pins = defaultdict(list)   # (board,net) -> [(refdes,pin)]
    pin2net = {}                   # (board,refdes,pin) -> net
    dev_pins = defaultdict(dict)   # (board,refdes) -> {pin: net}
    for key, e in global_nets.items():
        b, net = e["board"], e["net"]
        for j in e.get("joins", []):
            rd, pn = j.get("refdes", ""), j.get("pin", "")
            if not rd:
                continue
            net2pins[(b, net)].append((rd, pn))
            pin2net[(b, rd, pn)] = net
            dev_pins[(b, rd)][pn] = net
    return net2pins, pin2net, dev_pins


def _is_series_passive(b, rd, net2pins, dev_pins, cur):
    """真串联无源件：2 脚 R/L/BEAD/0Ω，且两端网络都非电源/地。"""
    if not _t(rd):
        return False
    pins = dev_pins.get((b, rd)) or {}
    if len(pins) != 2:
        return False
    nets = list(pins.values())
    return not any(_is_power(n) for n in nets)


def walk(net2pins, dev_pins, board, start_net, origin_ref):
    """从 start_net 跨【真串联无源件】前进，返回 (path_nets, endpoint_pins, end_type)。"""
    if _is_power(start_net):
        pins = net2pins.get((board, start_net), [])
        return [start_net], [(rd, pn) for rd, pn in pins if rd != origin_ref][:6], "POWER"
    path, cur, used = [start_net], start_net, set()
    for _ in range(CONV.cfg["trace_guard"]):
        pins = net2pins.get((board, cur), [])
        nxt = None
        for rd, pn in pins:
            if rd != origin_ref and (rd, pn) not in used and _is_series_passive(board, rd, net2pins, dev_pins, cur):
                for p2, n2 in (dev_pins.get((board, rd)) or {}).items():
                    if n2 != cur:
                        used.add((rd, pn)); nxt = n2
                        break
            if nxt:
                break
        if not nxt:
            break
        path.append(nxt); cur = nxt
    ends = [(rd, pn) for rd, pn in net2pins.get((board, cur), []) if rd != origin_ref]
    active = [(rd, pn) for rd, pn in ends if _is_active(rd)]
    conns = [(rd, pn) for rd, pn in ends if _is_conn(rd)]
    if _is_power(cur):
        end_type = "POWER"
    elif active:
        end_type = "CHIP"
    elif conns:
        end_type = "TO_CONNECTOR"
    elif not ends:
        end_type = "OPEN_END"
    else:
        end_type = "STUB"   # 只到无源件/无有源落点 → 未到驱动端
    return path, (active or conns or ends), end_type


def trace(global_nets: dict, only_connectors: list | None = None) -> dict:
    net2pins, pin2net, dev_pins = build_index(global_nets)
    connectors = [(b, rd) for (b, rd) in dev_pins if _is_conn(rd)]
    if only_connectors is not None:
        keep = set(only_connectors)
        connectors = [c for c in connectors if c in keep]
    results = []
    for b, conn in connectors:
        for pin, start_net in dev_pins[(b, conn)].items():
            fwd_path, ends, end_type = walk(net2pins, dev_pins, b, start_net, conn)
            # 反向验证：从落点芯片引脚回追
            bidir = "N/A"
            if end_type == "CHIP":
                active = [(rd, pn) for rd, pn in ends if _is_active(rd)]
                if active:
                    chip_rd, chip_pn = active[0]
                    back_path, back_ends, _ = walk(net2pins, dev_pins, b, pin2net.get((b, chip_rd, chip_pn), start_net), chip_rd)
                    bidir = "OK" if set(back_path) == set(fwd_path) and any(rd == conn for rd, _ in back_ends) else "MISMATCH"
            results.append({
                "board": b, "connector": conn, "pin": pin, "start_net": start_net,
                "path": fwd_path, "hops": len(fwd_path) - 1,
                "endpoint_pins": [f"{rd}.{pn}" for rd, pn in ends[:6]], "end_type": end_type,
                "bidirectional": bidir,
            })
    ends = defaultdict(int)
    for r in results:
        ends[r["end_type"]] += 1
    inv = {"interface_signals": len(results), "end_types": dict(ends),
           "bidir_ok": sum(1 for r in results if r["bidirectional"] == "OK"),
           "bidir_mismatch": sum(1 for r in results if r["bidirectional"] == "MISMATCH"),
           "open_ends": [f"{r['board']}::{r['connector']}.{r['pin']}" for r in results if r["end_type"] == "OPEN_END"][:40],
           "mismatches": [f"{r['board']}::{r['connector']}.{r['pin']}" for r in results if r["bidirectional"] == "MISMATCH"][:40]}
    return {"traces": results, "inventory": inv}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("b_prep_dir"); ap.add_argument("--out", default=None)
    args = ap.parse_args()
    d = Path(args.b_prep_dir)
    nets = json.loads((d / "global_nets.json").read_text(encoding="utf-8"))
    r = trace(nets)
    out = Path(args.out) if args.out else d / "trace_inventory.json"
    out.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    inv = r["inventory"]
    print(f"接口信号={inv['interface_signals']} | 终点={inv['end_types']} | 双向OK={inv['bidir_ok']} 不符={inv['bidir_mismatch']}")
    print(f"  悬空={len(inv['open_ends'])} 双向不符样例={inv['mismatches'][:3]}")


if __name__ == "__main__":
    main()
