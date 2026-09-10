"""多 EDN 全局合并 + 信号链 — 阶段3a（v2：板级隔离 + BOM/EDN 按板配对）.

关键变更(用户确认 A1)：
  - 每块板位号独立编号，身份 = (板, 位号)；禁止按裸位号跨板合并
  - 网络亦按板隔离：key = "板::网名"
  - 跨板连续只经"板间连接器"建立（见 connectors 匹配，后续实现）
  - BOM/EDN 按板配对：A_EDN ↔ A_BOM
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

TRANSPARENT = ("R", "L", "BEAD", "FB", "FERR", "0R", "N.C.", "NC", "TP", "JMP", "JUMP")


def board_of(name: str) -> str:
    """从文件名解析板号：...-A_V00... / ...-B_V10... → 'A'/'B'；无则 'X'。"""
    m = re.search(r"-([A-Z])_V\d", name)
    return m.group(1) if m else (re.search(r"-([A-Z])_", name).group(1)
                                 if re.search(r"-([A-Z])_", name) else "X")


def _t(refdes: str) -> bool:
    s = str(refdes or "").upper()
    return any(s.startswith(p) for p in TRANSPARENT)


def load_per_file(dirp: Path) -> dict:
    files = {}
    for comp in sorted(dirp.glob("*.components.json")):
        stem = comp.name.replace(".components.json", "")
        nets = dirp / f"{stem}.nets.json"
        files[stem] = {"board": board_of(stem),
                       "components": json.loads(comp.read_text(encoding="utf-8")),
                       "nets": json.loads(nets.read_text(encoding="utf-8")) if nets.exists() else []}
    return files


def merge(files: dict) -> dict:
    comps, nets = {}, {}
    board_stats = {}
    for stem, f in files.items():
        b = f["board"]
        bs = board_stats.setdefault(b, {"components": 0, "nets": 0})
        for refdes, c in f["components"].items():
            if not refdes:
                continue
            key = f"{b}::{refdes}"                     # ★ 板级身份
            comps[key] = {"refdes": refdes, "board": b, "model": c.get("model", ""), "file": stem}
            bs["components"] += 1
        for net in f["nets"]:
            name = net["net"]
            key = f"{b}::{name}"                       # ★ 网按板隔离
            e = nets.setdefault(key, {"net": name, "board": b, "files": {}, "joins": []})
            e["files"][stem] = e["files"].get(stem, 0) + 1
            for j in net["joins"]:
                e["joins"].append({"refdes": j["refdes"], "pin": j["pin"], "board": b, "file": stem})
            bs["nets"] += 1
    return {"components": comps, "nets": nets, "board_stats": board_stats}


def build_signal_chains(merged: dict) -> list:
    nets = merged["nets"]
    term, dev = {}, {}
    for key, e in nets.items():
        b = e["board"]
        for j in e["joins"]:
            rd = j["refdes"]
            if not rd:
                continue
            term[(b, rd, j["pin"])] = e["net"]
            dev.setdefault((b, rd), {})[j["pin"]] = e["net"]
    chains, visited = [], set()
    for key, e in nets.items():
        if key in visited:
            continue
        cur_name, cur_key, b = e["net"], key, e["board"]
        chain = [{"board": b, "net": cur_name}]
        guard = 0
        while key in nets and guard < 60:
            guard += 1
            e2 = nets[key]; nxt = None
            for j in e2["joins"]:
                if _t(j["refdes"]):
                    for pin2, n2 in (dev.get((b, j["refdes"])) or {}).items():
                        if n2 != cur_name and (b, n2) not in [(c["board"], c["net"]) for c in chain]:
                            nxt = n2
                            break
                if nxt:
                    break
            if not nxt:
                break
            visited.add(key)
            chain.append({"board": b, "net": nxt}); cur_name = nxt
            key = f"{b}::{nxt}"
        visited.add(key)
        chains.append({"start": f"{b}::{chain[0]['net']}", "path": chain, "hops": len(chain) - 1,
                       "end_type": "TERMINAL" if len(chain) > 1 else "STANDALONE"})
    return chains


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input_dir"); ap.add_argument("out_dir")
    args = ap.parse_args()
    files = load_per_file(Path(args.input_dir))
    m = merge(files)
    chains = build_signal_chains(m)
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    (out / "global_components.json").write_text(json.dumps(m["components"], ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "global_nets.json").write_text(json.dumps(m["nets"], ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "signal_chains.json").write_text(json.dumps(chains, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "merge_report.json").write_text(json.dumps(
        {"files": list(files), "boards": m["board_stats"],
         "components": len(m["components"]), "nets": len(m["nets"]), "signal_chains": len(chains)},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"板: {list(m['board_stats'])} | 元件={len(m['components'])} | 网络={len(m['nets'])} | 信号链={len(chains)}")
    for b, s in m["board_stats"].items():
        print(f"  板{b}: 元件{s['components']} 网络{s['nets']}")


if __name__ == "__main__":
    main()
