"""Run artifacts: every pipeline run writes a complete, inspectable record.

Layout (gitignored under runs/):

    runs/<run_id>/
      status.json              # per-stage state, updated as the run progresses
      run_report.json          # written by the orchestrator at the end
      00-ingest/
        output.json            # stage result (also passed to the next stage in memory)
        attempts/              # for model stages: attempt-01/{request,response,parsed}.json + meta.json
      01-locate/output.json
      ...

Nothing downstream ever runs on a failed stage, and every model call's exact
request and response are on disk for diagnosis.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any


def slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "topic"


class RunContext:
    def __init__(self, runs_dir: Path, run_id: str):
        self.runs_dir = runs_dir
        self.run_id = run_id
        self.dir = runs_dir / run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self._status_path = self.dir / "status.json"
        self._t0 = time.time()

    # -- stage artifact dirs -------------------------------------------------
    def stage_dir(self, stage_id: str) -> Path:
        d = self.dir / stage_id
        (d / "attempts").mkdir(parents=True, exist_ok=True)
        return d

    def attempts_dir(self, stage_id: str) -> Path:
        d = self.stage_dir(stage_id) / "attempts"
        d.mkdir(exist_ok=True)
        return d

    # -- writers -------------------------------------------------------------
    def write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def write_text(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def save_stage_output(self, stage_id: str, output: Any) -> None:
        self.write_json(self.stage_dir(stage_id) / "output.json", output)

    def load_stage_output(self, stage_id: str) -> Any:
        path = self.stage_dir(stage_id) / "output.json"
        if not path.exists():
            raise FileNotFoundError(f"missing artifact for stage {stage_id}: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    # -- status ---------------------------------------------------------------
    def mark_stage(self, stage_id: str, state: str, detail: str = "") -> None:
        status: dict[str, Any] = {
            "run_id": self.run_id,
            "started_at": self._t0,
            "stages": {},
        }
        if self._status_path.exists():
            status = json.loads(self._status_path.read_text(encoding="utf-8"))
        status.setdefault("stages", {})[stage_id] = {
            "state": state,
            "detail": detail,
            "at": time.time(),
        }
        self.write_json(self._status_path, status)

    def finish(self, ok: bool, detail: str = "") -> None:
        self.write_json(
            self.dir / "run_report.json",
            {
                "run_id": self.run_id,
                "ok": ok,
                "detail": detail,
                "duration_s": round(time.time() - self._t0, 1),
            },
        )
