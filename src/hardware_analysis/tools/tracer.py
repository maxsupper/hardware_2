"""端到端 tracer — 阶段3b（v4：严格服从 NG-010~014）.

规则（与 rules/rules.json 的 NG-010..014 对应）:
  NG-011 追踪：起点 = 接插件(J*/CN*/P*/CON*)脚；跨件仅限「真串联无源件」
          (conventions.is_series_passive：2 脚 R/L/BEAD/FB/FERR/JMP/0R 且两端非电源地)；
          ① 先判本网是否已有有源(U*)落点 → 有则已抵达，不再跨件；
          ② 访问集防绕圈：同一 (板,网) 只进一次；
          ③ 最大跨器件层数 trace_max_hops=6（超出记 DEPTH_EXCEEDED）。
  NG-012 差分对：conventions.diff_pair_key 识别 _P/_N、P/N、H/L、+/-；
          跨到当前网络的差分搭档 = 原地打转，不前进；追到任一端芯片即视为抵达。
  NG-013 双向验证：正向止于有源落点(芯片)，反向止于起点接插件(对称停止条件)；
          正反路径集合一致且回到起点接插件 → OK，否则 MISMATCH 且必带 reason 分类
          (OSCILLATION/DEPTH_EXCEEDED/NO_ACTIVE_END/REVERSE_NOT_HOME/PATH_DIFF/POWER_BRIDGE)；
          落点非芯片 → N/A。
  NG-014 落点判定：CHIP(有源 U* 脚) / TO_CONNECTOR(接插件) / POWER(电源地轨) /
          OPEN_END(本网无其他成员) / STUB(仅到无源件未达有源)。

电源/有源/接插件/串联件/差分对判定全部走 conventions 权威来源（NG-010：禁自造等价逻辑）。
用法: python -m hardware_analysis.tools.tracer <PH-2_网表解析_dir> [--out X.json]
"""
from __future__ import annotations
import argparse, json, sys
from collections import defaultdict, Counter
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hardware_analysis.common.conventions import CONV

# 落点五分类（NG-014）
END_TYPES = ("CHIP", "TO_CONNECTOR", "POWER", "OPEN_END", "STUB")
# MISMATCH 原因分类（NG-013）
REASONS = ("OSCILLATION", "DEPTH_EXCEEDED", "NO_ACTIVE_END",
           "REVERSE_NOT_HOME", "PATH_DIFF", "POWER_BRIDGE")


def build_index(global_nets: dict):
    """由 global_nets 建三类索引（单一真源：joins）。"""
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


def diff_twins(net2pins: dict) -> dict:
    """NG-012：差分对搭档索引 (board,net) -> 搭档网。

    conventions.diff_pair_key 识别 _P/_N、P/N、H/L、+/-；同 (板,base) 下成员互为搭档。
    """
    if not CONV.cfg.get("diff_pair_equivalent", True):
        return {}
    groups = defaultdict(set)                 # (board,base) -> {net,...}
    for (b, net) in net2pins:
        k = CONV.diff_pair_key(net)
        if k:
            groups[(b, k[0])].add(net)
    twins = {}
    for (b, base), members in groups.items():
        if len(members) >= 2:
            for n in members:
                twins[(b, n)] = next((m for m in sorted(members) if m != n), None)
    return twins


def _series_other(board, rd, cur, dev_pins) -> str | None:
    """若 rd 为真串联件且其一端在 cur，则返回另一端网络；否则 None。"""
    pins = dev_pins.get((board, rd)) or {}
    if not CONV.is_series_passive(rd, pins):        # NG-011：仅跨真串联件
        return None
    other = next((n for n in pins.values() if n != cur), None)
    if not other or CONV.is_power_net(other):       # 电源地网不作为前进落脚
        return None
    return other


def walk(net2pins, dev_pins, twins, board, start_net, origin_ref, goal_ref=None):
    """从 start_net 跨真串联无源件前进。

    返回 dict(path, end_net, branch, depth_exceeded, oscillation)：
      - NG-011① 本网已有有源落点 → 停；
      - NG-013  goal_ref（反向追踪的起点接插件）出现在本网 → 停（对称停止条件）；
      - NG-011② 访问集（同一 (板,网) 只进一次）；
      - NG-011③ trace_max_hops 上限；
      - NG-012  跨到当前网络的差分搭档 = 原地打转，不前进。
    """
    max_hops = int(CONV.cfg.get("trace_max_hops", 6))
    stop_at_active = bool(CONV.cfg.get("stop_at_active_net", True))
    path, cur = [start_net], start_net
    visited = {start_net}
    branch = False
    depth_exceeded = False
    for _ in range(max_hops):
        here = net2pins.get((board, cur), [])
        # NG-011① 先本网判定：已有有源落点 → 已抵达，不再跨件
        if stop_at_active and any(CONV.is_active(rd) for rd, _ in here if rd != origin_ref):
            break
        # NG-013 反向对称停止：回到目标接插件即停
        if goal_ref and any(rd == goal_ref for rd, _ in here):
            break
        cands = []
        for rd, _pn in here:
            if rd == origin_ref:
                continue
            other = _series_other(board, rd, cur, dev_pins)
            if not other or other in visited:              # NG-011② 防绕圈
                continue
            tw = twins.get((board, other))
            if tw and tw in visited:                       # NG-012 跨到搭档=原地打转
                continue
            cands.append((rd, other))
        if not cands:
            break
        if len(cands) > 1:
            branch = True                                  # 分叉（信息性）
        _, nxt = sorted(cands)[0]
        path.append(nxt)
        visited.add(nxt)
        cur = nxt
    else:
        depth_exceeded = True                              # 用尽 max_hops 仍可继续
    return {"path": path, "end_net": cur, "branch": branch,
            "depth_exceeded": depth_exceeded,
            "oscillation": len(path) != len(set(path))}


