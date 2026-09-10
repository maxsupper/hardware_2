"""netlist_graph builder — PH-3 产物（网表 json 化，v2.2）.

将 B_prep 各确定性产物组织为单一 netlist_graph.json：devices[]/nets[]/paths[]/cross_board_links[]。
要点（用户确认 A 方案）：
  - devices 每 (板,位号) 一条：model(BOM为准)/kind/source/ic(manual_index)/pins(全量)/links(上级-下级)/depop
  - nets 全量 joins（真值）+ kind(signal|power|gnd) + alias_group(0Ω 短接)
  - paths = tracer 结果（接口信号）
  - links：按脚拆条，扇出→多邻居(FANOUT)，电源→pwr，纯芯片间→bi，跨板→cross_board.peer
  - cross_board_links：连接器配对(D1，按 脚→网 定义一致性匹配 A↔B)
  - 子 agent 分发：--groups N 按接插件分组追踪后合并（同 schema）
用法: python -m hardware_analysis.tools.netlist_graph <B_prep_dir> [--groups N] [--product X]
"""
from __future__ import annotations
import argparse, json, re, sys
from collections import defaultdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hardware_analysis.tools import tracer as _tracer
from hardware_analysis.common.conventions import CONV


def kind_of(rd: str) -> str:
    return CONV.kind_of(rd)


def _pinnorm(pin: str) -> str:
    return CONV.pin_norm(pin)


def _netnorm(net: str) -> str:
    return CONV.net_norm(net)


def _power(net: str) -> bool:
    return CONV.is_power_net(net)


def _is_zero_ohm(dev: dict) -> bool:
    sym = (dev.get("provenance", {}).get("edn_symbol") or "").upper()
    return "ZEROOHM" in sym or "0OHM" in sym


def connector_pairs(dev_pins: dict, kinds: dict) -> tuple[list, list]:
    """D1: A↔B 连接器配对。**按脚号一一配对**（网名仅作信号连续性佐证，避免 GND 塔缩）。"""
    by_board = defaultdict(list)
    for (b, rd), pins in dev_pins.items():
        if kinds.get((b, rd)) == "CONNECTOR" and len(pins) >= 2:
            by_board[b].append((rd, pins))
    boards = sorted(by_board)
    if len(boards) < 2:
        return [], []
    a_board, b_board = boards[0], boards[1]

    def pin_corr(pa, pb):
        b_by_pin = {_pinnorm(pn): (pn, n) for pn, n in pb.items()}
        out = []
        for pn_a, na in pa.items():
            hit = b_by_pin.get(_pinnorm(pn_a))
            if hit:
                out.append((pn_a, hit[0], na, hit[1]))
        return out

    scored = []
    for ra, pa in by_board[a_board]:
        for rb, pb in by_board[b_board]:
            corr = pin_corr(pa, pb)
            sig = sum(1 for _, _, na, nb in corr
                      if not _power(na) and _netnorm(na) == _netnorm(nb))
            pinm = len(corr)
            if pinm >= CONV.cfg["connector_pair_min_signal"]:
                scored.append((sig, pinm, ra, rb, corr))
    pairs, links, used_b = [], [], set()
    for sig, pinm, ra, rb, corr in sorted(scored, reverse=True):
        if rb in used_b or sig < CONV.cfg["connector_pair_min_signal"]:
            continue
        used_b.add(rb)
        pairs.append({"a": f"{a_board}::{ra}", "b": f"{b_board}::{rb}",
                      "score": round(sig / max(pinm, 1), 3), "matched_pins": pinm,
                      "signal_matched": sig})
        for pn_a, pn_b, na, nb in corr:
            links.append({"a": f"{a_board}::{ra}.{pn_a}", "b": f"{b_board}::{rb}.{pn_b}",
                          "net_a": na, "net_b": nb, "method": "connector_pin",
                          "kind": "gnd" if _power(na) and "GND" in na.upper()
                                  else ("power" if _power(na) else "signal"),
                          "net_match": _netnorm(na) == _netnorm(nb)})
    return pairs, links


