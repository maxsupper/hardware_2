#!/usr/bin/env python3
"""platform_to_json — 平台资料 → rules/platform/<芯片>/ 统一 JSON 派生器（P3-C / P3-D）.

把**只读事实源** ``raw/raw_platmform/<芯片>/`` 派生为规则、引脚数据与索引：

  rules/platform/<芯片>/rules.json         kind=platform_rules（进 LLM；单文件 >20000 tokens 自动拆多文件）
  rules/platform/<芯片>/pinout.json        kind=pinout_table（数据，不进 LLM）
  rules/platform/<芯片>/pinout.index.json  引脚 / 功能 / 球号 → 条目下标 的 O(1) 查询索引
  rules/index.json                         kind=rules_index（common + platform + load_policy 总索引）

用法::

    PYTHONPATH=src .venv/bin/python scripts/prepare_rules/platform_to_json.py
    PYTHONPATH=src .venv/bin/python scripts/prepare_rules/platform_to_json.py --force
    PYTHONPATH=src .venv/bin/python scripts/prepare_rules/platform_to_json.py --chips RK3588,E2000

设计要点
--------
* **源逐芯片结构不同**：md 格式不作统一要求，本脚本按每个芯片的实际结构写适配器：
  - RK3588 / RK3576 / RV1126B：标准 markdown，按 ``##`` / ``###`` 标题切条；
  - E2000：``数据手册.md`` 是 PDF 文本转储（几乎无 markdown 标题），用专门的编号标题探测器
    （``^\\d+(\\.\\d+)*\\s+标题`` 且过滤表格量词行 / TOC 点线行 / 页码页眉重复），并按一级章节分文件。
* **统一信封**（冻结，不得改动）::

      {"schema_version":"1.0","kind":"platform_rules|pinout_table",
       "scope":"platform/<芯片>","source":"raw/...","source_sha1":"<sha1>",
       "generated_at":"<ISO8601>","tokens_est":N,"entries":[...]}

* **规则条目**：``{"id","title","stage","gate","params","must","must_not","text","refs"}``，
  ID 前缀统一 ``PF-<芯片代号>-<3 位序号>``； ``stage`` 默认 ``["PH-2","PH-3"]``，``gate`` 默认 ``"G3"``。
* **引脚条目**：``{"pin","ball","functions","type","power_domain","voltage","mux","notes"}``，
  缺失字段留空串 / 空数组，绝不编造；原 ``meta`` 保留并补 ``source_sha1`` / ``generated_at``。
* **tokens_est** = ``int(len(text) / 1.6)``（本仓库约定；RK3588 整文件 = 7430）。
* **预算护栏** ``BUDGET_TOKENS = 20000``：单芯片规则超限则按标题层级拆分为 ``rules_NN.json``。
* **source_sha1 增量**：源未变且内容一致 → ``skipped``（幂等）； ``--force`` 强制重写。
* **只用标准库**。若 ``src/hardware_analysis/models/rules_contracts.py`` 存在则额外做契约校验；
  否则回退到本地轻量校验函数（本脚本不创建 / 不修改该契约文件，避免与其它 agent 冲突）。
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# --------------------------------------------------------------------------- #
# 路径 / 常量
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = ROOT / "raw" / "raw_platmform"          # 注意：平台目录名就是 raw_platmform（拼写如此）
RULES_ROOT = ROOT / "rules"
PLATFORM_ROOT = RULES_ROOT / "platform"
INDEX_JSON = RULES_ROOT / "index.json"

SCHEMA_VERSION = "1.0"
BUDGET_TOKENS = 20000
TOKEN_DIVISOR = 1.6  # tokens_est = int(chars / 1.6)

DEFAULT_STAGE = ["PH-2", "PH-3"]
DEFAULT_GATE = "G3"

# 芯片 → 适配器配置。md_adapter ∈ {markdown, e2000_datasheet}
CHIPS: dict[str, dict] = {
    "RK3588": {
        "code": "RK3588",
        "md": "RK3588/hardware_check.md",
        "pinout": "RK3588/pinout.json",
        "md_adapter": "markdown",
    },
    "RK3576": {
        "code": "RK3576",
        "md": "RK3576/hardware_check.md",
        "pinout": "RK3576/pinout.json",
        "md_adapter": "markdown",
    },
    "RV1126B": {
        "code": "RV1126B",
        "md": "RV1126B/hardware_check.md",
        "pinout": "RV1126B/pinout.json",
        "md_adapter": "markdown",
    },
    "E2000": {
        "code": "E2000",
        "md": "E2000/数据手册.md",
        "pinout": "E2000/pinout.json",
        "md_adapter": "e2000_datasheet",
    },
}

# common 主题（另一 agent 正在生成 rules/common/*.json；此处按预期文件名登记，缺失不报错）
COMMON_TOPICS: list[tuple[str, list[str]]] = [
    ("引脚核对", ["PH-2", "PH-3"]),
    ("引脚电平检查", ["PH-3"]),
    ("电源检查", ["PH-3"]),
    ("接口电路检查", ["PH-3"]),
    ("引脚复用关系", ["PH-3"]),
    ("证据schema", ["PH-2", "PH-3"]),
]

LOAD_POLICY = {
    "PH-2": {"common": ["引脚核对"], "platform_rules": True, "pinout": False},
    "PH-3": {
        "common": ["引脚核对", "引脚电平检查", "电源检查", "接口电路检查", "引脚复用关系"],
        "platform_rules": True,
        "pinout": "on_demand",
    },
}


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #
def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def sha1_bytes(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()


def est_tokens(text: str) -> int:
    """tokens 估算（仓库约定）：int(len(text)/1.6)。"""
    return int(len(text) / TOKEN_DIVISOR)


def _strip_generated(d):
    """递归去掉易变字段 generated_at，用于幂等内容比较。"""
    if isinstance(d, dict):
        return {k: _strip_generated(v) for k, v in d.items() if k != "generated_at"}
    if isinstance(d, list):
        return [_strip_generated(x) for x in d]
    return d


def write_json_idempotent(path: Path, payload: dict, force: bool = False) -> bool:
    """写 JSON；内容（忽略 generated_at）与旧文件一致时跳过。返回 True=已写，False=跳过。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            if json.dumps(_strip_generated(old), ensure_ascii=False, sort_keys=True) == \
               json.dumps(_strip_generated(payload), ensure_ascii=False, sort_keys=True):
                return False
        except Exception:
            pass
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return True


