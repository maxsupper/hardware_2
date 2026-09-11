"""P3-B md→json 转换引擎 — raw/raw_rules/*.md → rules/common/*.json。

用法：
    cd <project_root>
    PYTHONPATH=src .venv/bin/python scripts/prepare_rules/md_to_json.py [--force] [--only 名称] [--out-dir rules/common]

参数：
    --force      忽略 source_sha1 增量判定，强制重建全部产物
    --only NAME  只转换单个源（NAME 为文件名或去掉 .md 的主题名）
    --out-dir D  输出目录（默认 rules/common）
    --rules F    规则主源路径（默认 rules/rules.json）

行为（对应任务 P3-A/P3-B 的冻结契约）：
    1. 分条：以 md 的 markdown 标题（^#{1,4}\\s）为边界；title=标题文字（去 #）；
       text=标题下一行到下一个标题之前的完整原文（不摘要）。无任何标题的文件
       （如 接口电路检查规则.md）→ 全文单条，id=<前缀>-000。
    2. ID 复用：按「行号落入 rules.json 同源条目的 line..end_line」匹配 → 复用
       既有 ID；匹配不到再新发 <前缀>-<3 位序号>（序号=该前缀当前最大号+1）。
    3. 前缀映射：引脚核对=IC- / 引脚电平=LS- / 电源=PO- / 接口电路=IF- /
       引脚复用=PB- / 证据Schema=EV-（仅用于新发 ID）。
    4. stage/gate：引脚核对/引脚电平/引脚复用 -> ["PH-2","PH-3"]+G3；
       电源检查/接口电路 -> ["PH-3"]+G3；证据Schema -> ["PH-4","PH-5"]+G4。
    5. must/must_not：抽取含 ⛔/必须/禁止/不得/❌ 的句子；must_not=含禁止/不得/❌，
       其余进 must；抽不到留空数组。
    6. params：仅记录确定且不与既有规范冲突的数值参数（"最多递归 2 层" 与
       NG-011 冲突，统一取 trace_max_hops=6）；其余数值仅保留在 text。
    7. tokens_est = len(json.dumps(entries, ensure_ascii=False)) // 16 * 10。
    8. 预算护栏：单文件 tokens_est>20000 时按 ## 一级标题拆分为 <主题>.json +
       <主题>.part2.json ...
    9. 增量：目标 json 的 source_sha1 与当前源一致则跳过（打印 skipped），--force 覆盖。
   10. 产物一律过 hardware_analysis.models.rules_contracts 的 Pydantic 校验。

只读 raw/，只写 rules/common/*.json；不改 rules.json / tools.md / raw/。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from hardware_analysis.models.rules_contracts import Ref, RuleBundle, RuleEntry  # noqa: E402

RAW_RULES_DIR = ROOT / "raw" / "raw_rules"
DEFAULT_RULES_JSON = ROOT / "rules" / "rules.json"
DEFAULT_OUT_DIR = ROOT / "rules" / "common"
TOKEN_BUDGET = 20000

# ---- per-source 适配器规格（前缀 / 阶段 / 门禁 / scope） ----
SOURCE_SPECS: dict[str, dict[str, Any]] = {
    "引脚核对规则.md": {"prefix": "IC", "stage": ["PH-2", "PH-3"], "gate": "G3", "scope": "common/引脚核对"},
    "引脚电平检查方案.md": {"prefix": "LS", "stage": ["PH-2", "PH-3"], "gate": "G3", "scope": "common/引脚电平"},
    "电源检查.md": {"prefix": "PO", "stage": ["PH-3"], "gate": "G3", "scope": "common/电源检查"},
    "接口电路检查规则.md": {"prefix": "PB", "stage": ["PH-3"], "gate": "G3", "scope": "common/接口电路",
                             "chunker": "pseudo"},   # 无 markdown 标题 → 用伪标题分条（第X部分/N.M/【…】）
    "引脚复用关系检查规则.md": {"prefix": "PB", "stage": ["PH-2", "PH-3"], "gate": "G3", "scope": "common/引脚复用"},
    "证据文件Schema规范.md": {"prefix": "EV", "stage": ["PH-4", "PH-5"], "gate": "G4", "scope": "common/证据文件Schema"},
}

BOM = "\ufeff"
HEADING_RE = re.compile(r"^(#{1,4})[ \t]+(\S.*?)[ \t]*$")
# 伪标题（无 markdown 标题的文件用，如 接口电路检查规则.md）
PSEUDO_L1_RE = re.compile(r"^第[一二三四五六七八九十百]+部分[：:].*$")
PSEUDO_L2_RE = re.compile(r"^\d+\.\d+[ \t]+\S.*$")
PSEUDO_L3_RE = re.compile(r"^【[^】]+】[ \t]*$")
ID_RE = re.compile(r"^([A-Za-z][A-Za-z0-9]*)-(\d+)$")
SENT_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])")
MD_PREFIX_RE = re.compile(r"^(?:>+\s*|[-*+]\s+|\d+[.)、]\s*|#+\s*)")
SELECT_TRIGGERS = ("⛔", "必须", "禁止", "不得", "❌")
NEG_TRIGGERS = ("禁止", "不得", "❌")


# --------------------------------------------------------------------------- #
# 抽取器（must / must_not / params）
# --------------------------------------------------------------------------- #
def split_sentences(text: str) -> list[str]:
    """把正文切成句子；保留原文，去掉行首 markdown 引用/项目符号标记。"""
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        line = MD_PREFIX_RE.sub("", line).strip()
        if not line:
            continue
        for piece in SENT_SPLIT_RE.split(line):
            piece = piece.strip()
            if piece:
                out.append(piece)
    return out


def extract_must(text: str) -> tuple[list[str], list[str]]:
    """返回 (must, must_not)。只收纳命中触发词的句子，不编造。"""
    must: list[str] = []
    must_not: list[str] = []
    for sent in split_sentences(text):
        if not any(t in sent for t in SELECT_TRIGGERS):
            continue
        if any(t in sent for t in NEG_TRIGGERS):
            if sent not in must_not:
                must_not.append(sent)
        elif sent not in must:
            must.append(sent)
    return must, must_not


def extract_params(text: str) -> dict[str, Any]:
    """仅抽取确定的数值参数。递归层数以 NG-011 为准（trace_max_hops=6）。"""
    params: dict[str, Any] = {}
    low = text.lower()
    if ("递归" in text or "trace_max_hops" in low) and ("层" in text or "hop" in low):
        params["trace_max_hops"] = 6
    return params


# --------------------------------------------------------------------------- #
# 分条（chunking）
# --------------------------------------------------------------------------- #
def strip_head(text: str) -> str:
    return text[1:] if text.startswith(BOM) else text


def iter_sections(text: str, chunker: str = "md") -> list[dict[str, Any]]:
    """按 chunker 切块。返回 [{level,title,line,end_line}]（1-based 闭区间）。

    chunker="md"     : 按 markdown 标题；chunker="pseudo" : 按伪标题（第X部分/N.M/【…】）。
    两者都无命中时返回单条：title=首个非空行，覆盖全文。
    """
    lines = strip_head(text).splitlines()
    starts: list[tuple[int, int, str]] = []
    if chunker == "pseudo":
        for no, raw in enumerate(lines, 1):
            s = raw.strip()
            if PSEUDO_L1_RE.match(s):
                starts.append((no, 1, s))
            elif PSEUDO_L2_RE.match(s):
                starts.append((no, 2, s))
            elif PSEUDO_L3_RE.match(s):
                starts.append((no, 3, s))
    else:
        for no, raw in enumerate(lines, 1):
            m = HEADING_RE.match(raw)
            if m:
                title = m.group(2).rstrip("#").strip()
                starts.append((no, len(m.group(1)), title))
    if not starts:
        first = next((ln.strip() for ln in lines if ln.strip()), "")
        first = MD_PREFIX_RE.sub("", first).strip()
        return ([{"level": 0, "title": first, "line": 1, "end_line": len(lines)}]
                if lines else [])
    out: list[dict[str, Any]] = []
    for idx, (no, level, title) in enumerate(starts):
        end = starts[idx + 1][0] - 1 if idx + 1 < len(starts) else len(lines)
        out.append({"level": level, "title": title, "line": no, "end_line": end})
    return out


def section_text(lines: list[str], sec: dict[str, Any]) -> str:
    """标题块正文：标题下一行到 end_line（含）。单条(level=0)取全文。"""
    start = 0 if sec["level"] == 0 else sec["line"]
    return "\n".join(lines[start:sec["end_line"]])


# --------------------------------------------------------------------------- #
# ID 分配（复用既有 / 新发）
# --------------------------------------------------------------------------- #
def norm_source(src: str) -> str:
    """rules.json 的 source 为相对 raw/ 的路径（如 raw_rules/x.md）；
    统一规范成信封使用的 raw/raw_rules/x.md。"""
    src = src.split("::")[0]
    return src if src.startswith("raw/") else f"raw/{src}"


def load_existing(rules_path: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    rules = json.loads(rules_path.read_text(encoding="utf-8"))["rules"]
    by_src: dict[str, list[dict[str, Any]]] = {}
    prefix_max: dict[str, int] = {}
    for cid, v in rules.items():
        m = ID_RE.match(cid)
        if m:
            p, n = m.group(1), int(m.group(2))
            prefix_max[p] = max(prefix_max.get(p, 0), n)
        src = norm_source(str(v.get("source", "")))
        by_src.setdefault(src, []).append(
            {"id": cid, "line": v.get("line"), "end_line": v.get("end_line")}
        )
    return by_src, prefix_max


def match_existing(entries: list[dict[str, Any]], start: int) -> str | None:
    """按行号落入 line..end_line 区间匹配既有 ID；优先精确命中起始行。"""
    exact = [e["id"] for e in entries if e.get("line") == start]
    if exact:
        return exact[0]
    hit = [e["id"] for e in entries
           if e.get("line") is not None and e.get("end_line") is not None
           and e["line"] <= start <= e["end_line"]]
    return hit[0] if hit else None


def new_id(prefix: str, counter: dict[str, int]) -> str:
    counter[prefix] = counter.get(prefix, 0) + 1
    return f"{prefix}-{counter[prefix]:03d}"


# --------------------------------------------------------------------------- #
# 组装
# --------------------------------------------------------------------------- #
def build_entries(name: str, text: str, source: str,
                  existing_by_src: dict[str, list[dict[str, Any]]],
                  counter: dict[str, int]) -> tuple[list[RuleEntry], list[str]]:
    spec = SOURCE_SPECS[name]
    secs = iter_sections(text, spec.get("chunker", "md"))
    lines = strip_head(text).splitlines()
    existing = existing_by_src.get(source, [])
    no_heading = len(secs) == 1 and secs[0]["level"] == 0

    entries: list[RuleEntry] = []
    groups: list[str] = []          # 每条 entry 所属的 ## 分组标题（预算拆分用）
    seen: set[str] = set()
    for sec in secs:
        if no_heading:
            cid = f"{spec['prefix']}-000"
        else:
            cid = match_existing(existing, sec["line"]) or new_id(spec["prefix"], counter)
        if cid in seen:                                   # 极端撞名保护
            cid = new_id(spec["prefix"], counter)
        seen.add(cid)
        if no_heading:
            groups.append(sec["title"])
        else:
            groups.append(sec["title"] if sec["level"] <= 2 else (groups[-1] if groups else sec["title"]))
        body = section_text(lines, sec)
        must, must_not = extract_must(body)
        entries.append(RuleEntry(
            id=cid,
            title=sec["title"],
            stage=list(spec["stage"]),
            gate=spec["gate"],
            params=extract_params(body),
            must=must,
            must_not=must_not,
            text=body,
            refs=[Ref(src=source, line=sec["line"], end_line=sec["end_line"])],
        ))
    return entries, groups


def tokens_est(entries: list[dict[str, Any]]) -> int:
    return len(json.dumps(entries, ensure_ascii=False)) // 16 * 10


def pack_parts(entries: list[RuleEntry], groups: list[str], budget: int) -> list[list[RuleEntry]]:
    """按 ## 一级标题分组、整组贪心装包，保证每片 tokens_est<=budget。

    先按分组聚合，再整组加入当前片；加入后会超预算则先切下一片（单片分组
    自身超预算时如实保留并告警，不强行拆分）。
    """
    if tokens_est([e.model_dump() for e in entries]) <= budget:
        return [entries]
    buckets: list[list[RuleEntry]] = []
    cur: list[RuleEntry] = []
    cur_group: str | None = None
    for entry, group in zip(entries, groups):
        if cur and group != cur_group:
            buckets.append(cur)
            cur = []
        cur.append(entry)
        cur_group = group
    if cur:
        buckets.append(cur)

    parts: list[list[RuleEntry]] = []
    cur = []
    for bucket in buckets:
        if cur and tokens_est([e.model_dump() for e in cur + bucket]) > budget:
            parts.append(cur)
            cur = []
        cur = cur + bucket
    if cur:
        parts.append(cur)
    return parts


def write_bundle(path: Path, spec: dict[str, Any], source: str, sha1: str,
                 entries: list[RuleEntry], part_no: int, generated_at: str) -> dict[str, Any]:
    scope = spec["scope"] if part_no == 1 else f"{spec['scope']} (part{part_no})"
    bundle = RuleBundle(
        schema_version="1.0", kind="rule_bundle", scope=scope, source=source,
        source_sha1=sha1, generated_at=generated_at,
        tokens_est=tokens_est([e.model_dump() for e in entries]), entries=entries,
    )
    data = bundle.model_dump()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def convert_one(name: str, spec: dict[str, Any], args: argparse.Namespace,
                existing_by_src: dict[str, list[dict[str, Any]]],
                counter: dict[str, int]) -> dict[str, Any]:
    raw_path = RAW_RULES_DIR / name
    text = raw_path.read_text(encoding="utf-8", errors="replace")
    sha1 = hashlib.sha1(raw_path.read_bytes()).hexdigest()
    source = f"raw/raw_rules/{name}"
    stem = raw_path.stem
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    primary = out_dir / f"{stem}.json"

    if primary.exists() and not args.force:
        try:
            old = json.loads(primary.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            old = {}
        if old.get("source_sha1") == sha1:
            ids = [e.get("id") for e in old.get("entries", [])]
            print(f"skipped: {source} (sha1 unchanged) -> {primary.relative_to(ROOT)} "
                  f"entries={len(ids)} tokens_est={old.get('tokens_est')}")
            return {"name": name, "status": "skipped", "path": str(primary), "ids": ids,
                    "entries": len(ids), "tokens_est": old.get("tokens_est")}

    entries, groups = build_entries(name, text, source, existing_by_src, counter)
    parts = pack_parts(entries, groups, args.token_budget)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    # 清理历史分片，避免陈旧文件残留
    for stale in out_dir.glob(f"{stem}.part*.json"):
        stale.unlink()

    written: list[Path] = []
    all_ids: list[str] = []
    total_tokens = 0
    for i, part in enumerate(parts, 1):
        target = primary if i == 1 else out_dir / f"{stem}.part{i}.json"
        data = write_bundle(target, spec, source, sha1, part, i, generated_at)
        written.append(target)
        all_ids.extend(e.id for e in part)
        total_tokens = data["tokens_est"] if i == 1 else total_tokens
        if data["tokens_est"] > args.token_budget:
            print(f"  ! WARN {target.name}: tokens_est={data['tokens_est']} 超预算(单片不可再拆)")
    print(f"built:   {source} -> {', '.join(w.name for w in written)} "
          f"entries={len(all_ids)} tokens_est={total_tokens}")
    return {"name": name, "status": "built", "path": str(primary), "ids": all_ids,
            "entries": len(all_ids), "tokens_est": total_tokens}


def print_coverage(results: list[dict[str, Any]]) -> None:
    all_ids: list[str] = []
    print("\n== per-file ID list ==")
    for r in results:
        ids = r["ids"]
        all_ids.extend(ids)
        gaps = find_gaps(ids)
        print(f"[{r['status']:7s}] {Path(r['path']).name}: entries={r['entries']} "
              f"tokens_est={r['tokens_est']} gaps={gaps or 'none'}")
        print("    IDs: " + (", ".join(ids) if ids else "(none)"))
    dup = sorted({i for i in all_ids if all_ids.count(i) > 1})
    print(f"\n== global ID check ==\n  total={len(all_ids)} unique={len(set(all_ids))} "
          f"duplicates={dup or 'none'}")
    # 与 rules.json 既有同源 ID 覆盖对照（仅已转换源）
    rj = json.loads(Path(DEFAULT_RULES_JSON).read_text(encoding="utf-8"))["rules"]
    produced = set(all_ids)
    for r in results:
        src = f"raw/raw_rules/{r['name']}"
        old = {cid for cid, v in rj.items() if norm_source(str(v.get("source", ""))) == src}
        covered = old & produced
        missing = sorted(old - produced)
        if missing:
            print(f"  {r['name']}: produced {len(covered)}/{len(old)} existing IDs; "
                  f"uncovered={missing}")
        else:
            print(f"  {r['name']}: produced {len(covered)}/{len(old)} existing IDs; 全覆盖")


def find_gaps(ids: list[str]) -> list[str]:
    """同前缀序号是否连续（min..max 无空洞）。"""
    nums: dict[str, list[int]] = {}
    for cid in ids:
        m = ID_RE.match(cid)
        if m:
            nums.setdefault(m.group(1), []).append(int(m.group(2)))
    gaps: list[str] = []
    for prefix, ns in nums.items():
        lo, hi = min(ns), max(ns)
        for n in range(lo, hi + 1):
            if n not in ns:
                gaps.append(f"{prefix}-{n:03d}")
    return gaps


def main() -> None:
    ap = argparse.ArgumentParser(description="raw/raw_rules/*.md -> rules/common/*.json")
    ap.add_argument("--force", action="store_true", help="忽略 source_sha1 增量判定")
    ap.add_argument("--only", default=None, help="只转换单个源（文件名或主题名）")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="输出目录")
    ap.add_argument("--rules", default=str(DEFAULT_RULES_JSON), help="规则主源 rules.json")
    ap.add_argument("--token-budget", type=int, default=TOKEN_BUDGET,
                    help=f"单文件 tokens_est 预算（默认 {TOKEN_BUDGET}，超出按 ## 拆分）")
    args = ap.parse_args()

    names = list(SOURCE_SPECS)
    if args.only:
        key = args.only if args.only.endswith(".md") else f"{args.only}.md"
        if key not in SOURCE_SPECS:
            ap.error(f"--only 未知源: {args.only}；可选: {', '.join(names)}")
        names = [key]

    existing_by_src, prefix_max = load_existing(Path(args.rules))
    counter = dict(prefix_max)  # 新发 ID 从既有最大号继续
    results = [convert_one(n, SOURCE_SPECS[n], args, existing_by_src, counter) for n in names]
    print_coverage(results)


if __name__ == "__main__":
    main()
