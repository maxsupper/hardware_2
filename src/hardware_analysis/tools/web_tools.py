"""Tavily web 三工具 — 阶段3c（web_search / web_extract / web_download）.

基于 config.json(web.tavily) + 环境变量覆盖；HTTP 直连，无 SDK 依赖。
用法见各函数；亦提供 CLI 自测。
"""
from __future__ import annotations
import json, sys, urllib.request, urllib.parse
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hardware_analysis.config import Config

TAVILY_SEARCH = "https://api.tavily.com/search"
TAVILY_EXTRACT = "https://api.tavily.com/extract"


def _post(url: str, payload: dict, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def web_search(query: str, max_results: int = 5, timeout: int = 25, cfg: Config | None = None) -> list:
    cfg = cfg or Config()
    d = _post(TAVILY_SEARCH, {"api_key": cfg.tavily_key, "query": query,
                              "max_results": max_results, "search_depth": "basic"}, timeout)
    return [{"title": r.get("title", ""), "url": r.get("url", ""),
             "content": (r.get("content") or "")[:300]} for r in d.get("results", [])]


def web_extract(url: str, depth: str = "basic", timeout: int = 35, cfg: Config | None = None) -> dict:
    cfg = cfg or Config()
    try:
        d = _post(TAVILY_EXTRACT, {"api_key": cfg.tavily_key, "urls": [url], "extract_depth": depth}, timeout)
        r = (d.get("results") or [{}])[0]
        return {"url": url, "ok": r.get("status") is not None or "raw_content" in r,
                "raw_content": (r.get("raw_content") or ""),
                "status": r.get("status", ""), "error": r.get("failed_reason", "")}
    except Exception as e:
        return {"url": url, "ok": False, "raw_content": "", "error": str(e)[:120]}


def web_download(url: str, dest: str | Path, timeout: int = 40) -> dict:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(url, str(dest), timeout=timeout)
        return {"url": url, "ok": True, "dest": str(dest), "size": dest.stat().st_size}
    except Exception as e:
        return {"url": url, "ok": False, "dest": str(dest), "error": str(e)[:120]}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("search"); p1.add_argument("q")
    p2 = sub.add_parser("extract"); p2.add_argument("url")
    p3 = sub.add_parser("download"); p3.add_argument("url"); p3.add_argument("dest")
    a = ap.parse_args()
    if a.cmd == "search":
        for r in web_search(a.q):
            print(f"* {r['title'][:50]} | {r['url']}")
    elif a.cmd == "extract":
        e = web_extract(a.url)
        print("ok:", e["ok"], "| 长度:", len(e["raw_content"]), "| err:", e["error"][:60])
        print(e["raw_content"][:200])
    elif a.cmd == "download":
        print(web_download(a.url, a.dest))
