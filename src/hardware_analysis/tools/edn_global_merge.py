"""多 EDN 全局合并 + 信号链 — 阶段3a 产物 B（确定性工具）。

输入: edn_parse 产出的 per-file {stem}.components.json + {stem}.nets.json
处理:
  - 元件: 按 refdes 合并（跨文件同 refdes 不同 model → 冲突记录，不静默合并）
  - 网络: 按网名合并（两端文件都出现 → 跨板候选）；同名冲突记录
  - 信号链: 从全局图上沿"透明器件"(R/L/BEAD/0R跳线)走到终端，构建完整链路
用法: python -m hardware_analysis.tools.edn_global_merge <per-file-dir> <product_out_dir>
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

TRANSPARENT = ("R", "L", "BEAD", "FB", "FERR", "0R", "N.C.", "NC", "TP", "JMP", "JUMP")


def _is_transparent(refdes_or_model: str) -> bool:
    s = (refdes_or_model or "").upper()
    return any(s.startswith(p) for p in TRANSPARENT)


def load_per_file(dirp: Path) -> dict:
    """读取目录下所有 {stem}.components.json / {stem}.nets.json"""
    files = {}
    for comp in sorted(dirp.glob("*.components.json")):
        stem = comp.name.replace(".components.json", "")
        nets = dirp / f"{stem}.nets.json"
        files[stem] = {
            "components": json.loads(comp.read_text(encoding="utf-8")),
            "nets": json.loads(nets.read_text(encoding="utf-8")) if nets.exists() else [],
        }
    return files


def merge(files: dict) -> dict:
    comps, comp_conflict, nets, conflicts = {}, [], {}, []
    for stem, f in files.items():
        for refdes, c in f["components"].items():
            if refdes in comps:
                m0 = comps[refdes].get("model")
                if m0 and c["model"] and m0 != c["model"]:
                    comp_conflict.append({"refdes": refdes, "model_A": m0, "model_B": c["model"], "file_B": stem})
                    continue  # 冲突不合并
                comps[refdes].setdefault("files", []).append(stem)
            else:
                comps[refdes] = {"refdes": refdes, "model": c["model"], "files": [stem]}
        for net in f["nets"]:
            name, joins = net["net"], net["joins"]
            entry = nets.setdefault(name, {"net": name, "files": {}, "joins": []})
            entry["files"][stem] = entry["files"].get(stem, 0) + 1
            for j in joins:
                entry["joins"].append({"refdes": j["refdes"], "pin": j["pin"], "file": stem,
                                       "src": f"{stem}/{j['refdes']}.{j['pin']}"})

    # 跨板候选：一个网名出现在 >=2 个文件
    cross = {n: v for n, v in nets.items() if len(v["files"]) >= 2}
    return {
        "components": comps,
        "nets": nets,
        "cross_board_nets": cross,
        "component_conflicts": comp_conflict,
    }


def build_signal_chains(merged: dict) -> dict:
    """跨越透明器件构建端到端信号链（按 net→透明器件→net 走）。"""
    nets = merged["nets"]
    # 确定每个透明器件的两个端子所在 net（由 joins 反查）
    term = {}  # (refdes,pin) -> netname
    for nname, e in nets.items():
        for j in e["joins"]:
            rd, pn = str(j.get("refdes")), str(j.get("pin"))
            if rd and pn:
                term[(rd, pn)] = nname

    from collections import defaultdict
    dev = defaultdict(dict)   # refdes -> {pin: netname}
    for (refdes, pin), nname in term.items():
        dev[refdes][pin] = nname

    # 透明器件: 取某引脚 net，沿该器件另一端 net 继续
    visited_nets, chains = set(), []
    for start_name in nets:
        if start_name in visited_nets:
            continue
        if _is_transparent(start_name):
            continue
        chain = [start_name]
        cur = start_name
        # 找下一跳：当前 net 上第一个"透明器件"的另一个端子
        guard = 0
        while cur in nets and guard < 50:
            guard += 1
            nxt = None
            for j in nets[cur]["joins"]:
                if _is_transparent(j["refdes"]):
                    other = nxt if False else None
                    for pin2, n2 in dev.get(j["refdes"], {}).items():
                        if n2 != cur and n2 not in visited_nets:
                            nxt = n2
                            break
                if nxt:
                    break
            if not nxt:
                break
            visited_nets.add(cur)
            cur = nxt
            chain.append(cur)
        visited_nets.add(cur)
        chains.append({"start": start_name, "path": chain})
    return chains


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input_dir", help="含 per-file *.components.json/*.nets.json 的目录")
    ap.add_argument("out_dir", help="写 global_components/global_nets/cross_board/signal_chains 的目录")
    args = ap.parse_args()

    files = load_per_file(Path(args.input_dir))
    m = merge(files)
    chains = build_signal_chains(m)
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    (out / "global_components.json").write_text(json.dumps(m["components"], ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "global_nets.json").write_text(json.dumps(m["nets"], ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "cross_board_nets.json").write_text(json.dumps(m["cross_board_nets"], ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "signal_chains.json").write_text(json.dumps(chains, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "merge_report.json").write_text(json.dumps(
        {"files": list(files), "components": len(m["components"]),
         "nets": len(m["nets"]), "cross_board": len(m["cross_board_nets"]),
         "component_conflicts": m["component_conflicts"], "signal_chains": len(chains)},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"文件={list(files)} | 元件={len(m['components'])} | 全局net={len(m['nets'])} "
          f"| 跨板={len(m['cross_board_nets'])} | 冲突={len(m['component_conflicts'])} | 信号链={len(chains)}")


if __name__ == "__main__":
    main()
