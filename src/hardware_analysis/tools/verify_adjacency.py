"""verify_adjacency — NG-006 等值证据工具（PH-2 自检项）.

证明「单一真源派生邻接」与旧 `links[].upstream/downstream` **逐条等价**：
  - 输入：新 netlist_graph.json（v3.0，无内嵌邻接）+ 基准文件（旧 upstream/downstream 的摘要）
  - 基准生成：`--make-baseline`（从旧版 netlist_graph.json 抽取 side/fanout/邻居集合哈希）
  - 校验：对每个 (board, refdes, pin) 重建 upstream/downstream，与基准比对邻居集合哈希 + side + fanout

用法:
  python -m hardware_analysis.tools.verify_adjacency --make-baseline <old_graph.json> -o <baseline.json>
  python -m hardware_analysis.tools.verify_adjacency --graph <new_graph.json> --baseline <baseline.json>
退出码 0=等价, 1=不等价。
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hardware_analysis.tools.netlist_graph import GraphIndex


def _h(items) -> str:
    ks = sorted(f"{x['refdes']}.{x['pin']}" if isinstance(x, dict) else str(x) for x in items)
    return hashlib.sha1("|".join(ks).encode()).hexdigest()


def make_baseline(old_graph: Path, out: Path) -> dict:
    g = json.loads(old_graph.read_text(encoding="utf-8"))
    base = {}
    for d in g.get("devices", []):
        b, rd = d.get("board", ""), d.get("refdes", "")
        for lk in d.get("links", []):
            up, dn = lk.get("upstream", []), lk.get("downstream", [])
            base[f"{b}::{rd}.{lk.get('pin')}"] = {
                "side": lk.get("side"),
                "fanout": len(set(f"{x.get('refdes')}.{x.get('pin')}" for x in up + dn)),
                "h_up": _h(up), "h_down": _h(dn),
                "n_up": len(up), "n_down": len(dn)}
    out.write_text(json.dumps(base, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return base


def verify(graph: Path, baseline: Path) -> dict:
    doc = json.loads(graph.read_text(encoding="utf-8"))
    base = json.loads(baseline.read_text(encoding="utf-8"))
    gi = GraphIndex(doc)
    mism, missing, checked = [], [], 0
    for key, exp in base.items():
        b, _, rest = key.partition("::")
        rd, _, pin = rest.partition(".")        # 位号无点；脚名可能含点→按首个点切分
        side = exp["side"]
        nb = gi.neighbors(b, rd, pin)
        up = nb if side in ("down", "bi", "pwr") else []
        dn = nb if side in ("up", "thru") else []
        if not nb and (exp["n_up"] or exp["n_down"]):
            missing.append(key)
        ok = (_h(up) == exp["h_up"] and _h(dn) == exp["h_down"]
              and len(set(f"{x['refdes']}.{x['pin']}" for x in up + dn)) == exp["fanout"])
        if not ok:
            mism.append({"key": key, "exp": {"h_up": exp["h_up"], "h_down": exp["h_down"], "fanout": exp["fanout"]},
                         "got": {"h_up": _h(up), "h_down": _h(dn), "fanout": len(nb)}})
        checked += 1
    return {"checked": checked, "mismatch": len(mism), "missing": len(missing),
            "sample_mismatch": mism[:5], "sample_missing": missing[:5],
            "status": "EQUIVALENT" if not mism and not missing else "DIFFERENT"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph")
    ap.add_argument("--baseline")
    ap.add_argument("--make-baseline", dest="mk")
    ap.add_argument("-o", "--out", default="docs/evidence/adjacency_baseline.json")
    a = ap.parse_args()
    if a.mk:
        b = make_baseline(Path(a.mk), Path(a.out))
        s = sum(v["n_up"] + v["n_down"] for v in b.values())
        print(f"基准已生成: {a.out} | 引脚={len(b):,} 邻接条目={s:,}")
        return
    r = verify(Path(a.graph), Path(a.baseline))
    print(f"邻接等值校验: {r['status']} | 比对={r['checked']:,} 不等={r['mismatch']} 缺失={r['missing']}")
    if r["mismatch"] or r["missing"]:
        print("  样例不等:", json.dumps(r["sample_mismatch"], ensure_ascii=False)[:300])
        print("  样例缺失:", r["sample_missing"][:5])
    sys.exit(0 if r["status"] == "EQUIVALENT" else 1)


if __name__ == "__main__":
    main()
