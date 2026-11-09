"""Dual-write Eval Result Store (`evals/store.py`).

Implements `ADR-0027` and `docs/backend/db-spec.md` §3.16–3.20:
- Tier 1: Append-only JSONL ledgers under `evals_runs/` (`eval_runs_ledger.jsonl`,
  `human_edits_ledger.jsonl`, `kid_sessions_ledger.jsonl`) + per-run artifact
  directories and C4 `.tar.zst` outbox archive helper.
- Tier 2: Relational store (`eval_run`, `eval_card_result`,
  `eval_defect_sample_result`, `eval_human_edit`, `eval_kid_session`) with
  RFC 9562 UUIDv7 primary keys, supporting PostgreSQL (`postgresql://`) as well
  as SQLite (`sqlite:///`) for offline verification of relational DDL and
  idempotent `backfill-db` replay.
"""

from __future__ import annotations

import difflib
import json
import re
import secrets
import sqlite3
import subprocess
import tarfile
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import EvalConfig
from .models import (
    HUMAN_EDIT_SCHEMA,
    KID_SESSION_SCHEMA,
    CardResult,
    DefectSampleResult,
    EvalRunReport,
    HumanEditRecord,
    KidSessionRecord,
    validate_schema,
)
from .telemetry import ErrorClass, Severity, emit_eval_event

_PII_FORBIDDEN_KEYS = frozenset(
    {
        "name",
        "student_name",
        "child_name",
        "full_name",
        "first_name",
        "last_name",
        "email",
        "phone",
        "mobile",
        "dob",
        "date_of_birth",
        "birth_date",
        "age",
        "school",
        "school_name",
        "address",
        "ip",
        "ip_address",
        "device_id",
        "aadhaar",
    }
)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?:\+91[\s-]?)?[6-9]\d{9}\b")


def generate_uuid7(ts_ms: int | None = None) -> str:
    """Generate an RFC 9562 time-ordered UUIDv7 string."""
    unix_ts_ms = int(time.time() * 1000) if ts_ms is None else int(ts_ms)
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    uuid_int = (unix_ts_ms & ((1 << 48) - 1)) << 80
    uuid_int |= 0x7 << 76
    uuid_int |= (rand_a & 0xFFF) << 64
    uuid_int |= 0b10 << 62
    uuid_int |= rand_b & ((1 << 62) - 1)
    return str(uuid.UUID(int=uuid_int))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_kid_session_dpdp(payload: dict[str, Any]) -> None:
    """Enforce DPDP Act 2023 child-privacy guardrails on `KidSessionRecord` payloads."""
    bad_keys = sorted(set(payload.keys()) & _PII_FORBIDDEN_KEYS)
    if bad_keys:
        raise ValueError(
            f"DPDP privacy violation: forbidden child PII field(s) {bad_keys} in kid session"
        )
    validate_schema(payload, KID_SESSION_SCHEMA, "KidSessionRecord")
    notes = str(payload.get("notes", ""))
    if _EMAIL_RE.search(notes) or _PHONE_RE.search(notes):
        raise ValueError(
            "DPDP privacy violation: notes field contains an email address or phone number"
        )


def _card_Result_from_dict(d: dict[str, Any]) -> CardResult:
    samples = [
        DefectSampleResult(**s) for s in d.get("defect_samples", [])
    ]
    return CardResult(
        card_id=d["card_id"],
        stage=d["stage"],
        topic_slug=d.get("topic_slug"),
        verdict=d["verdict"],
        deterministic_score=float(d["deterministic_score"]),
        judge_score=(
            float(d["judge_score"]) if d.get("judge_score") is not None else None
        ),
        fatal_count=int(d.get("fatal_count", 0)),
        major_count=int(d.get("major_count", 0)),
        minor_count=int(d.get("minor_count", 0)),
        unverified_count=int(d.get("unverified_count", 0)),
        model_calls=int(d.get("model_calls", 0)),
        thinking_s=float(d.get("thinking_s", 0.0)),
        max_completion_tokens=int(d.get("max_completion_tokens", 0)),
        length_cuts=int(d.get("length_cuts", 0)),
        metrics=dict(d.get("metrics", {})),
        delta_vs_baseline=dict(d.get("delta_vs_baseline", {})),
        issues=list(d.get("issues", [])),
        defect_samples=samples,
        target_scope_label=str(d.get("target_scope_label", "")),
    )


