"""D2 子图打包器 — 阶段3b（确定性；hw_analyze 补盲 与 hw_master 故障判定 共用）.

以目标器件为中心，按"引脚↔网络↔相邻器件引脚"外扩到深度2：
  D0=器件所有引脚；D1=引脚所挂网络；D2=网络上的相邻器件引脚。
产出结构化 JSON 数据包（含 boundary 声明），供 LLM 判功能/定位。
用法: python -m hardware_analysis.tools.subgraph_extractor <PH-2_网表解析_dir> <refdes> [--out d2.json]
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def build(global_nets: dict, target: str, depth: int = 2) -> dict:
    # pin -> net
    pin2net, comps = {}, {}
    nets_of = {}
    for nname, e in global_nets.items():
        joins = e.get("joins", [])
        nets_of[nname] = [{"refdes": j.get("refdes", ""), "pin": j.get("pin", ""), "file": j.get("file", "")}
                          for j in joins]
        for j in joins:
            rd, pn = j.get("refdes", ""), j.get("pin", "")
            pin2net.setdefault((rd, pn), []).append(nname)
            comps.setdefault(rd, set()).add(pn)

    if target not in comps:
        return {"target": target, "error": f"未在图中找到 {target}", "depth": depth}

    # D1: 目标器件所有引脚的网络
    d0_pins = comps[target]
    d1_nets = set()
    for pn in d0_pins:
        d1_nets.update(pin2net.get((target, pn), []))
    # D2: 这些网络上的相邻器件引脚
    neighbors = {}
    relevant_nets = {}
    for nname in sorted(d1_nets):
        attaches = nets_of[nname]
        own = [a for a in attaches if a["refdes"] == target]
        others = [a for a in attaches if a["refdes"] != target]
        relevant_nets[nname] = {"self": own, "others": others}
        for a in others:
            neighbors.setdefault(a["refdes"], []).append({"net": nname, "pin": a["pin"], "file": a["file"]})

    return {
        "schema_version": "1.0", "kind": "d2_subgraph",
        "target": target, "depth": depth,
        "boundary": f"仅 D0-D2：目标器件 + 其直接网络 + 相邻器件引脚；不含 D3 及更远",
        "d0_pins": sorted(d0_pins),
        "d1_nets": sorted(d1_nets),
        "net_neighbors": relevant_nets,
        "neighbor_components": {rd: v for rd, v in sorted(neighbors.items())},
        "stats": {"nets": len(d1_nets), "neighbor_components": len(neighbors)},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("b_prep_dir")
    ap.add_argument("refdes")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    d = Path(args.b_prep_dir)
    nets = json.loads((d / "global_nets.json").read_text(encoding="utf-8"))
    r = build(nets, args.refdes)
    out = Path(args.out) if args.out else d / f"d2_{args.refdes}.json"
    out.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{args.refdes}: D1网络={r.get('stats',{}).get('nets',0)} "
          f"| 相邻器件={r.get('stats',{}).get('neighbor_components',0)}")
    if "error" in r:
        print("  ", r["error"])


if __name__ == "__main__":
    main()