def build(b_prep: Path, product: str = "", groups: int = 1) -> dict:
    gcomp = json.loads((b_prep / "global_components.json").read_text(encoding="utf-8"))
    gnets = json.loads((b_prep / "global_nets.json").read_text(encoding="utf-8"))
    rmap = {}
    rp = b_prep / "refdes_function_map.json"
    if rp.exists():
        for c in json.loads(rp.read_text(encoding="utf-8")).get("components", []):
            rmap[c["id"]] = c
    mi = {}
    mp = b_prep / "manual_index.json"
    if mp.exists():
        mi = json.loads(mp.read_text(encoding="utf-8")).get("entries", {})

    # ---- pins / 设备索引 ----
    dev_pins = defaultdict(dict)          # (b,rd) -> {pin: net}
    net_pins = defaultdict(list)          # (b,net) -> [(rd,pin)]
    net_joins = {}                        # key -> joins
    for key, e in gnets.items():
        b, net = e["board"], e["net"]
        joins = e.get("joins", [])
        net_joins[key] = joins
        for j in joins:
            rd, pn = j.get("refdes", ""), j.get("pin", "")
            if rd:
                dev_pins[(b, rd)][pn] = net
                net_pins[(b, net)].append((rd, pn))
    kinds = {k: kind_of(k[1]) for k in dev_pins}

    # ---- 子 agent 分发追踪并合并（groups<=0 表示按接插件数自适应，上限 5） ----
    conns = [(b, rd) for (b, rd) in dev_pins if kinds.get((b, rd)) == "CONNECTOR"]
    if groups is None or groups <= 0:
        groups = min(5, max(1, len(conns)))
    all_traces = []
    if groups > 1 and conns:
        for i in range(groups):
            part = conns[i::groups]
            all_traces += _tracer.trace(gnets, only_connectors=part)["traces"]
    else:
        all_traces = _tracer.trace(gnets)["traces"]

    # 起点/终点索引
    start_pins, end_pins, via_by_net = set(), set(), {}
    for t in all_traces:
        start_pins.add((t["board"], t["connector"], t["pin"]))
        for ep in t.get("endpoint_pins", []):
            rd, _, pn = ep.partition(".")
            end_pins.add((t["board"], rd, pn))
        for i, n in enumerate(t.get("path", [])):
            via_by_net.setdefault((t["board"], n), []).append(
                {"trace_id": t.get("id", ""), "index": i, "n": len(t.get("path", []))})
    for i, t in enumerate(all_traces):
        t["id"] = f"T-{i+1:04d}"

    # ---- 0Ω 别名组 ----
    alias_of = {}
    for key, c in gcomp.items():
        b, rd = key.split("::", 1)
        if _is_zero_ohm(rmap.get(key, {})) and len(dev_pins.get((b, rd), {})) == 2:
            nets = sorted(dev_pins[(b, rd)].values())
            gid = f"alias::{_netnorm(nets[0])}"
            for n in nets:
                alias_of[(b, n)] = gid

    # ---- cross board ----
    pairs, xlinks = connector_pairs(dev_pins, kinds)
    peer_of = {}
    for lk in xlinks:
        peer_of[lk["a"]] = lk["b"]
        peer_of[lk["b"]] = lk["a"]

    # ---- devices ----
    devices = []
    for key, c in sorted(gcomp.items()):
        b, rd = key.split("::", 1)
        pins = dev_pins.get((b, rd), {})
        meta = rmap.get(key, {})
        prov = meta.get("provenance", {})
        mdl = (meta.get("identity", {}).get("model") or c.get("model") or "")
        populated = prov.get("populated", True)
        dev = {
            "id": key, "board": b, "refdes": rd, "model": mdl, "kind": kinds.get((b, rd), "OTHER"),
            "source": {"in_bom": prov.get("in_bom", False), "in_edn": True, "populated": populated,
                       "edn_symbol": prov.get("edn_symbol", "")},
            "ic": {}, "pins": dict(pins), "links": [], "depop": [],
        }
        if kinds.get((b, rd)) == "IC":
            e = mi.get(key, {})
            dev["ic"] = {"manual_path": e.get("manual_path"), "ic_type": e.get("ic_type", "UNKNOWN"),
                         "manual_status": e.get("status", "MISSING"), "channels": []}
        if not populated:
            dev["depop"] = [{"pin": p, "net": n} for p, n in pins.items()]
        # links：按脚拆条
        for pin, net in pins.items():
            if not net:
                continue
            nb = [{"board": b, "refdes": r2, "pin": p2,
                   "model": (rmap.get(f"{b}::{r2}", {}).get("identity", {}).get("model", "")),
                   "kind": kinds.get((b, r2), "OTHER")}
                  for (r2, p2) in net_pins.get((b, net), []) if (r2, p2) != (rd, pin)]
            if _power(net):
                side = "pwr"
            elif (b, rd, pin) in start_pins:
                side = "up"
            elif (b, rd, pin) in end_pins:
                side = "down"
            else:
                side = "bi"
            tr = None
            for t in all_traces:
                if t["board"] == b and (t["start_net"] == net or net in t.get("path", [])):
                    tr = {"id": t["id"], "end_type": t["end_type"], "bidirectional": t["bidirectional"]}
                    break
            status = "OK"
            if not nb:
                status = "OPEN_END"
            elif len(nb) >= CONV.cfg["fanout_min_neighbors"]:
                status = "FANOUT"
            if tr and tr["end_type"] in ("STUB", "OPEN_END") and side == "down":
                status = tr["end_type"]
            link = {"net": net, "pin": pin, "side": side,
                    "upstream": nb if side in ("down", "bi", "pwr") else [],
                    "downstream": nb if side in ("up", "thru") else [],
                    "via": [], "trace": tr, "status": status}
            if f"{b}::{rd}.{pin}" in peer_of:
                link["cross_board"] = {"peer": peer_of[f"{b}::{rd}.{pin}"], "status": "PAIRED"}
            dev["links"].append(link)
        devices.append(dev)

    # ---- nets ----
    nets = []
    for key, e in gnets.items():
        b, net = e["board"], e["net"]
        k = "gnd" if _power(net) and "GND" in net.upper() else (
            "power" if _power(net) else "signal")
        nets.append({"board": b, "net": net,
                     "joins": [{"refdes": j.get("refdes", ""), "pin": j.get("pin", "")} for j in e.get("joins", [])],
                     "kind": k, "alias_group": alias_of.get((b, net), "")})

    # ---- paths ----
    paths = [{"id": t["id"], "board": t["board"], "connector": t["connector"], "pin": t["pin"],
              "start_net": t["start_net"], "path": t.get("path", []),
              "endpoint_pins": t.get("endpoint_pins", []), "end_type": t["end_type"],
              "bidirectional": t["bidirectional"], "status": "OK"} for t in all_traces]

    # ---- diff pairs ----
    diff = defaultdict(list)
    for nd in nets:
        k = CONV.diff_pair_key(nd["net"])
        if k and nd["kind"] == "signal":
            diff[(nd["board"], k[0])].append(nd["net"])
    diff_pairs = [sorted(v) for v in diff.values() if len(v) >= 2]

    meta = {"boards": sorted({d["board"] for d in devices}),
            "devices": len(devices), "nets": len(nets), "paths": len(paths),
            "cross_board_links": len(xlinks), "connector_pairs": len(pairs),
            "sub_agent_groups": groups,
            "end_types": {k: sum(1 for p in paths if p["end_type"] == k)
                          for k in {p["end_type"] for p in paths}}}
    return {"schema_version": "2.2", "kind": "netlist_graph", "product": product, "status": "PASS",
            "meta": meta, "devices": devices, "nets": nets, "paths": paths,
            "cross_board_links": xlinks, "connector_pairs": pairs, "diff_pairs": diff_pairs}


