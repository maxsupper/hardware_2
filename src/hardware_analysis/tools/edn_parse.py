"""EDN 解析器 — EDIF 2.0.0 s-表达式 真实语法解析（OrCAD/Capture 导出）。

阶段3a 产物 A. 确定性工具，只读网表；产出 per-file components/nets 结构化 JSON。
后续: 多文件全局合并 + 信号链（3a 下一刀）。
用法: python -m hardware_analysis.tools.edn_parse <file.edn> [out_dir]
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # src/

HEADER = re.compile(r"\(edif\s+[^\s]+")


def sexpr_tokenize(text: str) -> list[str]:
    """s-表达式分词：括号/空白/带引号字符串。"""
    toks, i, n = [], 0, len(text)
    in_str = False
    buf = []
    while i < n:
        c = text[i]
        if c == '"':
            in_str = not in_str
            buf.append(c)
            i += 1
            continue
        if in_str:
            buf.append(c)
            i += 1
            continue
        if c in "()":
            if buf:
                toks.append("".join(buf)); buf = []
            toks.append(c)
            i += 1
            continue
        if c.isspace():
            if buf:
                toks.append("".join(buf)); buf = []
        else:
            buf.append(c)
        i += 1
    if buf:
        toks.append("".join(buf))
    return toks


def _parse(toks: list[str], pos: int, out: list):
    """递归构建嵌套树（list）：列表 = ['('elements...')']。"""
    while pos < len(toks):
        t = toks[pos]
        if t == "(":
            sub = []
            pos = _parse(toks, pos + 1, sub)
            out.append(sub)
        elif t == ")":
            return pos + 1
        else:
            out.append(t)
            pos += 1
    return pos


def parse_tree(toks: list[str]) -> list:
    out = []
    _parse(toks, 0, out)
    return out


def _first_field(node) -> str:
    """s-表达式首字段（结点名）。"""
    return str(node[0]) if isinstance(node, list) and node else ""


def walk(trees: list, name: str, acc: list):
    for t in trees:
        if isinstance(t, list) and t:
            if _first_field(t) == name:
                acc.append(t)
            walk(t[1:], name, acc)


def _first_leaf(node) -> str:
    """取嵌套结构里第一个字符串叶子（处理如 ['PWRCTRL3'] 的列表引脚名）。"""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        for it in node:
            v = _first_leaf(it)
            if v:
                return v
    return ""


def extract(file_text: str) -> dict:
    toks = sexpr_tokenize(file_text)
    tree = parse_tree(toks)
    # 定位 design 或 library 下的 (contents ...)
    instances, nets = [], []
    walk(tree, "instance", instances)
    walk(tree, "net", nets)

    comps = {}
    for inst in instances:
        # (instance REFDES (viewRef NetlistView (cellType generic))
        #           (cellRef NAME (libraryRef LIB)))
        refdes = _first_leaf(inst[1]) if len(inst) > 1 else ""
        name = ""
        for sub in inst[2:]:
            if isinstance(sub, list) and _first_field(sub) == "cellRef" and len(sub) > 1:
                name = _first_leaf(sub[1])
        comps[refdes] = {"refdes": refdes, "model": name, "cell": ""}

    net_list = []
    for net in nets:
        # (net NAME (joined (portRef PIN (instanceRef REFDES)) ...))
        netname = _first_leaf(net[1]) if len(net) > 1 else ""
        joined = []
        for sub in net[2:]:
            if isinstance(sub, list) and _first_field(sub) == "joined":
                for pr in sub[1:]:
                    if isinstance(pr, list) and _first_field(pr) == "portRef":
                        pin = _first_leaf(pr[1]) if len(pr) > 1 else ""
                        refdes = ""
                        for j in pr[2:]:
                            if isinstance(j, list) and _first_field(j) == "instanceRef" and len(j) > 1:
                                refdes = _first_leaf(j[1])
                        joined.append({"refdes": refdes, "pin": pin})
        net_list.append({"net": netname, "joins": joined})

    return {
        "components": {r: c for r, c in comps.items() if r},
        "nets": net_list,
        "stats": {"components": len(comps), "nets": len(net_list),
                  "net_joins": sum(len(x["joins"]) for x in net_list)},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="EDIF 2.0.0 网表解析（每个文件产出 components.json/nets.json）")
    ap.add_argument("edn", help="EDN 文件路径")
    ap.add_argument("--out", default=None, help="输出目录（默认同文件目录）")
    args = ap.parse_args()

    text = Path(args.edn).read_bytes().decode("utf-8", errors="replace")
    r = extract(text)
    outdir = Path(args.out) if args.out else Path(args.edn).parent
    outdir.mkdir(parents=True, exist_ok=True)
    stem = Path(args.edn).stem
    (outdir / f"{stem}.components.json").write_text(json.dumps(r["components"], ensure_ascii=False, indent=1), encoding="utf-8")
    (outdir / f"{stem}.nets.json").write_text(json.dumps(r["nets"], ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{Path(args.edn).name}: 元件={r['stats']['components']} net={r['stats']['nets']} 引脚连接={r['stats']['net_joins']}")
    print(f"写出: {outdir}/{stem}.{{components,nets}}.json")


if __name__ == "__main__":
    main()
