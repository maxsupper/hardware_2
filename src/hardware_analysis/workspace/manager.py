"""workspace 管理器 — 创建产品 run 工作区 + run_manifest。

目录（对齐 rules.json path_map）:
  storge/project/<产品>/PH-0_input .. PH-7_delivery + gates .run(temp+log)
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

STAGE_DIRS = ["PH-0_input", "PH-1_manual", "PH-2_check", "PH-3_netlist",
              "PH-4_analyze", "PH-5_report", "PH-6_audit", "PH-7_delivery",
              "gates", ".run/temp"]


class RunWorkspace:
    def __init__(self, root: str | Path, product: str):
        self.root = Path(root)
        self.product = product
        self.dir = self.root / product

    def create(self) -> dict:
        self.dir.mkdir(parents=True, exist_ok=True)
        for d in STAGE_DIRS:
            (self.dir / d).mkdir(parents=True, exist_ok=True)
        self.dir.joinpath(".run", "run.log.jsonl").touch(exist_ok=True)
        manifest = self.manifest()
        return manifest

    def manifest(self) -> dict:
        m = {
            "schema_version": "1.0", "kind": "run_manifest",
            "product": self.product,
            "run_dir": str(self.dir),
            "phases": {f"PH-{i}": "PENDING" for i in range(8)},
            "gates": {f"G{i}": "PENDING" for i in range(1, 8)},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        p = self.dir / "run_manifest.json"
        p.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
        return m

    def log(self, event: dict) -> None:
        """追加结构化事件（run.log.jsonl，JSONL 一行一条）供 web SSE 消费。"""
        ev = {"ts": datetime.now(timezone.utc).isoformat(), **event}
        with open(self.dir / ".run" / "run.log.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")

    def write_state(self, state: dict) -> None:
        (self.dir / ".run" / "run.state.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---------- 中间过程文件清理（即用即清 + 最终清理） ----------
    @property
    def temp(self) -> Path:
        return self.dir / ".run" / "temp"

    def clean_temp(self, patterns: tuple = ("*"), keep_dir: bool = True) -> int:
        """删除 .run/temp 下（匹配 patterns 的）中间文件；返回删除数。"""
        n = 0
        if not self.temp.exists():
            return 0
        for pat in patterns:
            for p in self.temp.glob(pat):
                if p.is_file():
                    p.unlink()
                    n += 1
        if not keep_dir and self.temp.exists() and not any(self.temp.iterdir()):
            self.temp.rmdir()
        return n

    def cleanup(self, keep_log: bool = True) -> dict:
        """收尾清理：删 temp 中间文件；默认保留 run.log.jsonl/run.state.json。"""
        n = self.clean_temp(("*",), keep_dir=False)
        removed = []
        for p in self.dir.glob("**/*.tmp"):
            p.unlink(missing_ok=True)
            removed.append(str(p))
        return {"temp_removed": n, "tmp_removed": len(removed)}


def create_run(product: str, root: str | Path = "storge/project") -> dict:
    return RunWorkspace(root, product).create()