# --------------------------------------------------------------------------- #
# 轻量本地校验（Pydantic 契约存在时优先用契约）
# --------------------------------------------------------------------------- #
FROZEN_ENVELOPE_KEYS = ("schema_version", "kind", "scope", "source",
                        "source_sha1", "generated_at", "tokens_est", "entries")
FROZEN_RULE_KEYS = ("id", "title", "stage", "gate", "params", "must", "must_not", "text", "refs")
FROZEN_PIN_KEYS = ("pin", "ball", "functions", "type", "power_domain", "voltage", "mux", "notes")


def validate_local(doc: dict) -> None:
    """冻结格式的轻量校验；不通过即抛 ValueError。"""
    for k in FROZEN_ENVELOPE_KEYS:
        if k not in doc:
            raise ValueError(f"信封缺字段 {k}")
    if doc["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"schema_version 必须 {SCHEMA_VERSION}")
    if doc["kind"] not in ("platform_rules", "pinout_table"):
        raise ValueError(f"未知 kind {doc['kind']}")
    if not isinstance(doc["entries"], list):
        raise ValueError("entries 必须是数组")
    if doc["kind"] == "platform_rules":
        for e in doc["entries"]:
            for k in FROZEN_RULE_KEYS:
                if k not in e:
                    raise ValueError(f"规则条目缺字段 {k}: {e.get('id')}")
            if not re.fullmatch(r"PF-[A-Za-z0-9]+-\d{3}", e["id"]):
                raise ValueError(f"规则 ID 不合规: {e['id']}")
    else:
        for e in doc["entries"]:
            for k in FROZEN_PIN_KEYS:
                if k not in e:
                    raise ValueError(f"引脚条目缺字段 {k}")


def try_contract_validate(doc: dict) -> str:
    """若 rules_contracts.py 存在则尝试契约校验；返回采用的方式名。

    契约文件由其它 agent 并行维护，其 API 可能变化；因此任何异常（含签名不符）都回退到本地轻校验，
    保证本脚本不会被并行开发中断。
    """
    try:
        import importlib
        sys.path.insert(0, str(ROOT / "src"))
        m = importlib.import_module("hardware_analysis.models.rules_contracts")
        used = "local"
        for attr in ("validate_document", "validate_envelope", "validate", "check"):
            fn = getattr(m, attr, None)
            if callable(fn):
                fn(doc)
                used = f"rules_contracts.{attr}"
                break
        else:
            kind = doc.get("kind")
            model_name = {"platform_rules": "RuleBundle", "pinout_table": "PinoutBundle"}.get(kind)
            model = getattr(m, model_name, None) if model_name else None
            if model is not None:
                model.model_validate(doc)
                used = f"rules_contracts.{model_name}"
        validate_local(doc)
        return used
    except ModuleNotFoundError:
        pass
    except Exception as exc:  # 并行开发的契约 API 不稳 / 不覆盖该 kind → 回退本地校验
        print(f"  [warn] rules_contracts 不可用({exc.__class__.__name__}: {exc})，回退本地校验")
    validate_local(doc)
    return "local"


# --------------------------------------------------------------------------- #
# 规则切条：标准 markdown
# --------------------------------------------------------------------------- #
def _flat_sections(headings: list[tuple[int, str, str]]) -> list[dict]:
    """把 (level,title,行号) 列表转成**连续不重叠**的块：text 从标题行到下一个被切标题前。

    说明：本仓库文档切条采用 contiguous（连续）语义 —— 每块到下一个命中标题（任意层级）为止，
    避免父标题重复包含子标题正文导致注入 token 翻倍（RK3588 与示例 tokens_est=7430 吻合）。
    """
    blocks = []
    for i, (level, title, line) in enumerate(headings):
        end = headings[i + 1][2] - 1 if i + 1 < len(headings) else None
        blocks.append({"level": level, "title": title, "line": line, "end_line": end})
    return blocks


def adapter_markdown(text: str) -> tuple[list[dict], list[str]]:
    """标准 markdown 适配器：按 ``##`` / ``###`` 标题切条（``####`` 及其以下不切）。"""
    lines = text.split("\n")
    headings: list[tuple[int, str, str]] = []
    for i, raw in enumerate(lines, start=1):
        m = re.match(r"^(#{2,3})\s+(.*?)\s*$", raw)
        if m:
            headings.append((len(m.group(1)), m.group(2).strip(), i))
    return _flat_sections(headings), lines


# --------------------------------------------------------------------------- #
# 规则切条：E2000 PDF 文本手册适配器
# --------------------------------------------------------------------------- #
_E2000_BAD_AFTER_NUM = re.compile(
    r"^\d+\s*(个|位|路|种|块|颗|条|次|章|页|年|月|日|"
    r"G|M|K|V|W|A|mA|bit|bits|x\d|X\d|瓦|毫|微|纳|欧|赫|伏|安)"
)


def _e2000_heading(raw: str):
    """探测 E2000 PDF 文本中的编号标题；返回 (level, title) 或 None。"""
    s = raw.strip()
    if not s or "...." in s:                       # 排除目录点线行
        return None
    m = re.match(r"^(\d{1,2}(?:\.\d{1,3}){0,3})\s+(\S.*)$", s)
    if not m:
        return None
    if len(s) > 55 or s[-1] in "。；，、：":            # 排除长句 / 表格句子
        return None
    num = m.group(1)
    if "." not in num:                              # 一级章节
        if not (1 <= int(num) <= 20):
            return None
        if _E2000_BAD_AFTER_NUM.match(s) or len(s) > 22:
            return None
    return num.count("."), s


def adapter_e2000_datasheet(text: str) -> tuple[list[dict], list[str]]:
    """E2000 ``数据手册.md`` 适配器（PDF 文本转储，无 markdown 标题）。

    探测器按真实结构识别 ``编号 标题`` 行；页眉重复的一级章节标题按精确同名去重（只保留首现）。
    版本历史 / 目录（点线行）位于正文之前，按最后一个 TOC 点线行之后起算，避免把版本历史里的
    ``2.4 ...`` 误判为正文标题并吞掉整个目录。
    """
    lines = text.split("\n")
    dotted = [i for i, l in enumerate(lines) if "...." in l]     # 0-based
    body_start = (max(dotted) + 2) if dotted else 1               # 1-based 正文起始行
    headings: list[tuple[int, str, str]] = []
    seen_titles: set[str] = set()
    for i, raw in enumerate(lines, start=1):
        if i < body_start:
            continue
        hit = _e2000_heading(raw)
        if not hit:
            continue
        level, title = hit
        if title in seen_titles:                    # 页眉在每页重复出现 → 去重
            continue
        seen_titles.add(title)
        headings.append((level, title, i))
    return _flat_sections(headings), lines


MD_ADAPTERS = {
    "markdown": adapter_markdown,
    "e2000_datasheet": adapter_e2000_datasheet,
}


# --------------------------------------------------------------------------- #
# must / must_not 抽取
# --------------------------------------------------------------------------- #
_SENT_SPLIT = re.compile(r"(?<=[。！？；\n])")


def extract_must(text: str) -> tuple[list[str], list[str]]:
    must, must_not = [], []
    for seg in _SENT_SPLIT.split(text):
        s = seg.strip().strip("|").strip()
        if not s:
            continue
        if "必须" in s and s not in must:
            must.append(s)
        if ("禁止" in s or "不得" in s or "⛔" in s) and s not in must_not:
            must_not.append(s)
    return must, must_not


# --------------------------------------------------------------------------- #
# 规则 → 多文件打包（预算护栏）
# --------------------------------------------------------------------------- #
def build_rule_entries(blocks: list[dict], lines: list[str], source_rel: str) -> list[dict]:
    entries = []
    for b in blocks:
        start = b["line"]
        end = b["end_line"] if b["end_line"] is not None else len(lines)
        text = "\n".join(lines[start - 1:end])
        must, must_not = extract_must(text)
        entries.append({
            "title": b["title"],
            "stage": list(DEFAULT_STAGE),
            "gate": DEFAULT_GATE,
            "params": {},
            "must": must,
            "must_not": must_not,
            "text": text,
            "refs": [{"src": source_rel, "line": start, "end_line": end}],
            "_level": b["level"],
            "_line": start,
            "_end_line": end,
        })
    return entries


def pack_rule_parts(entries: list[dict], lines: list[str]) -> list[list[dict]]:
    """按 tokens 预算把规则条目打包成若干文件；<=预算时单文件，超限时按标题顺序切分。"""
    if not entries:
        return [[]]
    total = est_tokens("\n".join(lines))
    if total <= BUDGET_TOKENS:
        return [entries]
    parts: list[list[dict]] = []
    cur: list[dict] = []
    cur_chars = 0
    for e in entries:
        span_chars = len("\n".join(lines[e["_line"] - 1:e["_end_line"]]))
        if cur and int((cur_chars + span_chars) / TOKEN_DIVISOR) > BUDGET_TOKENS:
            parts.append(cur)
            cur, cur_chars = [], 0
        cur.append(e)
        cur_chars += span_chars
    if cur:
        parts.append(cur)
    return parts


# --------------------------------------------------------------------------- #
# 构建 rules 产物
# --------------------------------------------------------------------------- #
def build_rules_files(chip: str, cfg: dict, force: bool) -> tuple[list[str], int]:
    """生成 rules/platform/<chip>/rules*.json；返回 (相对文件列表, 规则总 tokens_est)。"""
    md_path = RAW_ROOT / cfg["md"]
    raw_bytes = md_path.read_bytes()
    text = raw_bytes.decode("utf-8")
    sha = sha1_bytes(raw_bytes)
    source_rel = f"raw/raw_platmform/{cfg['md']}"

    blocks, lines = MD_ADAPTERS[cfg["md_adapter"]](text)
    entries = build_rule_entries(blocks, lines, source_rel)
    parts = pack_rule_parts(entries, lines)

    out_dir = PLATFORM_ROOT / chip
    out_dir.mkdir(parents=True, exist_ok=True)
    single = len(parts) == 1
    desired_names: list[str] = []
    total_tokens = 0
    seq = 0
    for pi, part in enumerate(parts):
        name = "rules.json" if single else f"rules_{pi + 1:02d}.json"
        desired_names.append(name)
        if single:
            tokens = est_tokens(text)
        else:
            span = lines[part[0]["_line"] - 1:part[-1]["_end_line"]]
            tokens = est_tokens("\n".join(span))
        total_tokens += tokens
        out_entries = []
        for e in part:
            seq += 1
            e2 = {k: copy.deepcopy(v) for k, v in e.items() if not k.startswith("_")}
            e2["id"] = f"PF-{cfg['code']}-{seq:03d}"
            # 冻结字段顺序
            out_entries.append({
                "id": e2["id"], "title": e2["title"], "stage": e2["stage"], "gate": e2["gate"],
                "params": e2["params"], "must": e2["must"], "must_not": e2["must_not"],
                "text": e2["text"], "refs": e2["refs"],
            })
        doc = {
            "schema_version": SCHEMA_VERSION,
            "kind": "platform_rules",
            "scope": f"platform/{chip}",
            "source": source_rel,
            "source_sha1": sha,
            "generated_at": _now_iso(),
            "tokens_est": tokens,
            "entries": out_entries,
        }
        how = try_contract_validate(doc)
        p = out_dir / name
        wrote = write_json_idempotent(p, doc, force=force)
        print(f"  [rules] {p.relative_to(ROOT)}  entries={len(out_entries)} tokens_est={tokens} "
              f"{'WRITE' if wrote else 'SKIP'} (validate={how})")

    # 清理旧的多文件分片（源结构变化时避免残留）
    for old in out_dir.glob("rules*.json"):
        if old.name not in desired_names:
            old.unlink()
            print(f"  [rules] 删除陈旧分片 {old.relative_to(ROOT)}")

    rels = [f"platform/{chip}/{n}" for n in desired_names]
    return rels, total_tokens


# --------------------------------------------------------------------------- #
# 构建 pinout 产物 + 索引
# --------------------------------------------------------------------------- #
_PIN_KNOWN_KEYS = {"ball", "gpio", "domain", "io_type", "pull", "pull_config",
                   "schmitt", "interruptable", "functions", "default_function", "notes"}


def normalize_pin(key: str, v: dict) -> dict:
    """源引脚记录 → 冻结引脚条目（缺失字段留空串 / 空数组，不编造）。"""
    pin = key[2:] if key.startswith("__") else key
    funcs_obj = v.get("functions") or {}
    funcs = [funcs_obj[k] for k in sorted(funcs_obj)] if isinstance(funcs_obj, dict) else list(funcs_obj)

    notes_parts: list[str] = []
    if v.get("notes"):
        notes_parts.append(str(v["notes"]))
    for k in ("pull", "pull_config", "schmitt", "interruptable", "gpio"):
        if k in v and v[k] not in (None, "", False):
            notes_parts.append(f"{k}={v[k]}")
    for k, val in v.items():
        if k not in _PIN_KNOWN_KEYS and val not in (None, "", False):
            notes_parts.append(f"{k}={val}")

    return {
        "pin": pin,
        "ball": v.get("ball", "") or "",
        "functions": funcs,
        "type": v.get("io_type", "") or "",
        "power_domain": v.get("domain", "") or "",
        "voltage": v.get("voltage", "") or "",
        "mux": v.get("default_function") or "",
        "notes": "; ".join(notes_parts),
    }


def build_pinout_files(chip: str, cfg: dict, force: bool) -> tuple[int, int]:
    """生成 pinout.json + pinout.index.json；返回 (tokens_est, 引脚条目数)。"""
    src_path = RAW_ROOT / cfg["pinout"]
    raw_bytes = src_path.read_bytes()
    src = json.loads(raw_bytes.decode("utf-8"))
    sha = sha1_bytes(raw_bytes)
    source_rel = f"raw/raw_platmform/{cfg['pinout']}"
    now = _now_iso()

    pins = src.get("pins", {}) or {}
    entries = [normalize_pin(k, v) for k, v in pins.items()]

    # meta：原样保留 + 补 source_sha1 / generated_at
    meta = dict(src.get("meta", {}))
    meta["source_sha1"] = sha
    meta["generated_at"] = now

    doc = {
        "schema_version": SCHEMA_VERSION,
        "kind": "pinout_table",
        "scope": f"platform/{chip}",
        "source": source_rel,
        "source_sha1": sha,
        "generated_at": now,
        "tokens_est": est_tokens(raw_bytes.decode("utf-8")),
        "meta": meta,
        "entries": entries,
    }
    how = try_contract_validate(doc)
    p = PLATFORM_ROOT / chip / "pinout.json"
    wrote = write_json_idempotent(p, doc, force=force)
    print(f"  [pinout] {p.relative_to(ROOT)}  entries={len(entries)} "
          f"tokens_est={doc['tokens_est']} {'WRITE' if wrote else 'SKIP'} (validate={how})")

    # ---- O(1) 索引：只存下标 ----
    by_pin: dict[str, int] = {}
    by_ball: dict[str, int] = {}
    by_function: dict[str, list[int]] = {}

    def _add_fn(name: str, idx: int) -> None:
        name = (name or "").strip()
        if not name:
            return
        lst = by_function.setdefault(name, [])
        if not lst or lst[-1] != idx:
            lst.append(idx)

    for idx, e in enumerate(entries):
        if e["pin"] and e["pin"] not in by_pin:
            by_pin[e["pin"]] = idx
        if e["ball"] and e["ball"] not in by_ball:
            by_ball[e["ball"]] = idx
        for fn in e["functions"]:
            _add_fn(fn, idx)
            if "/" in fn:                       # 复合功能名（如 LP4_DQ0_A/LP4X_DQ0_A）按分名建索引
                for sub in fn.split("/"):
                    if sub.strip() and sub.strip() != fn:
                        _add_fn(sub, idx)

    idx_doc = {
        "schema_version": SCHEMA_VERSION,
        "kind": "pinout_index",
        "scope": f"platform/{chip}",
        "source": f"raw/raw_platmform/{cfg['pinout']}",
        "source_sha1": sha,
        "generated_at": now,
        "by_pin": by_pin,
        "by_function": by_function,
        "by_ball": by_ball,
    }
    ip = PLATFORM_ROOT / chip / "pinout.index.json"
    iwrote = write_json_idempotent(ip, idx_doc, force=force)
    print(f"  [index ] {ip.relative_to(ROOT)}  by_pin={len(by_pin)} by_function={len(by_function)} "
          f"by_ball={len(by_ball)} {'WRITE' if iwrote else 'SKIP'}")
    return doc["tokens_est"], len(entries)


# --------------------------------------------------------------------------- #
# 总索引 rules/index.json
# --------------------------------------------------------------------------- #
def _resolve_common_file(topic: str) -> tuple[Path | None, str]:
    """定位 common/<主题>.json：优先同名文件；否则按主题词元模糊匹配实际文件。

    返回 (实际路径或 None, 相对路径) 。相对路径优先用实际文件名，找不到时用预期名
    ``common/<主题>.json``（缺失不报错）。
    """
    common_dir = RULES_ROOT / "common"
    expected_rel = f"common/{topic}.json"
    exp = common_dir / f"{topic}.json"
    if exp.exists():
        return exp, expected_rel
    if common_dir.is_dir():
        cjk = re.findall(r"[\u4e00-\u9fff]+", topic)
        words = [w.lower() for w in re.findall(r"[A-Za-z0-9]{3,}", topic)]
        for p in sorted(common_dir.glob("*.json")):
            stem_low = p.stem.lower()
            if cjk and not all(c in p.stem for c in cjk):
                continue
            if words and not all(w in stem_low for w in words):
                continue
            return p, f"common/{p.name}"
    return None, expected_rel


def build_total_index(platform_info: dict[str, dict]) -> dict:
    common: dict[str, dict] = {}
    for topic, stages in COMMON_TOPICS:
        resolved, rel = _resolve_common_file(topic)
        tokens = 0
        if resolved is not None:
            try:
                tokens = est_tokens(resolved.read_text(encoding="utf-8"))
            except Exception:
                tokens = 0
        common[topic] = {
            "file": rel,
            "prefix": "IC-",
            "stages": stages,
            "tokens_est": tokens,
        }

    platform: dict[str, dict] = {}
    for chip, info in platform_info.items():
        rules_ref = info["rules"][0] if len(info["rules"]) == 1 else info["rules"]
        platform[chip] = {
            "rules": rules_ref,
            "pinout": f"platform/{chip}/pinout.json",
            "pinout_index": f"platform/{chip}/pinout.index.json",
            "tokens_est": info["tokens_est"],
            "pins": info["pins"],
            "detect": {
                "model_regex": chip,
                "min_pins": max(1, int(info["pins"] * 0.5)),
            },
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "rules_index",
        "generated_at": _now_iso(),
        "common": common,
        "platform": platform,
        "load_policy": LOAD_POLICY,
    }


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description="平台资料 → rules/platform/<芯片>/ JSON 派生器")
    ap.add_argument("--force", action="store_true", help="忽略增量，强制重写全部产物")
    ap.add_argument("--chips", default=",".join(CHIPS.keys()),
                    help="逗号分隔的芯片列表（默认全部）")
    args = ap.parse_args()

    chips = [c.strip() for c in args.chips.split(",") if c.strip()]
    bad = [c for c in chips if c not in CHIPS]
    if bad:
        raise SystemExit(f"未知芯片: {bad}；可选 {list(CHIPS)}")

    print(f"platform_to_json | force={args.force} | chips={chips}")
    platform_info: dict[str, dict] = {}
    for chip in chips:
        cfg = CHIPS[chip]
        print(f"== {chip} ==")
        rules, rules_tokens = build_rules_files(chip, cfg, args.force)
        _, pins = build_pinout_files(chip, cfg, args.force)
        platform_info[chip] = {"rules": rules, "tokens_est": rules_tokens, "pins": pins}

    # 总索引：仅在全量芯片运行时写（避免部分运行时把索引裁剪掉其它芯片）
    if set(chips) == set(CHIPS.keys()):
        index = build_total_index(platform_info)
        wrote = write_json_idempotent(INDEX_JSON, index, force=args.force)
        print(f"== rules/index.json == {'WRITE' if wrote else 'SKIP'}")
        rk = platform_info.get("RK3588", {})
        print(f"RK3588: 规则 tokens_est={rk.get('tokens_est')} | 引脚={rk.get('pins')}")
    else:
        print("（部分芯片运行：跳过 rules/index.json 以避免裁剪其它芯片）")


if __name__ == "__main__":
    main()
