"""FastAPI web 后端 — 阶段7.

功能: 上传 EDN/BOM → 启动审查(子进程) → 状态/日志实时 → 门禁可见 → 人工回执。
前端: web/html|css|src 静态托管；数据: 读 run.log.jsonl/run.state.json/产物。
"""
from __future__ import annotations
import json, os, re, subprocess, sys, uuid, time
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASEDIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BASEDIR / "project"
PRODUCTS_DIR = BASEDIR / "storge" / "project"
WEB = BASEDIR / "web"

app = FastAPI(title="硬件审查台")
app.mount("/css", StaticFiles(directory=WEB / "css"), name="css")
app.mount("/src", StaticFiles(directory=WEB / "src"), name="src")
app.mount("/html", StaticFiles(directory=WEB / "html"), name="html")

RUNS: dict[str, dict] = {}  # run_id -> {product, state} 进程跟踪


def _safe_name(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z_\-\.]", "_", name)


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse((WEB / "html" / "index.html").read_text(encoding="utf-8"),
                        headers={"Cache-Control": "no-store, no-cache, must-revalidate"})


@app.get("/api/runs")
def list_runs():
    runs = []
    for p in sorted(PRODUCTS_DIR.glob("*")):
        if not p.is_dir():
            continue
        st = p / ".run" / "run.state.json"
        state = json.loads(st.read_text(encoding="utf-8")) if st.exists() else {}
        runs.append({"product": p.name, "current": state.get("current", "IDLE"),
                     "paused": state.get("paused", False), "pause_reason": state.get("pause_reason", "")})
    return runs


@app.post("/api/upload")
async def upload(product: str = Form(...), files: list[UploadFile] = File(...)):
    name = _safe_name(product)
    d = PROJECT_DIR / name
    d.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        p = d / f.filename
        p.write_bytes(await f.read())
        saved.append(f.filename)
    return {"product": name, "saved": saved}


@app.post("/api/start")
def start(product: str = Form(...), auto_pass: bool = Form(False)):
    name = _safe_name(product)
    src = "src"
    env = os.environ.copy()
    env["PYTHONPATH"] = src
    cmd = [sys.executable, "-m", "hardware_analysis.cli", "run", "--product", name]
    if auto_pass:
        cmd.append("--auto-pass")
    run_id = uuid.uuid4().hex[:8]
    # 后台子进程
    logf = open(PRODUCTS_DIR / name / ".run" / "stdout.log", "a", encoding="utf-8")  # 子进程 stdout 独立，勿污染 run.log.jsonl(JSONL)
    proc = subprocess.Popen(cmd, cwd=BASEDIR, env=env, stdout=logf, stderr=subprocess.STDOUT,
                            start_new_session=True)
    RUNS[run_id] = {"product": name, "pid": proc.pid}
    return {"run_id": run_id, "pid": proc.pid, "product": name}


@app.get("/api/state/{product}")
def state(product: str):
    name = _safe_name(product)
    st = PRODUCTS_DIR / name / ".run" / "run.state.json"
    if not st.exists():
        return {"product": name, "current": "IDLE"}
    return json.loads(st.read_text(encoding="utf-8"))


@app.get("/api/logs/{product}")
def logs(product: str, after: int = 0, n: int = 200):
    name = _safe_name(product)
    p = PRODUCTS_DIR / name / ".run" / "run.log.jsonl"
    if not p.exists():
        return {"events": [], "next": 0}
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    ev, i = [], after
    while i < len(lines) and len(ev) < n:          # 容错：跳过非 JSON 行（不因脏行 500）
        l = lines[i]; i += 1
        if not l.strip():
            continue
        try:
            ev.append(json.loads(l))
        except Exception:
            continue
    return {"events": ev, "next": i, "total": len(lines)}


@app.get("/api/gates/{product}")
def gates(product: str):
    name = _safe_name(product)
    gd = PRODUCTS_DIR / name / "gates"
    out = {}
    for f in sorted(gd.glob("G*.json")):
        try:
            out[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    return out


@app.post("/api/human/confirm")
def human_confirm(payload: dict):
    """人工回执：写 human_{kind}.json（step0a|batch|g6|manual）；manual 可带 decisions。"""
    product = _safe_name(payload.get("product", ""))
    kind = payload.get("kind", "batch")   # step0a | batch | g6 | manual
    answer = payload.get("answer", "continue")
    d = PRODUCTS_DIR / product / "gates"
    d.mkdir(exist_ok=True)
    obj = {"kind": kind, "answer": answer, "ts": time.time()}
    if kind == "manual" and isinstance(payload.get("decisions"), dict):
        obj["decisions"] = payload["decisions"]
    (d / "human_{}.json".format(kind)).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "written": f"human_{kind}.json", "n_decisions": len(obj.get("decisions", {}))}


@app.get("/api/manual_gaps/{product}")
def manual_gaps(product: str):
    """手册缺失确认清单（PH-1 产出）。"""
    name = _safe_name(product)
    p = PRODUCTS_DIR / name / "PH-1_手册检索" / "manual_gaps.json"
    if not p.exists():
        return {"total": 0, "gaps": []}
    return json.loads(p.read_text(encoding="utf-8"))


@app.post("/api/manual/upload")
async def manual_upload(file: UploadFile = File(...)):
    """人工补充手册：上传文件 → 存档 storge/datasheet/；若为 PDF 则自动转 .md。"""
    dest_dir = BASEDIR / "storge" / "datasheet"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / _safe_name(file.filename or "upload.bin")
    dest.write_bytes(await file.read())
    converted = None
    if dest.suffix.lower() == ".pdf":                  # 上传后自动触发转换
        try:
            from hardware_analysis.tools.pdf_to_md import convert
            r = convert(dest)
            converted = r.get("out") if r.get("ok") else r.get("error")
        except Exception as e:
            converted = f"转换失败:{str(e)[:60]}"
    return {"ok": True, "path": str(dest), "name": dest.name, "converted_md": converted}


@app.get("/api/problem/{product}")
def problem_dir(product: str):
    """故障分析产物(一期预留)。"""
    d = BASEDIR / "storge" / "problem" / _safe_name(product)
    return {"exists": d.exists(), "path": str(d)}
