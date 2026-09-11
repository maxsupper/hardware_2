"""chip_function — PH-2 芯片功能解析（NG-015/NG-016）.

用户需求：芯片功能必须在 PH-2 网表解析阶段补齐；能从 EDN 解析的直接解析，不行的问 LLM，
结果写回 netlist_graph.devices[].function 与 refdes_function_map.components[].function。

流程（对每个 kind="IC" 且 source.populated 的器件）：
  ① 直接从 EDN 解析：conventions.chip_function_by_symbol 顺序匹配 source.edn_symbol（大写），
     其次 model；命中即止 → source="edn_symbol" / confidence="HIGH"。
  ② 未命中 → 问 LLM（契约 ChipFunctionVerdict）给出功能概述/category/role/confidence；
     失败/契约不满足**不得中断** → category="其他", role="other",
     description=f"{model}（功能未确认）", source="unknown"。
  ③ 写回两处产物（紧凑 JSON，保持 netlist_graph v3.0 其它字段原样）。
  ④ 缓存 <PH-2_dir>/chip_function_cache.json（键 f"{edn_symbol}|{model}"），二跑 0 次 LLM 且字节一致。

用法:
  PYTHONPATH=src python -m hardware_analysis.tools.chip_function <PH-2_网表解析_dir> \
      [--product X] [--manual-index <path>] [--force] [--retries N] [--timeout S]
"""
from __future__ import annotations
import argparse, json, re, sys
from collections import Counter
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hardware_analysis.common.conventions import CONV
from hardware_analysis.models.contracts import ChipFunction, ChipFunctionVerdict