def end_type(board, end_net, origin_ref, net2pins):
    """NG-014 落点五分类；返回 (end_type, ends, actives, conns)。"""
    ends = [(rd, pn) for rd, pn in net2pins.get((board, end_net), []) if rd != origin_ref]
    actives = [(rd, pn) for rd, pn in ends if CONV.is_active(rd)]
    conns = [(rd, pn) for rd, pn in ends if CONV.is_connector(rd)]
    if CONV.is_power_net(end_net):
        et = "POWER"
    elif actives:
        et = "CHIP"
    elif conns:
        et = "TO_CONNECTOR"
    elif not ends:
        et = "OPEN_END"
    else:
        et = "STUB"
    return et, ends, actives, conns


def _classify_reason(fpath, rpath, fbranch, fdepth, rdepth, rend, conn, net2pins, board) -> str:
    """NG-013 MISMATCH 原因分类（按规范列举顺序判定）。"""
    if len(fpath) != len(set(fpath)) or len(rpath) != len(set(rpath)):
        return "OSCILLATION"
    if fdepth or rdepth:
        return "DEPTH_EXCEEDED"
    r_ends = net2pins.get((board, rend), [])
    if not any(CONV.is_active(rd) for rd, _ in r_ends):
        return "NO_ACTIVE_END"
    if not any(rd == conn for rd, _ in r_ends):
        return "REVERSE_NOT_HOME"
    if set(fpath) != set(rpath):
        return "PATH_DIFF"
    if any(CONV.is_power_net(n) for n in fpath[1:]):
        return "POWER_BRIDGE"
    return "PATH_DIFF"


def trace(global_nets: dict, only_connectors: list | None = None) -> dict:
    """追踪全部接插件引脚，返回 {"traces":[...], "inventory":{...}}（契约不变）。"""
    net2pins, pin2net, dev_pins = build_index(global_nets)
    twins = diff_twins(net2pins)
    max_hops = int(CONV.cfg.get("trace_max_hops", 6))
    connectors = sorted((b, rd) for (b, rd) in dev_pins if CONV.is_connector(rd))
    if only_connectors is not None:
        keep = set(only_connectors)
        connectors = [c for c in connectors if c in keep]

    results = []
    for b, conn in connectors:
        for pin, start_net in dev_pins[(b, conn)].items():
            fwd = walk(net2pins, dev_pins, twins, b, start_net, conn)
            fpath, fend = fwd["path"], fwd["end_net"]
            ftype, ends, actives, conns = end_type(b, fend, conn, net2pins)

            bidir, reason = "N/A", ""
            rdepth = False
            if ftype == "CHIP" and actives:
                chip_rd, chip_pn = actives[0]
                chip_net = pin2net.get((b, chip_rd, chip_pn), start_net)
                # NG-013 反向追踪：起点=落点芯片脚，goal=起点接插件（对称停止）
                rev = walk(net2pins, dev_pins, twins, b, chip_net, chip_rd, goal_ref=conn)
                rpath, rend, rdepth = rev["path"], rev["end_net"], rev["depth_exceeded"]
                same = set(rpath) == set(fpath)
                back_home = any(rd == conn for rd, _ in net2pins.get((b, rend), []))
                if same and back_home:
                    bidir = "OK"
                else:
                    bidir = "MISMATCH"
                    reason = _classify_reason(fpath, rpath, fwd["branch"],
                                              fwd["depth_exceeded"], rdepth, rend, conn,
                                              net2pins, b)
            endpoint = (actives or conns or ends)[:6] if ftype != "POWER" else ends[:6]
            results.append({
                "board": b, "connector": conn, "pin": pin, "start_net": start_net,
                "path": fpath, "hops": len(fpath) - 1,
                "endpoint_pins": [f"{rd}.{pn}" for rd, pn in endpoint],
                "end_type": ftype, "bidirectional": bidir,
                "reason": reason,
                "depth_exceeded": bool(fwd["depth_exceeded"] or rdepth),
                "oscillation": bool(fwd["oscillation"]),
            })

    ends = Counter(r["end_type"] for r in results)
    mism = [r for r in results if r["bidirectional"] == "MISMATCH"]
    inv = {
        "interface_signals": len(results),
        "end_types": dict(ends),
        "bidir_ok": sum(1 for r in results if r["bidirectional"] == "OK"),
        "bidir_mismatch": len(mism),
        "open_ends": [f"{r['board']}::{r['connector']}.{r['pin']}"
                      for r in results if r["end_type"] == "OPEN_END"][:40],
        "mismatches": [f"{r['board']}::{r['connector']}.{r['pin']}" for r in mism][:40],
        "mismatch_reasons": dict(Counter(r["reason"] for r in mism)),
        "max_hops": max_hops,
    }
    return {"traces": results, "inventory": inv}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("b_prep_dir")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    d = Path(args.b_prep_dir)
    nets = json.loads((d / "global_nets.json").read_text(encoding="utf-8"))
    r = trace(nets)
    out = Path(args.out) if args.out else d / "trace_inventory.json"
    out.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    inv = r["inventory"]
    print(f"接口信号={inv['interface_signals']} | 终点={inv['end_types']} | "
          f"双向OK={inv['bidir_ok']} 不符={inv['bidir_mismatch']} | max_hops={inv['max_hops']}")
    if inv["mismatch_reasons"]:
        print(f"  不符原因={inv['mismatch_reasons']}")
    print(f"  悬空={len(inv['open_ends'])} 双向不符样例={inv['mismatches'][:3]}")


if __name__ == "__main__":
    main()
