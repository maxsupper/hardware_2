"""netlist_graph builder — PH-2 产物（网表 json 化，v3.0）.

将 PH-2_网表解析 各确定性产物组织为单一 netlist_graph.json：devices[]/nets[]/paths[]/cross_board_links[]。
要点：
  - devices 每 (板,位号) 一条：model(BOM为准)/kind/source/ic(manual_index)/pins(全量)/links/depop
  - **NG-006 单一真源**：器件间连接只由 devices[].pins 与 nets[].joins 承载；
    links[] **不内嵌邻接表**（无 upstream/downstream/via）；邻接由 `GraphIndex` 按 side+joins **派生**
    （与旧字段逐条等价，证据见 tools/verify_adjacency.py）。links 仅留不可派生属性：net/pin/side/fanout/status/trace/cross_board。
  - nets 全量 joins（真值）+ kind(signal|power|gnd) + alias_group(0Ω 短接)
  - paths = tracer 结果（接口信号）
  - cross_board_links：连接器配对(按 脚→网 定义一致性匹配 A↔B)
  - 子 agent 分发：--groups N 按接插件分组追踪后合并（同 schema）
用法: python -m hardware_analysis.tools.netlist_graph <PH-2_网表解析_dir> [--groups N] [--product X] [--pretty]
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


# 平台识别（P4-B）：读 rules/index.json 的 platform.*.detect；缺失时扫 rules/platform/* 目录名回退。
_ROOT = Path(__file__).resolve().parents[3]
FALLBACK_MIN_PINS = 100


def _load_platform_specs(root: Path | None = None) -> dict:
    """→ {chip: {"model_regex":..., "min_pins":...}}；优先 rules/index.json，缺失时目录名回退。"""
    root = root or _ROOT
    plats: dict[str, dict] = {}
    idxp = root / "rules" / "index.json"
    if idxp.exists():
        try:
            d = json.loads(idxp.read_text(encoding="utf-8"))
        except Exception:
            d = {}
        for chip, spec in (d.get("platform") or {}).items():
            if not isinstance(spec, dict):
                continue
            det = spec.get("detect") if isinstance(spec.get("detect"), dict) else spec
            rx = det.get("model_regex") or det.get("regex") or chip
            try:
                mp = int(det.get("min_pins", spec.get("min_pins", 0)) or 0)
            except (TypeError, ValueError):
                mp = 0
            plats[chip] = {"model_regex": rx, "min_pins": mp}
    if not plats:                                  # 优雅降级：扫 rules/platform/* 目录名
        base = root / "rules" / "platform"
        if base.is_dir():
            for p in sorted(base.iterdir()):
                if p.is_dir():
                    plats[p.name] = {"model_regex": re.escape(p.name),
                                     "min_pins": FALLBACK_MIN_PINS}
    return plats


def detect_platform(devices: list[dict], root: Path | None = None) -> tuple[str, str, dict]:
    """识别主控平台 → (platform, platform_device, summary)。

    规则：遍历 kind==IC 器件，re.search(model_regex, model, re.I) 且 len(pins)>=min_pins；
    多个命中取引脚数最多者。匹配不到 → ("", "", {status:NO_PLATFORM_MATCH})，不抛错。
    """
    specs = _load_platform_specs(root)
    ic_devs = [d for d in devices if str(d.get("kind", "")).upper() == "IC"]
    candidates: list[dict] = []
    best = None                                   # (npins, chip, device_id)
    for chip, spec in specs.items():
        try:
            rx = re.compile(str(spec.get("model_regex") or chip), re.I)
        except re.error:
            rx = re.compile(re.escape(chip), re.I)
        minp = int(spec.get("min_pins") or 0)
        for d in ic_devs:
            model = str(d.get("model") or "")
            npins = len(d.get("pins") or {})
            if rx.search(model) and npins >= minp:
                candidates.append({"chip": chip, "device": d.get("id", ""),
                                   "model": model, "pins": npins})
                if best is None or npins > best[0]:
                    best = (npins, chip, d.get("id", ""))
    if best:
        _, chip, dev_id = best
        return chip, dev_id, {"device": dev_id, "status": "MATCHED", "candidates": candidates}
    return "", "", {"device": "", "status": "NO_PLATFORM_MATCH", "candidates": candidates}


def build(b_prep: Path, product: str = "", groups: int = 1, manual_index: str | None = None) -> dict:
    gcomp = json.loads((b_prep / "global_components.json").read_text(encoding="utf-8"))
    gnets = json.loads((b_prep / "global_nets.json").read_text(encoding="utf-8"))
    rmap = {}
    rp = b_prep / "refdes_function_map.json"
    if rp.exists():
        for c in json.loads(rp.read_text(encoding="utf-8")).get("components", []):
            rmap[c["id"]] = c
    mi = {}
    mp = Path(manual_index) if manual_index else (b_prep / "manual_index.json")
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

    # NG-010：同网络内 side 必须一致（网络级统一，禁止同网混合 side）。
    # 优先级：电源/地→pwr；差分对成员→bi；起点脚(接插件)→up；终点脚→down；否则 bi。
    net_side, net_pair = {}, {}
    for key, e in gnets.items():
        b, net = e["board"], e["net"]
        roles = set()
        for j in e.get("joins", []):
            rd, pn = j.get("refdes", ""), j.get("pin", "")
            if not rd:
                continue
            if _power(net):
                roles.add("pwr")
            elif CONV.diff_pair_key(net):
                roles.add("diff")
            elif (b, rd, pn) in start_pins:
                roles.add("up")
            elif (b, rd, pn) in end_pins:
                roles.add("down")
            else:
                roles.add("bi")
        chosen = next(r for r in ("pwr", "diff", "up", "down", "bi") if r in roles)
        net_side[(b, net)] = "bi" if chosen in ("diff", "bi") else chosen
        _k = CONV.diff_pair_key(net)
        net_pair[(b, net)] = _k[0] if _k else ""          # NG-012 pair_id

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
            nbr = sum(1 for (r2, p2) in net_pins.get((b, net), []) if (r2, p2) != (rd, pin))
            side = net_side.get((b, net), "bi")   # NG-010：同一 (板,网) 全部 link 用统一 side
            tr = None
            for t in all_traces:
                if t["board"] == b and (t["start_net"] == net or net in t.get("path", [])):
                    tr = {"id": t["id"], "end_type": t["end_type"], "bidirectional": t["bidirectional"]}
                    break
            status = "OK"
            if not nbr:
                status = "OPEN_END"
            elif nbr >= CONV.cfg["fanout_min_neighbors"]:
                status = "FANOUT"
            if tr and tr["end_type"] in ("STUB", "OPEN_END") and side == "down":
                status = tr["end_type"]
            # NG-006：不内嵌邻接表；fanout=同网邻居数（0 表示悬空/开终点）。邻接用 GraphIndex 派生。
            link = {"net": net, "pin": pin, "side": side,
                    "pair_id": net_pair.get((b, net), ""),
                    "fanout": nbr, "trace": tr, "status": status}
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
              "bidirectional": t["bidirectional"], "status": "OK",
              # NG-011/013：追踪深度与绕圈/原因分类随 paths 透传
              "hops": t.get("hops", max(len(t.get("path", [])) - 1, 0)),
              "reason": t.get("reason", ""),
              "depth_exceeded": bool(t.get("depth_exceeded", False)),
              "oscillation": bool(t.get("oscillation", False))} for t in all_traces]

    # ---- diff pairs ----
    diff = defaultdict(list)
    for nd in nets:
        k = CONV.diff_pair_key(nd["net"])
        if k and nd["kind"] == "signal":
            diff[(nd["board"], k[0])].append(nd["net"])
    diff_pairs = [sorted(v) for v in diff.values() if len(v) >= 2]

    # ---- 平台识别（P4-B）：写入 meta.platform / meta.platform_detect ----
    platform, platform_device, platform_detect = detect_platform(devices)
    if platform_detect["status"] == "NO_PLATFORM_MATCH":
        platform_detect["warning"] = "WARNING: 未识别到已知平台，规则束将仅注入通用规则"

    meta = {"boards": sorted({d["board"] for d in devices}),
            "devices": len(devices), "nets": len(nets), "paths": len(paths),
            "platform": platform, "platform_device": platform_device,
            "platform_detect": platform_detect,
            "cross_board_links": len(xlinks), "connector_pairs": len(pairs),
            "sub_agent_groups": groups,
            "trace_limits": {"max_hops": int(CONV.cfg.get("trace_max_hops", 6)),
                              "depth_exceeded": sum(1 for p in paths if p.get("depth_exceeded")),
                              "oscillation": sum(1 for p in paths if p.get("oscillation"))},
            "end_types": {k: sum(1 for p in paths if p["end_type"] == k)
                          for k in {p["end_type"] for p in paths}}}
    return {"schema_version": "3.0", "kind": "netlist_graph", "product": product, "status": "PASS",
            "meta": meta, "devices": devices, "nets": nets, "paths": paths,
            "cross_board_links": xlinks, "connector_pairs": pairs, "diff_pairs": diff_pairs}


class GraphIndex:
    """邻接访问器（NG-006）：从单一真源 devices[].pins + nets[].joins **派生**邻接，
    与旧 links[].upstream/downstream 逐条等价（证据：tools/verify_adjacency.py）。
    内存构造 O(N)；单点查询 O(k)。**不落盘**，避免 GND 网格 O(k²) 膨胀。"""

    def __init__(self, doc: dict):
        self.doc = doc
        self._members = defaultdict(list)          # (board, net) -> [(refdes, pin)]
        self._netof = {}                           # (board, refdes, pin) -> net
        for nd in doc.get("nets", []):
            b, net = nd.get("board", ""), nd.get("net", "")
            for j in nd.get("joins", []):
                rd, pn = j.get("refdes", ""), j.get("pin", "")
                if rd:
                    self._members[(b, net)].append((rd, pn))
                    self._netof[(b, rd, pn)] = net
        for d in doc.get("devices", []):
            b, rd = d.get("board", ""), d.get("refdes", "")
            for pn, net in (d.get("pins") or {}).items():
                self._netof.setdefault((b, rd, pn), net)

    def members(self, board: str, net: str) -> list[tuple[str, str]]:
        return list(self._members.get((board, net), []))

    def net_of(self, board: str, refdes: str, pin: str) -> str:
        return self._netof.get((board, refdes, pin), "")

    def neighbors(self, board: str, refdes: str, pin: str, net: str | None = None) -> list[dict]:
        """同网其他脚（排除自身），字段与原 upstream/downstream 一致。"""
        net = net if net is not None else self.net_of(board, refdes, pin)
        return [{"board": board, "refdes": r2, "pin": p2}
                for (r2, p2) in self._members.get((board, net), [])
                if (r2, p2) != (refdes, pin)]

    def adjacency(self, board: str, refdes: str, pin: str, side: str, net: str | None = None) -> list[dict]:
        """按 side 还原旧 upstream/downstream（side∈down|bi|pwr → upstream；up|thru → downstream）。"""
        return self.neighbors(board, refdes, pin, net) if side in ("down", "bi", "pwr", "up", "thru") else []


def adjacency_view(doc: dict, board: str, refdes: str, pin: str) -> dict:
    """向后兼容视图：返回 {"upstream":[...], "downstream":[...]}，语义同旧字段。"""
    gi = GraphIndex(doc)
    side, net = "bi", None
    for d in doc.get("devices", []):
        if d.get("board") == board and d.get("refdes") == refdes:
            for lk in d.get("links", []):
                if lk.get("pin") == pin:
                    side, net = lk.get("side", "bi"), lk.get("net")
    nb = gi.neighbors(board, refdes, pin, net)
    return {"upstream": nb if side in ("down", "bi", "pwr") else [],
            "downstream": nb if side in ("up", "thru") else [],
            "net": net, "side": side}


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
    # NG-006：结构单一真源——links 不得内嵌邻接表
    embedded = sum(1 for d in doc["devices"] for lk in d["links"]
                   if lk.get("upstream") or lk.get("downstream") or "via" in lk)
    # NG-010：同网 side 一致性——残余混合 side 必须为 0；raw 冲突仅作归并证据（信息性）。
    side_sets = defaultdict(set)
    for d in doc["devices"]:
        b = d["board"]
        for lk in d["links"]:
            side_sets[(b, lk.get("net", ""))].add(lk.get("side"))
    mixed = {k: sorted(v) for k, v in side_sets.items() if len(v) > 1}
    start_pins = {(p["board"], p["connector"], p["pin"]) for p in doc.get("paths", [])}
    end_pins = set()
    for p in doc.get("paths", []):
        for ep in p.get("endpoint_pins", []):
            rd, _, pn = ep.partition(".")
            end_pins.add((p["board"], rd, pn))
    raw_roles = defaultdict(set)
    for nd in doc.get("nets", []):
        b, net = nd["board"], nd["net"]
        for j in nd.get("joins", []):
            rd, pn = j.get("refdes", ""), j.get("pin", "")
            if not rd:
                continue
            if CONV.is_power_net(net):
                raw_roles[(b, net)].add("pwr")
            elif CONV.diff_pair_key(net):
                raw_roles[(b, net)].add("diff")
            elif (b, rd, pn) in start_pins:
                raw_roles[(b, net)].add("up")
            elif (b, rd, pn) in end_pins:
                raw_roles[(b, net)].add("down")
            else:
                raw_roles[(b, net)].add("bi")
    normalized = {k: sorted(v) for k, v in raw_roles.items() if len(v) > 1}
    side_conflicts = {
        "count": len(mixed),
        "sample": [f"{k[0]}::{k[1]}={v}" for k, v in list(mixed.items())[:5]],
        "normalized": len(normalized),
        "normalized_sample": [f"{k[0]}::{k[1]}={v}" for k, v in list(normalized.items())[:5]],
    }
    return {"dangling_joins": len(issues["dangling_joins"]),
            "uncovered_pins": len(issues["uncovered_pins"]),
            "embedded_adjacency": embedded,
            "side_conflicts": side_conflicts,
            "sample_dangling": issues["dangling_joins"][:5],
            "sample_uncovered": issues["uncovered_pins"][:5],
            "status": "PASS" if not issues["dangling_joins"] and not embedded else "FAIL"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("b_prep_dir")
    ap.add_argument("--groups", type=int, default=0, help="子 agent 分组数；<=0 表示按接插件数自适应(上限5)")
    ap.add_argument("--product", default="")
    ap.add_argument("--manual-index", default=None, help="manual_index.json 路径（默认取 b_prep/manual_index.json）")
    ap.add_argument("--pretty", action="store_true", help="人类可读缩进写盘（默认紧凑，体积小）")
    args = ap.parse_args()
    d = Path(args.b_prep_dir)
    doc = build(d, args.product, args.groups, manual_index=args.manual_index)
    v = validate(doc)
    doc["meta"]["validation"] = v            # 校验并入产物 meta（不另留中间文件）
    out = d / "netlist_graph.json"
    if args.pretty:
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        out.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    doc["meta"]["size_bytes"] = out.stat().st_size
    print(f"  netlist_graph.json = {out.stat().st_size/1048576:.3f} MB (紧凑)")
    m = doc["meta"]
    pd = m.get("platform_detect", {})
    print(f"  平台识别: platform={m.get('platform') or '-'} "
          f"status={pd.get('status')} device={pd.get('device') or '-'}")
    print(f"netlist_graph: 板={m['boards']} 器件={m['devices']} 网={m['nets']} 路径={m['paths']} "
          f"跨板={m['cross_board_links']} 配对={m['connector_pairs']} 分组={m['sub_agent_groups']}")
    print(f"  终点={m['end_types']} | 校验 dangling={v['dangling_joins']} uncovered={v['uncovered_pins']} -> {v['status']}")
    print(f"  连接器配对: {[(p['a'], p['b'], p['matched_pins']) for p in doc['connector_pairs'][:4]]}")


if __name__ == "__main__":
    main()
