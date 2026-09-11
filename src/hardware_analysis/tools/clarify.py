"""clarify 回环协议 — PH-4↔PH-3（有界≤3轮，计数独立于 G5/G6）.

PH-4 只读 netlist_graph.json；遇 STUB/OPEN_END/双向不符/ic_type 冲突 → 写 request（自含 scope+假设）。
PH-3 收到 request → **只重读源 EDN 该局部** 定向复查 → 写 resolution(CONFIRMED/CORRECTED + delta)。
3 轮未决 → link 标 UNVERIFIED 进"待核清单"，不阻塞。
用法:
  python -m hardware_analysis.tools.clarify emit   <PH-2_网表解析> <out_requests.jsonl>
  python -m hardware_analysis.tools.clarify resolve <product> <PH-2_网表解析> <requests.jsonl> <out_resolutions.jsonl>
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

MAX_ROUNDS = 3


def _board_of(name: str) -> str:
    from hardware_analysis.common.conventions import CONV
    return CONV.board_of(name)


def emit_requests(b_prep: Path, out_path: Path) -> list:
    """从 netlist_graph 中挑出需回环的 link（status STUB/OPEN_END，或 IC 未定 ic_type）。"""
    g = json.loads((b_prep / "netlist_graph.json").read_text(encoding="utf-8"))
    reqs = []
    for d in g["devices"]:
        if d["kind"] == "IC" and d.get("ic", {}).get("ic_type") in ("UNKNOWN", None):
            reqs.append({"ref": f"CT-{len(reqs)+1:04d}", "kind": "verify_ic_type",
                         "device": d["id"], "question": "ic_type 未定，请复核该 IC 类型与通道",
                         "scope": {"board": d["board"], "refdes": d["refdes"]}})
        for lk in d["links"]:
            if lk.get("status") in ("STUB", "OPEN_END"):
                reqs.append({"ref": f"CT-{len(reqs)+1:04d}", "kind": "verify_trace",
                             "device": d["id"], "pin": lk["pin"],
                             "question": f"追踪终点 {(lk.get('trace') or {}).get('end_type')}，请复核对端",
                             "scope": {"board": d["board"], "net": lk["net"], "refdes": d["refdes"]},
                             "hypothesis": {"expected_endpoint": None}})
    out_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in reqs), encoding="utf-8")
    return reqs


def _edn_net_joins(product: str, board: str, net: str, project_dir: str = "project") -> list | None:
    """只重读源 EDN 该文件，取指定网络的 joins（真值）。"""
    from hardware_analysis.tools import edn_parse
    d = Path(project_dir) / product
    for f in list(d.glob("*.EDN")) + list(d.glob("*.edn")):
        if _board_of(f.name) != board:
            continue
        r = edn_parse.extract(f.read_bytes().decode("utf-8", errors="replace"))
        for n in r["nets"]:
            if n["net"] == net:
                return n["joins"]
    return None


def resolve(product: str, b_prep: Path, req_path: Path, out_path: Path,
            project_dir: str = "project") -> list:
    g = json.loads((b_prep / "netlist_graph.json").read_text(encoding="utf-8"))
    net_joins = {(n["board"], n["net"]): n["joins"] for n in g["nets"]}
    res = []
    for line in req_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        req = json.loads(line)
        sc = req.get("scope", {})
        board, net = sc.get("board", ""), sc.get("net", "")
        if not net:
            res.append({"ref": req["ref"], "result": "UNRESOLVED", "round": 1,
                        "evidence": {"reason": "无 net scope，需人工"}, "apply_to": {}})
            continue
        src = _edn_net_joins(product, board, net, project_dir)
        cur = net_joins.get((board, net), [])
        if src is None:
            r = {"ref": req["ref"], "result": "UNRESOLVED", "round": 1,
                 "evidence": {"reason": "源 EDN 无此网"}, "apply_to": {}}
        elif sorted((j["refdes"], j["pin"]) for j in src) == sorted((j["refdes"], j["pin"]) for j in cur):
            r = {"ref": req["ref"], "result": "CONFIRMED", "round": 1,
                 "evidence": {"joins": len(src)}, "apply_to": {"net": net, "status": "OK"}}
        else:
            r = {"ref": req["ref"], "result": "CORRECTED", "round": 1,
                 "evidence": {"src_joins": len(src), "graph_joins": len(cur)},
                 "apply_to": {"net": net, "joins": src}}
        res.append(r)
    out_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in res), encoding="utf-8")
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["emit", "resolve"])
    ap.add_argument("args", nargs="+")
    a = ap.parse_args()
    if a.action == "emit":
        reqs = emit_requests(Path(a.args[0]), Path(a.args[1]))
        print(f"clarify emit: {len(reqs)} 条 request → {a.args[1]}")
    else:
        product, b_prep, req, out = a.args
        res = resolve(product, Path(b_prep), Path(req), Path(out))
        from collections import Counter
        print(f"clarify resolve: {len(res)} 条 → {dict(Counter(r['result'] for r in res))}")


if __name__ == "__main__":
    main()
