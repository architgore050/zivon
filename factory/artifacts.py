"""Run artifacts: every pipeline run writes a complete, inspectable record.

Layout (gitignored under runs/):

    runs/<run_id>/
      status.json              # per-stage state, updated as the run progresses
      run_report.json          # written by the orchestrator at the end
      00-ingest/
        output.json            # stage result (also passed to the next stage in memory)
        attempts/              # for model stages: attempt-01/{request.json, response.json, meta.json}
                               # meta.json carries latency, token usage, sampling, char counts
      01-locate/output.json
      ...

Timing (2026-11-04 observability pass): every stage transition prints a
progress line (`[NN-stage] starting` / `[NN-stage] ok in 12.3s (detail)`) and
every status.json stage entry carries `at` plus `elapsed_s` for measured runs;
run_report.json collects the per-stage `stage_durations_s` so "where does a
run spend its time" is answerable from the artifacts alone.

Ledgers (2026-11-08, founder's logging ask): append-only JSONL evidence files
(`calls_ledger.jsonl`, `issues_ledger.jsonl`) record what every model attempt
burned (latency, thinking proxy, tokens, finish reason, rejection reason) and
what every reviewer actually found (severity + category + block). run_report
rolls both up; `scripts/issue_report.py` aggregates them across runs so
"which failure classes keep recurring" becomes answerable - the input to
prompting improvements.

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
        # accumulated measured wall-time per stage (multi-round stages add up)
        self._stage_elapsed: dict[str, float] = {}

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

    # -- ledgers (2026-11-08, founder's logging ask) --------------------------
    def append_ledger(self, name: str, entries: list[dict[str, Any]]) -> None:
        """Append structured evidence lines to runs/<run_id>/<name>.jsonl.

        Two ledgers exist per run:
        - calls_ledger: one line per model call attempt (latency, time-to-
          first-content-token as the thinking proxy, token usage, finish
          reason, rejection reason) - what the model burned and why a call
          was rejected;
        - issues_ledger: one line per reviewer-found issue (stage, call,
          severity, category, block, message) - what the agents actually
          catch, so cross-run analysis can name recurring failure classes.
        Append-only JSONL: survives pod death, resumable runs keep adding,
        and scripts/issue_report.py aggregates them across runs.
        """
        if not entries:
            return
        path = self.dir / f"{name}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for entry in entries:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

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
        """Record a stage transition, print it, and measure stage wall-time.

        The progress print is the run's live heartbeat for whoever is watching
        `kubectl logs`; the measured `elapsed_s` (status.json) plus
        `stage_durations_s` (run_report.json) make per-stage timing auditable
        after the fact. Multi-round stages (03-check, 09-review) accumulate
        across rounds; resumed stages carry over the previous attempt's
        measured time.
        """
        now = time.time()
        status: dict[str, Any] = {
            "run_id": self.run_id,
            "started_at": self._t0,
            "stages": {},
        }
        if self._status_path.exists():
            status = json.loads(self._status_path.read_text(encoding="utf-8"))
        status.setdefault("run_id", self.run_id)
        status.setdefault("started_at", self._t0)
        stages = status.setdefault("stages", {})
        prev = stages.get(stage_id, {})
        entry: dict[str, Any] = {"state": state, "detail": detail, "at": now}
        elapsed: float | None = None
        if state == "running":
            # a re-running round inherits the earlier rounds' accumulated time
            if "elapsed_s" in prev:
                self._stage_elapsed.setdefault(stage_id, prev["elapsed_s"])
        elif state in ("ok", "failed"):
            if prev.get("state") == "running":
                elapsed = round(now - float(prev["at"]), 1)
            elif "elapsed_s" in prev:
                elapsed = prev["elapsed_s"]  # resumed: inherit the measured time
            if elapsed is not None:
                entry["elapsed_s"] = elapsed
                self._stage_elapsed[stage_id] = round(
                    self._stage_elapsed.get(stage_id, 0.0) + elapsed, 1
                )
        stages[stage_id] = entry
        self.write_json(self._status_path, status)
        self._print_stage(stage_id, state, detail, elapsed)

    @staticmethod
    def _print_stage(
        stage_id: str, state: str, detail: str, elapsed: float | None
    ) -> None:
        """Live progress line: one per stage transition, on stdout."""
        if state == "running":
            print(f"[{stage_id}] starting")
            return
        timing = f" in {elapsed}s" if elapsed is not None else ""
        suffix = f" ({detail})" if detail else ""
        print(f"[{stage_id}] {state}{timing}{suffix}")

    def finish(self, ok: bool, detail: str = "") -> None:
        status: dict[str, Any] = {}
        if self._status_path.exists():
            try:
                status = json.loads(self._status_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        self.write_json(
            self.dir / "run_report.json",
            {
                "run_id": self.run_id,
                "ok": ok,
                "detail": detail,
                "started_at": status.get("started_at", self._t0),
                "completed_at": round(time.time(), 1),
                "duration_s": round(time.time() - self._t0, 1),
                "stage_durations_s": {
                    stage: round(seconds, 1)
                    for stage, seconds in sorted(self._stage_elapsed.items())
                },
                # Ledger rollups (2026-11-08): the run answers "what did the
                # model burn, and what did the reviewers actually find" from
                # its own artifacts, without reading raw attempt files.
                "model_call_stats": self._calls_ledger_summary(),
                "issues_found": self._issues_ledger_summary(),
            },
        )

    # -- ledger rollups --------------------------------------------------------
    def _read_ledger(self, name: str) -> list[dict[str, Any]]:
        path = self.dir / f"{name}.jsonl"
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a torn append line must not break the report
        return rows

    def _calls_ledger_summary(self) -> dict[str, Any]:
        """Per-stage model-call stats from calls_ledger.jsonl.

        An attempt can appear twice (answered, then rejected by validation);
        the final state per (stage, round_tag, attempt) wins: rejected beats
        answered. thinking_s sums time-to-first-content-token - the honest
        proxy for how long a call thought before answering (a thinking model
        streams nothing until then).
        """
        final: dict[tuple[str, str, int], dict[str, Any]] = {}
        for row in self._read_ledger("calls_ledger"):
            key = (
                str(row.get("stage", "?")),
                str(row.get("round_tag") or ""),
                int(row.get("attempt") or 0),
            )
            prev = final.get(key)
            if prev is None or row.get("outcome") in ("rejected", "transport-failure"):
                final[key] = row
        by_stage: dict[str, dict[str, Any]] = {}
        for row in final.values():
            stats = by_stage.setdefault(
                str(row.get("stage", "?")),
                {
                    "attempts": 0,
                    "rejected": 0,
                    "transport_failures": 0,
                    "thinking_s": 0.0,
                    "max_completion_tokens": 0,
                },
            )
            stats["attempts"] += 1
            outcome = row.get("outcome")
            if outcome == "rejected":
                stats["rejected"] += 1
            elif outcome == "transport-failure":
                stats["transport_failures"] += 1
            first = row.get("first_token_s")
            if isinstance(first, (int, float)):
                stats["thinking_s"] = round(stats["thinking_s"] + first, 1)
            completion = row.get("completion_tokens")
            if isinstance(completion, (int, float)):
                stats["max_completion_tokens"] = max(
                    stats["max_completion_tokens"], int(completion)
                )
        return dict(sorted(by_stage.items()))

    def _issues_ledger_summary(self) -> dict[str, Any]:
        rows = self._read_ledger("issues_ledger")
        by_stage: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        by_category: dict[str, int] = {}
        unverified = 0
        for row in rows:
            by_stage[str(row.get("stage", "?"))] = (
                by_stage.get(str(row.get("stage", "?")), 0) + 1
            )
            sev = str(row.get("severity", "?"))
            by_severity[sev] = by_severity.get(sev, 0) + 1
            cat = str(row.get("category") or "other")
            by_category[cat] = by_category.get(cat, 0) + 1
            if row.get("unverified"):
                unverified += 1
        return {
            "total": len(rows),
            "unverified": unverified,
            "by_stage": dict(sorted(by_stage.items())),
            "by_severity": dict(sorted(by_severity.items())),
            "by_category": dict(sorted(by_category.items())),
        }

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
        status: dict[str, Any] = {
            "run_id": self.run_id,
            "started_at": self._t0,
            "stages": {},
        }
        if self._status_path.exists():
            try:
                status = json.loads(self._status_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass  # corrupt status file: rebuild it, the outputs are what matter
        status.setdefault("run_id", self.run_id)
        # started_at is the run's origin stamp: written on FIRST apply and then
        # preserved (it was being dropped on resume until 2026-11-04).
        status.setdefault("started_at", self._t0)
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