PROMPT_VERSION = "chip_function_v1"
NETS_LIMIT = 30
_DEFAULT_ROLES = ["soc", "power", "memory", "interface", "mcu_soc", "protection", "switch", "other"]


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def _dedup(seq) -> list:
    seen, out = set(), []
    for x in seq:
        s = str(x or "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def device_nets(dev: dict) -> tuple[list, list]:
    """返回 (截断到 30 的去重网络名, 全量去重网络名)。"""
    nets = _dedup((dev.get("pins") or {}).values())
    return nets[:NETS_LIMIT], nets


def power_domains(nets) -> list:
    return [n for n in nets if CONV.is_power_net(n)]


def match_direct(edn_symbol, model, table) -> tuple[dict | None, str]:
    """顺序匹配 edn_symbol（大写）→ model；返回 (verdict, 命中的 pattern)。"""
    for txt in (edn_symbol, model):
        t = str(txt or "").upper()
        if not t:
            continue
        for r in table:
            pat = str(r.get("pattern", "") or "")
            if not pat:
                continue
            if re.search(pat, t):
                return {"category": r.get("category", ""), "role": r.get("role", "other"),
                        "description": r.get("description", "")}, pat
    return None, ""


def _sanitize_verdict(obj, roles) -> dict | None:
    """归一化 LLM 判定：role 必须落在枚举内；description 为空视为契约失败。"""
    desc = str(getattr(obj, "description", "") or "").strip()
    if not desc:
        return None
    role = str(getattr(obj, "role", "") or "").strip().lower()
    if role not in roles:
        role = "other"
    conf = str(getattr(obj, "confidence", "") or "").strip().upper()
    if conf not in ("HIGH", "LIKELY", "UNCERTAIN"):
        conf = "UNCERTAIN"
    cat = str(getattr(obj, "category", "") or "").strip() or "其他"
    return {"category": cat, "role": role, "description": desc, "confidence": conf}


def build_prompt(dev: dict, roles, manual_path: str, ic_type: str) -> str:
    sym = (dev.get("source") or {}).get("edn_symbol") or ""
    model = dev.get("model") or ""
    nets30, _ = device_nets(dev)
    return (
        "任务: 判定这颗芯片的功能。给出功能概述(中文≤40字)、类别 category、角色 role、置信度 confidence。\n"
        f"edn_symbol={sym} model={model}\n"
        f"型号(model): {model}\n"
        f"EDN符号(edn_symbol): {sym}\n"
        f"引脚数: {len(dev.get('pins') or {})}\n"
        f"主要网络(前{NETS_LIMIT}): {', '.join(nets30) if nets30 else '无'}\n"
        f"手册: {manual_path or '无'}\n"
        f"ic_type: {ic_type or 'UNKNOWN'}\n"
        f"role 只能取以下枚举之一: {', '.join(roles)}\n"
        "只输出 JSON: {\"category\":\"\",\"role\":\"\",\"description\":\"\",\"confidence\":\"HIGH|LIKELY|UNCERTAIN\",\"reason\":\"\"}\n"
    )


def _llm_verdict(prompt: str, roles, retries: int, timeout: int) -> tuple[dict | None, str]:
    """调 LLM（含本地重试）；返回 (verdict 或 None, 错误信息)。HARDWARE_MOCK=1 走模板 mock。"""
    from hardware_analysis.agents.direct import llm_json
    err = ""
    for _ in range(max(0, retries) + 1):
        obj, errs, _sec = llm_json("hw_chip_function", prompt, ChipFunctionVerdict, timeout=timeout)
        if obj is not None:
            v = _sanitize_verdict(obj, roles)
            if v is not None:
                return v, ""
            err = "契约失败: description 为空"
        else:
            err = "；".join(errs)[:150] if errs else "LLM 返回空"
    return None, err


def _load_manual_index(path: Path | None) -> dict:
    if not path or not Path(path).exists():
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")).get("entries", {}) or {}
    except Exception:
        return {}


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def process(ph2_dir: Path, product: str = "", force: bool = False,
            manual_index: str | None = None, retries: int = 1,
            timeout: int = 60) -> dict:
    ph2 = Path(ph2_dir)
    gpath = ph2 / "netlist_graph.json"
    if not gpath.exists():
        raise FileNotFoundError(f"缺少 {gpath}（PH-2 未产出）")
    doc = json.loads(gpath.read_text(encoding="utf-8"))
    devices = doc.get("devices", [])

    table = CONV.cfg.get("chip_function_by_symbol") or []
    roles = CONV.cfg.get("chip_function_roles") or _DEFAULT_ROLES

    mi = _load_manual_index(Path(manual_index) if manual_index else (ph2 / "manual_index.json"))

    cache_path = ph2 / "chip_function_cache.json"
    cache = {}
    if cache_path.exists():
        try:
            old = json.loads(cache_path.read_text(encoding="utf-8"))
            if old.get("prompt_version") == PROMPT_VERSION:
                cache = dict(old.get("entries") or {})
        except Exception:
            cache = {}

    stats = Counter()
    func_by_id: dict[str, dict] = {}
    llm_calls = 0
    for dev in devices:
        if dev.get("kind") != "IC" or not (dev.get("source") or {}).get("populated"):
            continue
        sym = (dev.get("source") or {}).get("edn_symbol") or ""
        model = dev.get("model") or ""
        verdict, matched = match_direct(sym, model, table)
        if verdict is not None:
            source, confidence = "edn_symbol", "HIGH"
        else:
            key = f"{sym}|{model}"
            if not force and key in cache:
                verdict = cache[key]
                source = "llm"
                confidence = str(verdict.get("confidence") or "LIKELY")
            else:
                ent = mi.get(dev.get("id")) or {}
                man = ent.get("manual_path") or (dev.get("ic") or {}).get("manual_path") or ""
                ic_type = ent.get("ic_type") or (dev.get("ic") or {}).get("ic_type") or ""
                llm_calls += 1
                got, _err = _llm_verdict(build_prompt(dev, roles, man, ic_type), roles, retries, timeout)
                if got is None:
                    verdict = {"category": "其他", "role": "other",
                               "description": f"{model}（功能未确认）", "confidence": "UNKNOWN"}
                    source, confidence = "unknown", "UNKNOWN"
                else:
                    verdict = got
                    cache[key] = got
                    source, confidence = "llm", str(got.get("confidence") or "LIKELY")
            matched = "llm"
        nets30, allnets = device_nets(dev)
        fn = ChipFunction(category=verdict.get("category", "") or "其他",
                          role=verdict.get("role", "other") or "other",
                          description=verdict.get("description", "") or f"{model}（功能未确认）",
                          source=source, confidence=confidence,
                          evidence={"edn_symbol": sym, "model": model, "matched": matched},
                          nets=nets30, power_domains=power_domains(allnets))
        dev["function"] = fn.model_dump()
        func_by_id[dev.get("id", "")] = dev["function"]
        stats[source] += 1

    total = sum(stats.values())
    doc.setdefault("meta", {})["chip_function"] = {
        "total": total, "by_source": {k: stats[k] for k in sorted(stats)}}
    gpath.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # ---- 写回 refdes_function_map.json ----
    rp = ph2 / "refdes_function_map.json"
    wrote_map = False
    if rp.exists() and func_by_id:
        rm = json.loads(rp.read_text(encoding="utf-8"))
        for c in rm.get("components", []):
            f = func_by_id.get(c.get("id"))
            if f:
                c["function"] = {"category": f["category"], "role": f["role"],
                                 "description": f["description"], "nets": f["nets"],
                                 "power_domains": f["power_domains"],
                                 "source": f["source"], "confidence": f["confidence"]}
        rp.write_text(json.dumps(rm, ensure_ascii=False, indent=1), encoding="utf-8")
        wrote_map = True

    # ---- 缓存落盘（含 prompt_version；确定性排序）----
    cache_path.write_text(json.dumps({"prompt_version": PROMPT_VERSION, "entries": cache},
                                     ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")

    stats_out = {"total": total, "by_source": {k: stats[k] for k in sorted(stats)},
                 "llm_calls": llm_calls, "refdes_map_written": wrote_map}
    print(f"chip_function: IC={total} 来源={dict(sorted(stats.items()))} "
          f"LLM调用={llm_calls} refdes_map={'已写' if wrote_map else '无'}")
    return stats_out


def main() -> None:
    ap = argparse.ArgumentParser(description="PH-2 芯片功能解析（EDN 直解 + LLM 补充）")
    ap.add_argument("b_prep_dir", help="PH-2_网表解析 目录（含 netlist_graph.json）")
    ap.add_argument("--product", default="")
    ap.add_argument("--manual-index", default=None, help="manual_index.json 路径（LLM 上下文，可缺省）")
    ap.add_argument("--force", action="store_true", help="强制重算（忽略缓存）")
    ap.add_argument("--retries", type=int, default=1, help="LLM 失败重试次数（默认 1）")
    ap.add_argument("--timeout", type=int, default=60, help="LLM 单次超时秒（默认 60）")
    args = ap.parse_args()
    try:
        process(Path(args.b_prep_dir), args.product, args.force,
                args.manual_index, args.retries, args.timeout)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