def eval_run_report_from_dict(d: dict[str, Any]) -> EvalRunReport:
    return EvalRunReport(
        eval_run_id=d["eval_run_id"],
        suite=d["suite"],
        pipeline_version=int(d.get("pipeline_version", 1)),
        factory_image_tag=str(d.get("factory_image_tag", "0.3.17")),
        git_sha=d["git_sha"],
        prompt_bundle_sha256=d["prompt_bundle_sha256"],
        generator_model=d["generator_model"],
        judge_model=d["judge_model"],
        started_at=d["started_at"],
        completed_at=d["completed_at"],
        duration_s=float(d["duration_s"]),
        overall_pass=bool(d["overall_pass"]),
        regression_detected=bool(d.get("regression_detected", False)),
        baseline_eval_run_id=d.get("baseline_eval_run_id"),
        summary=dict(d["summary"]),
        cards=[_card_Result_from_dict(c) for c in d.get("cards", [])],
        schema_version=int(d.get("schema_version", 1)),
    )


class EvalStore:
    """Manages JSONL ledger persistence, relational dual-write, and outbox backfill."""

    def __init__(self, cfg: EvalConfig) -> None:
        self.cfg = cfg
        self.evals_runs_dir = cfg.evals_runs_dir
        self.evals_runs_dir.mkdir(parents=True, exist_ok=True)

    @property
    def runs_ledger(self) -> Path:
        return self.evals_runs_dir / "eval_runs_ledger.jsonl"

    @property
    def human_edits_ledger(self) -> Path:
        return self.evals_runs_dir / "human_edits_ledger.jsonl"

    @property
    def kid_sessions_ledger(self) -> Path:
        return self.evals_runs_dir / "kid_sessions_ledger.jsonl"

    @property
    def outbox_dir(self) -> Path:
        path = self.evals_runs_dir / "outbox"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _append_jsonl(self, path: Path, row: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(row, ensure_ascii=False, sort_keys=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.is_file():
            return []
        rows: list[dict[str, Any]] = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            stripped = raw.strip()
            if stripped:
                rows.append(json.loads(stripped))
        return rows

    def persist_run(self, report: EvalRunReport) -> dict[str, Any]:
        """Persist an `EvalRunReport` to JSONL ledger, per-run directory, and optional DB."""
        report_dict = report.to_dict()
        self._append_jsonl(self.runs_ledger, report_dict)

        run_dir = self.evals_runs_dir / report.eval_run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "eval_report.json").write_text(
            json.dumps(report_dict, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        backend_used = "jsonl"
        db_synced = False
        if self.cfg.store_backend in ("dual", "postgres") and self.cfg.db_url:
            try:
                self._persist_run_relational(report)
                backend_used = self.cfg.store_backend
                db_synced = True
            except Exception as exc:
                bundle = self.create_outbox_bundle(report.eval_run_id)
                emit_eval_event(
                    "EVT-EVAL-RUN-COMPLETED",
                    {
                        "eval_run_id": report.eval_run_id,
                        "store_degraded_to_jsonl": True,
                        "outbox_bundle": bundle.name,
                        "db_error": str(exc),
                    },
                    severity=Severity.WARNING,
                    error_class=ErrorClass.store_error,
                    run_id=report.eval_run_id,
                    fallback_dir=self.evals_runs_dir,
                )
                if self.cfg.store_backend == "postgres":
                    raise

        return {
            "eval_run_id": report.eval_run_id,
            "backend": backend_used,
            "db_synced": db_synced,
            "run_dir": str(run_dir),
        }

    def create_outbox_bundle(self, eval_run_id: str) -> Path:
        """Package a run directory into `evals_runs/outbox/<eval_run_id>.tar.zst` (ADR-0027 C4)."""
        run_dir = self.evals_runs_dir / eval_run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        tar_path = self.outbox_dir / f"{eval_run_id}.tar"
        zst_path = self.outbox_dir / f"{eval_run_id}.tar.zst"
        with tarfile.open(tar_path, "w") as tf:
            for item in sorted(run_dir.rglob("*")):
                if item.is_file():
                    tf.add(item, arcname=f"{eval_run_id}/{item.relative_to(run_dir)}")
        try:
            res = subprocess.run(
                ["zstd", "-q", "-f", str(tar_path), "-o", str(zst_path)],
                check=False,
                capture_output=True,
            )
            if res.returncode == 0 and zst_path.is_file():
                tar_path.unlink(missing_ok=True)
                return zst_path
        except FileNotFoundError:
            pass
        with tarfile.open(zst_path, "w:gz") as gzf:
            for item in sorted(run_dir.rglob("*")):
                if item.is_file():
                    gzf.add(item, arcname=f"{eval_run_id}/{item.relative_to(run_dir)}")
        tar_path.unlink(missing_ok=True)
        return zst_path

    def _ensure_sqlite_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS eval_run (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL UNIQUE,
                suite TEXT NOT NULL,
                git_sha TEXT NOT NULL,
                git_branch TEXT NOT NULL,
                trigger TEXT NOT NULL,
                code_model TEXT NOT NULL,
                judge_model TEXT NOT NULL,
                overall_verdict TEXT NOT NULL,
                total_cards INTEGER NOT NULL,
                passed_cards INTEGER NOT NULL,
                failed_cards INTEGER NOT NULL,
                skipped_cards INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                duration_ms INTEGER NOT NULL,
                summary JSON NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS eval_card_result (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES eval_run(id) ON DELETE CASCADE,
                card_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                tier TEXT NOT NULL,
                verdict TEXT NOT NULL,
                deterministic_score REAL NOT NULL,
                llm_judge_score REAL,
                metrics JSON NOT NULL DEFAULT '{}',
                thresholds_checked JSON NOT NULL DEFAULT '{}',
                issues JSON NOT NULL DEFAULT '[]',
                judge_calls INTEGER NOT NULL DEFAULT 0,
                judge_thinking_s REAL NOT NULL DEFAULT 0,
                max_completion_tokens INTEGER NOT NULL DEFAULT 0,
                length_cuts INTEGER NOT NULL DEFAULT 0,
                duration_ms INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE (run_id, card_id)
            );
            CREATE TABLE IF NOT EXISTS eval_defect_sample_result (
                id TEXT PRIMARY KEY,
                card_result_id TEXT NOT NULL REFERENCES eval_card_result(id) ON DELETE CASCADE,
                card_id TEXT NOT NULL,
                sample_id TEXT NOT NULL,
                defect_class TEXT NOT NULL,
                expected_verdict TEXT NOT NULL,
                actual_verdict TEXT NOT NULL,
                expected_severity TEXT,
                actual_max_severity TEXT,
                matched INTEGER NOT NULL,
                target_block_matched INTEGER NOT NULL,
                source_quoted INTEGER NOT NULL,
                latency_ms INTEGER NOT NULL DEFAULT 0,
                raw_response JSON NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                UNIQUE (card_result_id, sample_id)
            );
            CREATE TABLE IF NOT EXISTS eval_human_edit (
                id TEXT PRIMARY KEY,
                course_slug TEXT NOT NULL,
                topic_slug TEXT NOT NULL,
                baseline_git_sha TEXT NOT NULL,
                published_git_sha TEXT NOT NULL,
                files_changed INTEGER NOT NULL,
                lines_added INTEGER NOT NULL,
                lines_deleted INTEGER NOT NULL,
                total_lines INTEGER NOT NULL,
                edit_ratio REAL NOT NULL,
                zero_edit_publish INTEGER NOT NULL,
                per_file_diff JSON NOT NULL DEFAULT '{}',
                recorded_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS eval_kid_session (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL UNIQUE,
                course_slug TEXT NOT NULL,
                topic_slug TEXT NOT NULL,
                cohort_tag TEXT NOT NULL,
                device_profile TEXT NOT NULL,
                sections_viewed INTEGER NOT NULL,
                sections_total INTEGER NOT NULL,
                completed_lesson INTEGER NOT NULL,
                time_to_first_interaction_ms INTEGER NOT NULL,
                total_dwell_ms INTEGER NOT NULL,
                check_attempts INTEGER NOT NULL,
                check_passes_first_try INTEGER NOT NULL,
                sim_interactions INTEGER NOT NULL,
                abandoned_at_section TEXT,
                recorded_at TEXT NOT NULL
            );
            """
        )

    def _sqlite_path(self) -> Path:
        url = self.cfg.db_url or ""
        if url.startswith("sqlite:///"):
            return Path(url[len("sqlite:///") :])
        raise ValueError(f"Unsupported sqlite URL: {url}")

    def _persist_run_relational(self, report: EvalRunReport) -> None:
        url = self.cfg.db_url or ""
        run_uuid = generate_uuid7()
        overall_verdict = "pass" if report.overall_pass else "fail"
        total_cards = len(report.cards)
        passed_cards = sum(1 for c in report.cards if c.verdict == "pass")
        failed_cards = sum(1 for c in report.cards if c.verdict == "fail")
        skipped_cards = sum(1 for c in report.cards if c.verdict == "skip")
        duration_ms = max(0, int(report.duration_s * 1000))

        if url.startswith("sqlite:///"):
            db_path = self._sqlite_path()
            db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(db_path) as conn:
                self._ensure_sqlite_schema(conn)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO eval_run (
                        id, run_id, suite, git_sha, git_branch, trigger,
                        code_model, judge_model, overall_verdict,
                        total_cards, passed_cards, failed_cards, skipped_cards,
                        started_at, finished_at, duration_ms, summary
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_uuid,
                        report.eval_run_id,
                        report.suite,
                        report.git_sha,
                        "main",
                        "manual_cli",
                        report.generator_model,
                        report.judge_model,
                        overall_verdict,
                        total_cards,
                        passed_cards,
                        failed_cards,
                        skipped_cards,
                        report.started_at,
                        report.completed_at,
                        duration_ms,
                        json.dumps(report.summary, sort_keys=True),
                    ),
                )
                row = conn.execute(
                    "SELECT id FROM eval_run WHERE run_id = ?",
                    (report.eval_run_id,),
                ).fetchone()
                eff_run_uuid = row[0] if row else run_uuid

                for c in report.cards:
                    c_uuid = generate_uuid7()
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO eval_card_result (
                            id, run_id, card_id, stage, tier, verdict,
                            deterministic_score, llm_judge_score, metrics,
                            thresholds_checked, issues, judge_calls,
                            judge_thinking_s, max_completion_tokens,
                            length_cuts, duration_ms, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            c_uuid,
                            eff_run_uuid,
                            c.card_id,
                            c.stage,
                            "tier2_ReviewerCalibration"
                            if c.card_id.startswith("EV-REV")
                            else (
                                "tier3_OperationalAndOutcome"
                                if c.card_id in ("EV-E2E-001", "EV-KID-001")
                                else "tier1_Intrinsic"
                            ),
                            "skipped" if c.verdict == "skip" else c.verdict,
                            c.deterministic_score,
                            c.judge_score,
                            json.dumps(c.metrics, sort_keys=True),
                            json.dumps({}, sort_keys=True),
                            json.dumps(c.issues, sort_keys=True),
                            c.model_calls,
                            c.thinking_s,
                            c.max_completion_tokens,
                            c.length_cuts,
                            0,
                            report.completed_at,
                        ),
                    )
                    crow = conn.execute(
                        "SELECT id FROM eval_card_result WHERE run_id = ? AND card_id = ?",
                        (eff_run_uuid, c.card_id),
                    ).fetchone()
                    eff_c_uuid = crow[0] if crow else c_uuid
                    for s in c.defect_samples:
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO eval_defect_sample_result (
                                id, card_result_id, card_id, sample_id, defect_class,
                                expected_verdict, actual_verdict, expected_severity,
                                actual_max_severity, matched, target_block_matched,
                                source_quoted, latency_ms, raw_response, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                generate_uuid7(),
                                eff_c_uuid,
                                c.card_id,
                                s.sample_id,
                                s.outcome_class,
                                s.expected_verdict,
                                s.actual_verdict,
                                s.expected_severity,
                                s.actual_severity,
                                1 if s.expected_verdict == s.actual_verdict else 0,
                                1 if s.target_block_matched else 0,
                                1 if s.source_quoted else 0,
                                int(s.latency_s * 1000),
                                json.dumps({"details": s.details}),
                                report.completed_at,
                            ),
                        )
                conn.commit()
            return

        if url.startswith(("postgresql://", "postgres://")):
            try:
                import psycopg  # type: ignore[import-not-found]
            except ImportError as exc:
                raise RuntimeError(
                    "psycopg is required for postgresql:// ZIVON_DB_URL persistence"
                ) from exc
            with psycopg.connect(url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO eval_run (
                            id, run_id, suite, git_sha, git_branch, trigger,
                            code_model, judge_model, overall_verdict,
                            total_cards, passed_cards, failed_cards, skipped_cards,
                            started_at, finished_at, duration_ms, summary
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                        ON CONFLICT (run_id) DO NOTHING
                        """,
                        (
                            run_uuid,
                            report.eval_run_id,
                            report.suite,
                            report.git_sha,
                            "main",
                            "manual_cli",
                            report.generator_model,
                            report.judge_model,
                            overall_verdict,
                            total_cards,
                            passed_cards,
                            failed_cards,
                            skipped_cards,
                            report.started_at,
                            report.completed_at,
                            duration_ms,
                            json.dumps(report.summary, sort_keys=True),
                        ),
                    )
                conn.commit()
            return

        raise ValueError(f"Unsupported ZIVON_DB_URL scheme: {url!r}")

    def backfill_db(self) -> dict[str, int]:
        """Idempotently replay all JSONL ledger rows into the relational store (`ADR-0027`)."""
        if not self.cfg.db_url:
            raise ValueError("ZIVON_DB_URL / EVAL_DB_URL must be configured to run backfill-db")

        runs = self._read_jsonl(self.runs_ledger)
        edits = self._read_jsonl(self.human_edits_ledger)
        sessions = self._read_jsonl(self.kid_sessions_ledger)
        cards_count = 0
        samples_count = 0

        for r in runs:
            rep = eval_run_report_from_dict(r)
            cards_count += len(rep.cards)
            samples_count += sum(len(c.defect_samples) for c in rep.cards)
            self._persist_run_relational(rep)

        if self.cfg.db_url.startswith("sqlite:///"):
            with sqlite3.connect(self._sqlite_path()) as conn:
                self._ensure_sqlite_schema(conn)
                for e in edits:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO eval_human_edit (
                            id, course_slug, topic_slug, baseline_git_sha,
                            published_git_sha, files_changed, lines_added,
                            lines_deleted, total_lines, edit_ratio,
                            zero_edit_publish, per_file_diff, recorded_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            e.get("id") or generate_uuid7(),
                            e["course_id"],
                            e["topic_slug"],
                            e.get("generated_git_sha", "0" * 40),
                            e.get("published_git_sha", "0" * 40),
                            int(e.get("human_edits_count", 0)),
                            int(e["manual_added_lines"]),
                            int(e["manual_deleted_lines"]),
                            int(e["total_generated_lines"]),
                            float(e["human_edit_rate"]),
                            1 if float(e["human_edit_rate"]) == 0.0 else 0,
                            json.dumps({"categories": e.get("edit_categories", [])}),
                            e["recorded_at"],
                        ),
                    )
                for k in sessions:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO eval_kid_session (
                            id, session_id, course_slug, topic_slug, cohort_tag,
                            device_profile, sections_viewed, sections_total,
                            completed_lesson, time_to_first_interaction_ms,
                            total_dwell_ms, check_attempts, check_passes_first_try,
                            sim_interactions, abandoned_at_section, recorded_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            k.get("id") or generate_uuid7(),
                            k["session_code"],
                            f"class-{k['topic_class']}-physics",
                            k["topic_slug"],
                            f"class-{k['tester_class']}",
                            "weak-android",
                            4,
                            4,
                            1 if k["gate_b_pass"] else 0,
                            10000,
                            180000,
                            2,
                            (1 if k["followup_1_correct"] else 0)
                            + (1 if k["followup_2_correct"] else 0),
                            1,
                            k["confusion_blocks"][0] if k.get("confusion_blocks") else None,
                            k["recorded_at"],
                        ),
                    )
                conn.commit()

        return {
            "runs": len(runs),
            "card_results": cards_count,
            "defect_samples": samples_count,
            "human_edits": len(edits),
            "kid_sessions": len(sessions),
        }

    def load_run(self, run_id_or_path: str | Path) -> EvalRunReport:
        """Load an `EvalRunReport` from a run directory, JSON file, or `eval_run_id`."""
        candidate = Path(run_id_or_path)
        if candidate.is_dir() and (candidate / "eval_report.json").is_file():
            data = json.loads((candidate / "eval_report.json").read_text(encoding="utf-8"))
            return eval_run_report_from_dict(data)
        if candidate.is_file():
            data = json.loads(candidate.read_text(encoding="utf-8"))
            return eval_run_report_from_dict(data)

        run_dir = self.evals_runs_dir / str(run_id_or_path)
        if (run_dir / "eval_report.json").is_file():
            data = json.loads((run_dir / "eval_report.json").read_text(encoding="utf-8"))
            return eval_run_report_from_dict(data)

        for row in reversed(self._read_jsonl(self.runs_ledger)):
            if row.get("eval_run_id") == str(run_id_or_path):
                return eval_run_report_from_dict(row)

        raise FileNotFoundError(f"Run report not found for {run_id_or_path!r}")

    def list_runs(self) -> list[dict[str, Any]]:
        return self._read_jsonl(self.runs_ledger)

    def record_human_edit(
        self,
        *,
        course_id: str,
        topic_slug: str,
        class_level: int = 9,
        factory_run_id: str = "run-manual",
        pipeline_version: int = 1,
        baseline_dir: Path,
        published_dir: Path,
        generated_git_sha: str = "0" * 40,
        published_git_sha: str = "0" * 40,
        notes: str = "",
    ) -> HumanEditRecord:
        """Compare pipeline output against published files and record `HumanEditRecord`."""
        tracked_names = ("index.html", "page.css", "page.js", "plan.json")
        lines_added = 0
        lines_deleted = 0
        total_lines = 0
        files_changed = 0
        categories: list[str] = []

        for name in tracked_names:
            base_file = baseline_dir / name
            pub_file = published_dir / name
            if not base_file.is_file() and not pub_file.is_file():
                continue
            base_lines = (
                base_file.read_text(encoding="utf-8").splitlines()
                if base_file.is_file()
                else []
            )
            pub_lines = (
                pub_file.read_text(encoding="utf-8").splitlines()
                if pub_file.is_file()
                else []
            )
            total_lines += max(len(base_lines), len(pub_lines))
            added = 0
            deleted = 0
            for diff_line in difflib.ndiff(base_lines, pub_lines):
                if diff_line.startswith("+ "):
                    added += 1
                elif diff_line.startswith("- "):
                    deleted += 1
            if added > 0 or deleted > 0:
                files_changed += 1
                categories.append(name)
            lines_added += added
            lines_deleted += deleted

        denom = max(1, total_lines)
        edit_rate = round((lines_added + lines_deleted) / denom, 4)

        rec = HumanEditRecord(
            id=generate_uuid7(),
            topic_slug=topic_slug,
            course_id=course_id,
            class_level=class_level,
            factory_run_id=factory_run_id,
            pipeline_version=pipeline_version,
            total_generated_lines=denom,
            manual_added_lines=lines_added,
            manual_deleted_lines=lines_deleted,
            human_edit_rate=edit_rate,
            human_edits_count=files_changed,
            edit_categories=categories,
            notes=notes,
            recorded_at=utc_now_iso(),
            generated_git_sha=generated_git_sha,
            published_git_sha=published_git_sha,
        )
        row = rec.to_dict()
        self._append_jsonl(self.human_edits_ledger, row)
        emit_eval_event(
            "EVT-EVAL-HUMAN-EDIT-RECORDED",
            {
                "topic_slug": topic_slug,
                "course_id": course_id,
                "human_edit_rate": edit_rate,
                "manual_added_lines": lines_added,
                "manual_deleted_lines": lines_deleted,
            },
            fallback_dir=self.evals_runs_dir,
        )
        return rec

    def record_kid_session(self, payload: dict[str, Any]) -> KidSessionRecord:
        """Validate a kid comprehension session for DPDP compliance and append to ledger."""
        validate_kid_session_dpdp(payload)
        rec = KidSessionRecord(
            id=str(payload.get("id") or generate_uuid7()),
            session_code=str(payload["session_code"]),
            topic_slug=str(payload["topic_slug"]),
            tester_class=int(payload["tester_class"]),
            topic_class=int(payload["topic_class"]),
            is_above_class_level=bool(payload["is_above_class_level"]),
            restated_in_own_words=bool(payload["restated_in_own_words"]),
            followup_1_correct=bool(payload["followup_1_correct"]),
            followup_2_correct=bool(payload["followup_2_correct"]),
            gate_b_pass=bool(payload["gate_b_pass"]),
            confusion_blocks=list(payload.get("confusion_blocks", [])),
            promoted_defect_id=payload.get("promoted_defect_id"),
            notes=str(payload.get("notes", "")),
            recorded_at=str(payload.get("recorded_at") or utc_now_iso()),
            consent_record_id=payload.get("consent_record_id"),
            lesson_version_id=payload.get("lesson_version_id"),
        )
        row = rec.to_dict()
        self._append_jsonl(self.kid_sessions_ledger, row)
        emit_eval_event(
            "EVT-EVAL-KID-SESSION-LOGGED",
            {
                "session_code": rec.session_code,
                "topic_slug": rec.topic_slug,
                "gate_b_pass": rec.gate_b_pass,
                "promoted_defect_id": rec.promoted_defect_id,
            },
            fallback_dir=self.evals_runs_dir,
        )
        return rec
