#!/usr/bin/env python3
"""platform_check — 平台官方引脚表核对（PF-001 / PF-003 / PF-004；对应 IC-007 / IC-008）.

确定性工具：用平台官方引脚表核对网表里主控 SoC 的每个引脚。
  官方表优先级：rules/platform/<芯片>/pinout.json   （新格式，含 entries[]）
                → 回退 raw/raw_platmform/<芯片>/pinout.json （旧格式，含 pins{}）
  两种结构自动探测（有 entries 用 entries，否则用 pins 的 dict 值 + 键）。

核对三类（判据保守，宁可 WARNING 不可乱 FAIL）：
  1) pin_existence  引脚存在性 —— 归一化后能否在官方表找到；找不到记 MISSING_IN_PINOUT (WARNING)。
  2) function       功能/复用 —— 官方 functions 与网络名语义冲突；仅明确冲突才记 FUNCTION_MISMATCH。
  3) domain         电平域   —— 官方 domain/voltage 与网表可推断电压是否一致；
                     无电压证据只记 SKIPPED_NO_NET_VOLTAGE，不编造。
并报告覆盖率 = 已核对脚数 / 应核对脚数（PF-004）。

平台识别（PF-001）：无 --platform 时按 rules/index.json 的 platform.<芯片>.detect
（model_regex + min_pins）识别；index.json 缺失时回退扫 rules/platform/* 与
raw/raw_platmform/* 目录名，用「型号包含芯片名 + len(pins)>=100」匹配。

用法:
  python -m hardware_analysis.tools.platform_check <PH-2_网表解析_dir> [--platform RK3588] [--out platform_check.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# 项目根 = <root>/src/hardware_analysis/tools/platform_check.py → parents[3]
ROOT = Path(__file__).resolve().parents[3]

from hardware_analysis.common.conventions import CONV  # noqa: E402  （DEV-010：脚名归一权威源）

SCHEMA_VERSION = "1.0"
DEFAULT_MIN_PINS = 100           # 无 detect 规则时的回退最小引脚数（主控 SoC 量级）
DOMAIN_VOLT_TOL = 0.05           # 电压比对容差（V）

# ---------------------------------------------------------------------------
# 一、引脚名归一化（基于 CONV.pin_norm 扩展；单一权威源 + 本工具的语义后缀剥离）
# ---------------------------------------------------------------------------
_TRAIL_LETTER = re.compile(r"_[a-z]$")


def _stem_dir_suffix(s: str) -> str:
    """剥离尾部方向/复用/板号注记（最多 2 个单字母 token，如 `_u_F`/`_d_C`/`_A`/`_Z`）。"""
    for _ in range(2):
        s2 = _TRAIL_LETTER.sub("", s)
        if s2 == s:
            break
        s = s2
    return s


def pin_key(label: str) -> str:
    """统一归一：CONV.pin_norm（去 `&` / 去 `_A|_B` / 小写）+ 去尾部单字母注记。

    例：`GPIO0_D4_u_F`→`gpio0_d4`；`AVSS_100_Z`→`avss_100`；`DDR_CH0_DQ0_A`→`ddr_ch0_dq0`；
        `GPIO2_B7_d`（官方）→`gpio2_b7`。大小写无关。
    """
    return _stem_dir_suffix(CONV.pin_norm(label))


def variants(label: str) -> set[str]:
    """一个标签的归一化候选集：整体 + 按 `/` 拆分的各别名（网表/官方都可能给组合名）。"""
    raw = str(label or "").strip().lstrip("&")
    out = {pin_key(raw)}
    for part in raw.split("/"):
        part = part.strip()
        if part:
            out.add(pin_key(part))
    return {x for x in out if x}


# ---------------------------------------------------------------------------
# 二、官方引脚表加载（两种结构自动探测）
# ---------------------------------------------------------------------------
def _as_func_list(v) -> list[str]:
    if not v:
        return []
    if isinstance(v, dict):
        return [str(x) for x in v.values() if x]
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        return [str(x) for x in v if x]
    return [str(v)]


def _entry(pin="", ball="", functions=None, type_="", power_domain="",
           voltage="", mux="", notes="") -> dict:
    return {
        "pin": str(pin or ""),
        "ball": str(ball or ""),
        "functions": functions or [],
        "type": str(type_ or ""),
        "power_domain": str(power_domain or ""),
        "voltage": voltage if voltage is not None else "",
        "mux": str(mux or ""),
        "notes": str(notes or ""),
    }


def load_pinout(path: Path) -> tuple[list[dict], str]:
    """读 pinout.json → (entries, fmt)。fmt ∈ {entries, pins}。"""
    d = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(d, dict) and isinstance(d.get("entries"), list):
        entries = []
        for e in d["entries"]:
            if not isinstance(e, dict):
                continue
            entries.append(_entry(
                pin=e.get("pin") or e.get("name") or e.get("gpio") or "",
                ball=e.get("ball") or "",
                functions=_as_func_list(e.get("functions") or e.get("function")),
                type_=e.get("type") or e.get("io_type") or "",
                power_domain=e.get("power_domain") or e.get("domain") or "",
                voltage=e.get("voltage") or "",
                mux=e.get("mux") or "",
                notes=e.get("notes") or e.get("pull") or "",
            ))
        return entries, "entries"

    if isinstance(d, dict) and isinstance(d.get("pins"), dict):
        entries = []
        for key, v in d["pins"].items():
            if not isinstance(v, dict):
                v = {}
            base = str(key).lstrip("_")
            entries.append(_entry(
                pin=v.get("gpio") or base,
                ball=v.get("ball") or base,
                functions=_as_func_list(v.get("functions")),
                type_=v.get("io_type") or "",
                power_domain=v.get("domain") or "",
                voltage=v.get("voltage") or "",
                notes=v.get("pull") or "",
            ))
        return entries, "pins"

    raise ValueError(f"无法识别的 pinout 结构: {path}")


def resolve_pinout(root: Path, chip: str) -> tuple[list[dict], str, str, dict]:
    """按优先级定位官方表 → (entries, fmt, source_path, extra_meta)。找不到抛 FileNotFoundError。"""
    cand = [
        root / "rules" / "platform" / chip / "pinout.json",
        root / "raw" / "raw_platmform" / chip / "pinout.json",
    ]
    # 目录名大小写无关回退
    for base_key, base in (("rules", root / "rules" / "platform"),
                           ("raw", root / "raw" / "raw_platmform")):
        if base.is_dir():
            for p in base.iterdir():
                if p.is_dir() and p.name.lower() == chip.lower():
                    cand.append(p / "pinout.json")
    seen = set()
    for p in cand:
        if p in seen:
            continue
        seen.add(p)
        if p.exists():
            entries, fmt = load_pinout(p)
            extra = {}
            idxp = p.with_name("pinout.index.json")
            if idxp.exists():
                try:
                    extra["index"] = json.loads(idxp.read_text(encoding="utf-8"))
                except Exception:
                    extra["index"] = None
            return entries, fmt, str(p), extra
    raise FileNotFoundError("NO_OFFICIAL_PINOUT")


def build_official_index(entries: list[dict], external_index: dict | None = None) -> dict:
    """归一化标识 → entry 下标。索引 pin/ball/gpio/functions（`/` 拆别名） + 外部 index。"""
    idx: dict[str, int] = {}

    def put(key: str, i: int):
        if key and key not in idx:
            idx[key] = i

    for i, e in enumerate(entries):
        for ident in (e["pin"], e["ball"], *(e.get("functions") or [])):
            for k in variants(ident):
                put(k, i)
    if isinstance(external_index, dict):
        for bucket in ("by_pin", "by_ball", "by_function"):
            for k, v in (external_index.get(bucket) or {}).items():
                vals = v if isinstance(v, (list, tuple)) else [v]
                for vi in vals:
                    if isinstance(vi, int) and 0 <= vi < len(entries):
                        for nk in variants(k):
                            put(nk, vi)
    return idx


# ---------------------------------------------------------------------------
# 三、平台识别（PF-001）
# ---------------------------------------------------------------------------
def load_platform_rules(root: Path, rules_dir: Path | None = None) -> dict:
    """→ {chip: {model_regex, min_pins, source}}。优先 rules/index.json，回退目录扫描。"""
    rules_dir = rules_dir or (root / "rules")
    plats: dict[str, dict] = {}
    idxp = rules_dir / "index.json"
    if idxp.exists():
        try:
            d = json.loads(idxp.read_text(encoding="utf-8"))
        except Exception:
            d = {}
        for chip, spec in (d.get("platform") or {}).items():
            spec = spec if isinstance(spec, dict) else {}
            det = spec.get("detect") if isinstance(spec.get("detect"), dict) else spec
            rx = (det.get("model_regex") or det.get("regex") or det.get("model")
                  or spec.get("model_regex") or chip)
            mp = det.get("min_pins", det.get("min_pin", spec.get("min_pins", DEFAULT_MIN_PINS)))
            try:
                mp = int(mp)
            except (TypeError, ValueError):
                mp = DEFAULT_MIN_PINS
            plats[chip] = {"model_regex": rx, "min_pins": mp, "source": "rules/index.json"}

    if not plats:  # 回退：扫 rules/platform/* 与 raw/raw_platmform/* 目录名
        cands: set[str] = set()
        for base in (rules_dir / "platform", root / "raw" / "raw_platmform"):
            if base.is_dir():
                cands |= {p.name for p in base.iterdir() if p.is_dir()}
        for chip in sorted(cands):
            plats[chip] = {"model_regex": re.escape(chip), "min_pins": DEFAULT_MIN_PINS,
                           "source": "dir-scan"}
    return plats


def detect_platform(graph: dict, plats: dict, forced: str | None = None) -> tuple[str, dict, str]:
    """→ (chip, device, detect_reason)。识别不到 device → ("", {}, "NO_PLATFORM_MATCH")。"""
    ic_devs = [d for d in graph.get("devices", [])
               if str(d.get("kind", "")).upper() == "IC"]

    def max_pin_ic():
        return max(ic_devs, key=lambda d: len(d.get("pins") or {}), default=None)

    if forced:
        spec = None
        for chip, s in plats.items():
            if chip.lower() == forced.lower():
                spec, chip_name = s, chip
                break
        else:
            chip_name = forced
            spec = {"model_regex": re.escape(forced), "min_pins": 1, "source": "forced"}
        targets = [(chip_name, spec)]
    else:
        targets = list(plats.items())

    best = None  # (npins, chip, device, reason)
    for chip, spec in targets:
        rx = None
        try:
            rx = re.compile(str(spec.get("model_regex") or chip), re.I)
        except re.error:
            rx = re.compile(re.escape(chip), re.I)
        for d in ic_devs:
            model = str(d.get("model") or "")
            npins = len(d.get("pins") or {})
            if rx.search(model) and npins >= int(spec.get("min_pins") or DEFAULT_MIN_PINS):
                reason = f"DETECT:{spec.get('source','')}"
                if best is None or npins > best[0]:
                    best = (npins, chip, d, reason)
    if best:
        return best[1], best[2], best[3]

    if forced and ic_devs:  # 强制平台但型号不匹配 → 回退最大脚 IC，显式标注
        d = max_pin_ic()
        return forced, d, "DETECT_FORCED_FALLBACK_MAX_PINS"
    return "", {}, "NO_PLATFORM_MATCH"


# ---------------------------------------------------------------------------
# 四、语义族 / 电压推断（保守）
# ---------------------------------------------------------------------------
_FAMILY_RE = [
    ("DDR", re.compile(r"DDR")),
    ("EMMC", re.compile(r"EMMC")),
    ("SDMMC", re.compile(r"SDMMC|SDIO")),
    ("SATA", re.compile(r"SATA")),
    ("PCIE", re.compile(r"PCIE")),
    ("USB", re.compile(r"USB|TYPEC|OTG")),
    ("MIPI", re.compile(r"MIPI|CSI|DSI|DPHY|CPHY")),
    ("HDMI", re.compile(r"HDMI")),
    ("EDP", re.compile(r"EDP")),
    ("GMAC", re.compile(r"GMAC")),
    ("UART", re.compile(r"UART")),
    ("I2C", re.compile(r"I2C")),
    ("SPI", re.compile(r"SPI")),
    ("I2S", re.compile(r"I2S")),
    ("PDM", re.compile(r"PDM")),
    ("PWM", re.compile(r"PWM")),
    ("CAN", re.compile(r"CAN")),
    ("JTAG", re.compile(r"JTAG|TDI|TDO|TCK|TMS|TRST")),
    ("GPIO", re.compile(r"GPIO")),
    ("POWER", re.compile(r"VCC|VDD|VSS|AVSS|AVDD|VCCIO|PMUIO|GND|VBAT|VIN|VREF")),
]
_DEDICATED = {"DDR", "EMMC", "SDMMC", "SATA", "PCIE", "USB", "MIPI", "HDMI", "EDP",
              "GMAC", "UART", "I2C", "SPI", "I2S", "PDM", "PWM", "CAN", "JTAG"}


def family_of(label: str) -> set[str]:
    u = str(label or "").upper()
    return {name for name, rx in _FAMILY_RE if rx.search(u)}


_VOLT_RE = re.compile(r"(\d)\s*V\s*(\d{1,3})")


def voltage_of(label: str) -> float | None:
    """从名称解析电压（`1V8`→1.8 / `0V75`→0.75 / `VCC4V0`→4.0）；无法解析→None。"""
    m = _VOLT_RE.search(str(label or "").upper().replace(" ", ""))
    if not m:
        return None
    try:
        return int(m.group(1)) + float("0." + m.group(2))
    except ValueError:
        return None


def official_voltage(e: dict) -> float | None:
    """官方电压：优先数值 voltage 字段，其次从 voltage/domain 名称解析（`1V8`/`3V3`）。"""
    v = e.get("voltage")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if isinstance(v, str) and v.strip():
        try:
            return float(v.strip())
        except ValueError:
            parsed = voltage_of(v)
            if parsed is not None:
                return parsed
    return voltage_of(e.get("power_domain") or "")


# ---------------------------------------------------------------------------
# 五、核对
# ---------------------------------------------------------------------------
def check(graph: dict, chip: str, device: dict, entries: list[dict],
          index: dict, detect_reason: str, pinout_src: str, pinout_fmt: str) -> dict:
    dev_id = device.get("id") or f"{device.get('board','')}::{device.get('refdes','')}"
    pins: dict = device.get("pins") or {}
    findings: list[dict] = []
    samples_missing: list[dict] = []
    samples_mismatch: list[dict] = []

    def add(sev, check_name, pin, net, expected, actual, detail):
        fid = f"PF-003-{len(findings) + 1:04d}"
        f = {"id": fid, "severity": sev, "check": check_name,
             "object": f"{dev_id}.{pin}", "net": net,
             "expected": expected, "actual": actual, "detail": detail}
        findings.append(f)
        if len(samples_mismatch) < 10 and check_name != "pin_existence":
            samples_mismatch.append(f)

    # ---- 域电压分组推断（同域其他脚网络名含电压 → 推断该域实际电压）----
    domain_nets: dict[str, list[str]] = defaultdict(list)
    matched_pin: dict[str, int] = {}
    for pin, net in pins.items():
        i = None
        for k in variants(pin):
            if k in index:
                i = index[k]
                break
        matched_pin[pin] = i if i is not None else -1
        if i is not None:
            dom = entries[i]["power_domain"]
            if dom:
                domain_nets[dom].append(str(net or ""))
    domain_infer: dict[str, float] = {}
    for dom, nets in domain_nets.items():
        vols = [v for v in (voltage_of(n) for n in nets) if v is not None]
        if vols:
            domain_infer[dom] = Counter(vols).most_common(1)[0][0]

    stats = {"pins_total": len(pins), "matched": 0, "missing_in_pinout": 0,
             "function_mismatch": 0, "domain_mismatch": 0, "skipped_no_net_voltage": 0}

    for pin in sorted(pins):
        net = str(pins.get(pin) or "")
        i = matched_pin[pin]
        if i is None or i < 0:
            stats["missing_in_pinout"] += 1
            if len(samples_missing) < 10:
                samples_missing.append({"pin": pin, "net": net,
                                        "norm": sorted(variants(pin))})
            add("WARNING", "pin_existence", pin, net,
                "存在于官方引脚表", "未匹配（归一化后仍无）",
                "可能为归一化不足或官方表缺失；建议人工确认，勿直接判 FAIL")
            continue

        stats["matched"] += 1
        e = entries[i]
        funcs = e.get("functions") or []

        # ---- 功能/复用（保守）----
        off_fam: set[str] = set()
        for f in [e.get("pin", ""), *funcs]:
            off_fam |= family_of(f)
        is_gpio_capable = bool(e.get("pin", "").upper().startswith("GPIO")) or ("GPIO" in off_fam)
        net_fam = family_of(net) - {"POWER"}
        off_bus = off_fam - {"POWER", "GPIO"}
        if (not is_gpio_capable and off_bus and net_fam
                and not (off_bus & net_fam)):
            sev = "FAIL" if off_bus == {"DDR"} else "WARNING"
            stats["function_mismatch"] += 1
            add(sev, "function", pin, net,
                "官方功能=" + "/".join(funcs[:4] or [e.get("pin", "")]),
                "网络语义族=" + "/".join(sorted(net_fam)),
                "官方脚功能族与网络名语义族不相交；判据保守，人工复核")

        # ---- 电平域（无证据不编造）----
        off_v = official_voltage(e)
        if e.get("power_domain") or e.get("voltage"):
            net_v = voltage_of(net)
            if net_v is None:
                net_v = domain_infer.get(e["power_domain"])
            if net_v is None:
                stats["skipped_no_net_voltage"] += 1
            elif off_v is not None and abs(net_v - off_v) > DOMAIN_VOLT_TOL:
                stats["domain_mismatch"] += 1
                add("FAIL", "domain", pin, net,
                    f"{e['power_domain'] or e.get('voltage')}({off_v}V)",
                    f"{net_v}V（net/inferred）",
                    "官方电平域电压与网表可推断电压不一致（IC-008）")

    sev_set = {f["severity"] for f in findings}
    status = "FAIL" if "FAIL" in sev_set else ("WARNING" if "WARNING" in sev_set else "PASS")
    expected = len(entries)
    checked = stats["pins_total"]
    coverage = {
        "target": dev_id,
        "items_expected": expected,
        "items_checked": checked,
        "fill_rate": round(checked / expected, 4) if expected else 0.0,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "platform_check",
        "product": graph.get("product", ""),
        "platform": chip,
        "device": dev_id,
        "status": status,
        "coverage": coverage,
        "findings": findings,
        "stats": stats,
        "samples": {"missing": samples_missing, "mismatch": samples_mismatch},
        "meta": {
            "detect": detect_reason,
            "pinout_source": pinout_src,
            "pinout_format": pinout_fmt,
            "pinout_entries": expected,
            "device_model": device.get("model", ""),
            "normalization": ("pin_norm=C[strip '&'|drop '_A/_B'|lowercase]"
                              "+drop up-to-2 trailing single-letter tokens; '/' splits aliases"),
            "function_rule": "仅当官方非GPIO专用总线族与网络语义族不相交才报；官方仅DDR→FAIL，其余WARNING",
            "domain_rule": "无网络/同域电压证据只记 SKIPPED_NO_NET_VOLTAGE；电压明确不等才报 DOMAIN_MISMATCH",
        },
    }


# ---------------------------------------------------------------------------
# 六、CLI
# ---------------------------------------------------------------------------
def _warn(reason: str, graph: dict, chip: str = "") -> dict:
    return {
        "schema_version": SCHEMA_VERSION, "kind": "platform_check",
        "product": graph.get("product", ""), "platform": chip, "device": "",
        "status": "WARNING", "reason": reason,
        "coverage": {"target": "", "items_expected": 0, "items_checked": 0, "fill_rate": 0.0},
        "findings": [],
        "stats": {"pins_total": 0, "matched": 0, "missing_in_pinout": 0,
                  "function_mismatch": 0, "domain_mismatch": 0, "skipped_no_net_voltage": 0},
        "samples": {"missing": [], "mismatch": []},
        "meta": {"reason": reason},
    }


def run(prep_dir: Path, platform: str | None = None, rules_dir: Path | None = None,
        root: Path | None = None) -> dict:
    root = root or (rules_dir.parent if rules_dir else ROOT)
    gp = prep_dir / "netlist_graph.json"
    if not gp.exists():
        raise FileNotFoundError(f"缺少 {gp}")
    graph = json.loads(gp.read_text(encoding="utf-8"))

    plats = load_platform_rules(root, rules_dir)
    chip, device, reason = detect_platform(graph, plats, platform)
    if not device:
        return _warn("NO_PLATFORM_MATCH", graph)

    try:
        entries, fmt, src, extra = resolve_pinout(root, chip)
    except FileNotFoundError:
        r = _warn("NO_OFFICIAL_PINOUT", graph, chip)
        r["device"] = device.get("id", "")
        return r

    index = build_official_index(entries, extra.get("index"))
    return check(graph, chip, device, entries, index, reason, src, fmt)


def main() -> None:
    ap = argparse.ArgumentParser(description="平台官方引脚表核对（PF-001/PF-003/PF-004）")
    ap.add_argument("prep_dir", help="PH-2_网表解析 目录（含 netlist_graph.json）")
    ap.add_argument("--platform", default=None, help="强制平台芯片名（如 RK3588）；缺省自动识别")
    ap.add_argument("--out", default=None, help="输出 JSON（默认 <prep_dir>/platform_check.json）")
    ap.add_argument("--rules-dir", default=None, help="rules 目录（默认 <root>/rules）")
    args = ap.parse_args()

    d = Path(args.prep_dir)
    rules_dir = Path(args.rules_dir) if args.rules_dir else None
    report = run(d, args.platform, rules_dir, root=(rules_dir.parent if rules_dir else None))

    out = Path(args.out) if args.out else d / "platform_check.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    c = report["coverage"]
    s = report["stats"]
    print(f"[platform_check] platform={report['platform'] or '-'} device={report['device'] or '-'} "
          f"status={report['status']} reason={report.get('reason','') or '-'} | "
          f"coverage={c['items_checked']}/{c['items_expected']}={c['fill_rate']} | "
          f"matched={s['matched']} missing={s['missing_in_pinout']} "
          f"func_mismatch={s['function_mismatch']} domain_mismatch={s['domain_mismatch']} "
          f"skipped_volt={s['skipped_no_net_voltage']} → {out}")


if __name__ == "__main__":
    main()