def validate(doc: dict) -> dict:
    """G3 完整性自检（确定性）。"""
    dev_ids = {d["id"] for d in doc["devices"]}
    issues = {"dangling_joins": [], "uncovered_pins": [], "orphan_endpoints": [], "alias_ok": True}
    pins_of = {d["id"]: d["pins"] for d in doc["devices"]}
    link_cov = defaultdict(set)
    for d in doc["devices"]:
        for lk in d["links"]:
            link_cov[d["id"]].add(lk["pin"])
    for nd in doc["nets"]:
        for j in nd["joins"]:
            i = f'{nd["board"]}::{j["refdes"]}'
            if j["refdes"] and i not in dev_ids:
                issues["dangling_joins"].append(f'{i}.{j["pin"]}')
            elif j["refdes"] and j["pin"] not in link_cov.get(i, set()):
                issues["uncovered_pins"].append(f'{i}.{j["pin"]}')
    return {"dangling_joins": len(issues["dangling_joins"]),
            "uncovered_pins": len(issues["uncovered_pins"]),
            "sample_dangling": issues["dangling_joins"][:5],
            "sample_uncovered": issues["uncovered_pins"][:5],
            "status": "PASS" if not issues["dangling_joins"] else "FAIL"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("b_prep_dir")
    ap.add_argument("--groups", type=int, default=0, help="子 agent 分组数；<=0 表示按接插件数自适应(上限5)")
    ap.add_argument("--product", default="")
    args = ap.parse_args()
    d = Path(args.b_prep_dir)
    doc = build(d, args.product, args.groups)
    v = validate(doc)
    doc["meta"]["validation"] = v            # 校验并入产物 meta（不另留中间文件）
    (d / "netlist_graph.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    m = doc["meta"]
    print(f"netlist_graph: 板={m['boards']} 器件={m['devices']} 网={m['nets']} 路径={m['paths']} "
          f"跨板={m['cross_board_links']} 配对={m['connector_pairs']} 分组={m['sub_agent_groups']}")
    print(f"  终点={m['end_types']} | 校验 dangling={v['dangling_joins']} uncovered={v['uncovered_pins']} -> {v['status']}")
    print(f"  连接器配对: {[(p['a'], p['b'], p['matched_pins']) for p in doc['connector_pairs'][:4]]}")


if __name__ == "__main__":
    main()
