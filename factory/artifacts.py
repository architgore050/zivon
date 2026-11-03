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
request and response are on disk for diagnosis. Partial re-runs read upstream
stage outputs from the latest previous run (see load_stage_output).

Resume (graph v2): a run id is deterministic per (chapter, class), so a
re-triggered run reuses the stage outputs of the previous attempt instead of
re-deriving them - a late-stage failure never re-runs the whole pipeline.
status.json carries a fingerprint of the run's inputs (pipeline version,
chapter, class, model, config); a mismatch refuses resume and tells the
operator to pass --fresh.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

from .errors import MissingArtifactError


def slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "topic"


def wipe_run(runs_dir: Path, run_id: str) -> bool:
    """Delete a previous run dir (--fresh). Returns whether something was removed."""
    target = runs_dir / run_id
    if target.exists():
        shutil.rmtree(target)
        return True
    return False


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
        """Read a stage's output.json for this run.

        Partial re-runs (--stages 05-check,07-render) need upstream artifacts
        this run did not produce. Fallback, as promised by the runbook: take
        the artifact from the LATEST previous run that has it, copy it into
        this run's stage dir (so every run stays self-contained and
        inspectable), and print loudly where it came from. Use --run-id to
        pin which run you mean. If no run has it, fail with instructions.
        """
        path = self.stage_dir(stage_id) / "output.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))

        source = self._latest_previous_run_output(stage_id)
        if source is None:
            raise MissingArtifactError(
                f"stage {stage_id} needs the output of stage {stage_id}, but "
                f"neither this run nor any previous run under {self.runs_dir} "
                "has it. Run the earlier stages first, e.g. "
                f"python pipeline.py <topic> --stages 00-ingest,...,{stage_id} "
                "(see docs/content-factory/runbook.md)."
            )
        shutil.copy2(source, path)
        print(
            f"[artifacts] stage {stage_id}: no output in run '{self.run_id}'; "
            f"using run '{source.parent.parent.name}' ({source}) - copied to {path}"
        )
        return json.loads(path.read_text(encoding="utf-8"))

    def _latest_previous_run_output(self, stage_id: str) -> Path | None:
        """Newest output.json for stage_id among sibling run dirs."""
        if not self.runs_dir.exists():
            return None
        candidates: list[tuple[float, str, Path]] = []
        for run_dir in self.runs_dir.iterdir():
            if not run_dir.is_dir() or run_dir.name == self.run_id:
                continue
            candidate = run_dir / stage_id / "output.json"
            if candidate.exists():
                candidates.append((candidate.stat().st_mtime, run_dir.name, candidate))
        if not candidates:
            return None
        # newest first; run name breaks ties (run ids are time-ordered)
        candidates.sort()
        return candidates[-1][2]

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

    # -- resume support -------------------------------------------------------
    def status_exists(self) -> bool:
        return self._status_path.exists()

    def get_fingerprint(self) -> str | None:
        if not self._status_path.exists():
            return None
        try:
            return json.loads(self._status_path.read_text(encoding="utf-8")).get(
                "fingerprint"
            )
        except json.JSONDecodeError:
            return None

    def set_fingerprint(self, fingerprint: str) -> None:
        status: dict[str, Any] = {"run_id": self.run_id, "stages": {}}
        if self._status_path.exists():
            try:
                status = json.loads(self._status_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass  # corrupt status file: rebuild it, the outputs are what matter
        status["fingerprint"] = fingerprint
        self.write_json(self._status_path, status)

    def stage_ok(self, stage_id: str) -> bool:
        """Resumable: the stage finished ok AND its output artifact is on disk."""
        if not self._status_path.exists():
            return False
        try:
            status = json.loads(self._status_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False
        entry = status.get("stages", {}).get(stage_id, {})
        return (
            entry.get("state") == "ok"
            and (self.dir / stage_id / "output.json").exists()
        )
