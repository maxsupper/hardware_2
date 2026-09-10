"""反向验证 — 阶段1b 产物 D.

校验"无遗留 / 无错位 / 无重复", 通过标准: missing=0 且 misplace=0 且 dup_source=0。
用法: python -m scripts.prepare_rules.reverse_check
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.prepare_rules.numbering_dict import DERIVE_DIR


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", default=str(DERIVE_DIR / "raw_inventory.json"))
    ap.add_argument("--mapping", default=str(DERIVE_DIR / "mapping.json"))
    ap.add_argument("--out", default=str(DERIVE_DIR / "reverse_check.json"))
    args = ap.parse_args()

    inv = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
    mp = json.loads(Path(args.mapping).read_text(encoding="utf-8"))
    r2c, c2r = mp["raw_to_canonical"], mp["canonical_to_raw"]

    # 构造 inventory 的原始节键集
    inv_keys = set()
    for rel, f in inv["files"].items():
        for s in f["sections"]:
            inv_keys.add((rel, s["line"]))
    # mapping 中已用 "file::Lxx" 形式
    key_of = lambda rel, ln: f"{rel}::L{ln}"

    # check1 无遗留: 每个 inventory 节都有映射
    missing = []
    for rel, ln in sorted(inv_keys):
        k = key_of(rel, ln)
        if k not in r2c:
            missing.append(k)

    # check2 无重复来源: 一个 raw 节不被多个 canonical 指向
    src_counter = {}
    dup_source = []
    for cid, info in c2r.items():
        s = info["source"]
        src_counter[s] = src_counter.get(s, 0) + 1
    for s, c in src_counter.items():
        if c > 1:
            dup_source.append({"source": s, "count": c})

    # check3 无错位: canonical→raw 溯源一致 + 双向闭合
    misplace = []
    for cid, info in c2r.items():
        s = info["source"]
        back = r2c.get(s)
        if back != cid:                      # 反查不回同一 ID = 错位
            misplace.append({"cid": cid, "source": s, "back": back})
        # 标题/行号与 inventory 一致
        rel, ln = info["source"].split("::L")
        f = inv["files"].get(rel)
        if f:
            hit = next((x for x in f["sections"] if x["line"] == int(ln)), None)
            if hit is None:
                misplace.append({"cid": cid, "why": "inventory 无此行", "source": s})
    # 遗留的 canonical 无 raw?  检查 r2c 全部能否反查（r2c 每键都会在 c2r 中，但校验一遍）
    extra = [cid for cid in c2r if cid not in {r2c[k] for k in r2c}]
    if extra:
        misplace.append({"why": "canonical 无 raw 来源", "ids": extra[:5]})

    result = {
        "schema_version": "1.0", "kind": "reverse_check",
        "checks": {
            "无遗留(missing)": {"count": len(missing), "items": missing[:10]},
            "无重复来源(dup_source)": {"count": len(dup_source), "items": dup_source[:10]},
            "无错位(misplace)": {"count": len(misplace), "items": misplace[:10]},
        },
        "stats": {"raw_sections": len(inv_keys), "mapped": len(c2r),
                  "r2c_keys": len(r2c)},
        "pass": len(missing) == 0 and len(dup_source) == 0 and len(misplace) == 0,
    }
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已写: {args.out}")
    print(f"raw节={result['stats']['raw_sections']} canonical={result['stats']['mapped']} r2c={len(r2c)}")
    for name, c in result["checks"].items():
        print(f"  {name}: {c['count']}" + ("" if c["count"] == 0 else f" -> {c['items'][:2]}"))
    print("最终:", "PASS ✅ (遗留=0 错位=0)" if result["pass"] else "FAIL ❌")


if __name__ == "__main__":
    main()
