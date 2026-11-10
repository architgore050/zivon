"""Admin surface API-A1 through API-A10 under `/v1/admin/*` (backend-spec §6.3).

Cluster-side, authenticated via constant-time admin token comparison (ADR-0026).
Enforces NFR-30 (aggregate-only display; transcripts are never returned on admin
panels) and script-parity for A7/A8/A9 (`trigger-tests.sh`,
`trigger-factory-run.sh`, `logs-factory-run.sh`).
"""

from __future__ import annotations

import datetime
import hmac
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from db.uuid7 import uuid7_str

from ..config import BackendConfig
from ..errors import APIError
from ..logging_shim import ErrorClass, Severity, log_event

router = APIRouter(prefix="/v1/admin")


def _utc_now_iso() -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _today_str() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def require_admin_auth(
    request: Request,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> str:
    """FastAPI dependency enforcing fail-closed constant-time admin token auth."""
    cfg: BackendConfig = request.app.state.config
    expected = cfg.admin_token
    if not expected:
        log_event(
            "dashboard.auth_unconfigured",
            {"secret_present": False},
            severity=Severity.CRITICAL,
            error_class=ErrorClass.AUTH_ERROR,
        )
        raise APIError("E-SERVICE-UNAVAILABLE", status_code=503, retryable=False)

    candidate = ""
    if authorization and authorization.lower().startswith("bearer "):
        candidate = authorization.split(" ", 1)[1].strip()
    elif x_admin_token:
        candidate = x_admin_token.strip()

    if not candidate or not hmac.compare_digest(
        candidate.encode("utf-8"), expected.encode("utf-8")
    ):
        log_event(
            "dashboard.auth_failure",
            {"ip_truncated": "redacted", "attempts": 1},
            severity=Severity.WARNING,
            error_class=ErrorClass.AUTH_ERROR,
        )
        raise APIError("E-UNAUTHORIZED", status_code=401, retryable=False)

    return "admin"


@router.get("/summary")
def admin_summary(
    request: Request,
    _actor: str = Depends(require_admin_auth),
) -> JSONResponse:
    """API-A1: Sessions today, credit burn, guard state, engagement aggregates, open reports."""
    db = request.app.state.db
    today = _today_str()

    sess_row = db.fetchone(
        "SELECT COUNT(*) AS cnt, COALESCE(SUM(turn_count), 0) AS turns FROM session WHERE substr(started_at, 1, 10) = ?",
        (today,),
    )
    ev_row = db.fetchone(
        "SELECT COUNT(*) AS cnt FROM telemetry_event WHERE substr(ts, 1, 10) = ?",
        (today,),
    )
    rep_row = db.fetchone(
        "SELECT COUNT(*) AS cnt FROM problem_report WHERE status = 'open'"
    )

    stt_row = db.fetchone(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM credit_ledger WHERE model = 'prisma' AND substr(created_at, 1, 10) = ?",
        (today,),
    )
    tts_row = db.fetchone(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM credit_ledger WHERE model = 'timbre' AND substr(created_at, 1, 10) = ?",
        (today,),
    )
    llm_row = db.fetchone(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM credit_ledger WHERE model = 'gemma_gpu' AND substr(created_at, 1, 10) = ?",
        (today,),
    )

    guard = getattr(request.app.state, "guard", None)
    if guard is not None:
        g_status = guard.get_status()
        guard_state = g_status.global_state
        guard_mode = g_status.mode
        credits_used = float(g_status.global_used)
    else:
        prof = db.fetchone("SELECT mode FROM guard_profile WHERE id = 1")
        guard_mode = str(prof["mode"]) if prof else "normal"
        gc = db.fetchone(
            "SELECT used_credits, state FROM guard_counter WHERE period = ? AND scope = 'global' AND scope_key = 'global'",
            (today,),
        )
        guard_state = str(gc["state"]) if gc else "ok"
        credits_used = float(gc["used_credits"]) if gc else 0.0

    return JSONResponse(
        content={
            "day": today,
            "sessions_today": int(sess_row["cnt"]) if sess_row else 0,
            "credit_burn": {
                "stt_seconds": float(stt_row["total"]) if stt_row else 0.0,
                "tts_chars": float(tts_row["total"]) if tts_row else 0.0,
                "llm_tokens": float(llm_row["total"]) if llm_row else 0.0,
                "credits_used": credits_used,
            },
            "guard_state": guard_state,
            "guard_profile_mode": guard_mode,
            "engagement": {
                "turns_today": int(sess_row["turns"]) if sess_row else 0,
                "events_today": int(ev_row["cnt"]) if ev_row else 0,
            },
            "open_reports_count": int(rep_row["cnt"]) if rep_row else 0,
        }
    )


@router.get("/sessions")
def admin_sessions(
    request: Request,
    date: str | None = Query(default=None),
    _actor: str = Depends(require_admin_auth),
) -> JSONResponse:
    """API-A2: Pseudonymous session rows (INF-096: id, topic, duration, turns — ZERO transcripts)."""
    db = request.app.state.db
    target_date = (date or _today_str()).strip()
    rows = db.fetchall(
        """
        SELECT session_id, course_id, class_level, lang, mode,
               started_at, ended_at, turn_count
        FROM session
        WHERE substr(started_at, 1, 10) = ?
        ORDER BY started_at DESC
        LIMIT 500
        """,
        (target_date,),
    )
    items: list[dict[str, Any]] = []
    for r in rows:
        items.append(
            {
                "session_id": r["session_id"],
                "topic": r["course_id"],
                "class_level": r["class_level"],
                "lang": r["lang"],
                "mode": r["mode"],
                "turns": int(r["turn_count"] or 0),
                "started_at": r["started_at"],
                "ended_at": r["ended_at"],
            }
        )
    return JSONResponse(content={"date": target_date, "sessions": items})


@router.get("/credits")
def admin_credits(
    request: Request,
    _actor: str = Depends(require_admin_auth),
) -> JSONResponse:
    """API-A3: Ledger totals, reconciliation drift %, and profile config."""
    db = request.app.state.db
    today = _today_str()
    guard = getattr(request.app.state, "guard", None)
    if guard is not None:
        return JSONResponse(content=guard.get_reconciliation_report(period=today))

    prof = db.fetchone("SELECT * FROM guard_profile WHERE id = 1") or {}
    gc = db.fetchone(
        "SELECT used_credits, state FROM guard_counter WHERE period = ? AND scope = 'global' AND scope_key = 'global'",
        (today,),
    )
    ledger_sum = db.fetchone(
        "SELECT COALESCE(SUM( COALESCE(cost_credits, 0) ), 0) AS total FROM credit_ledger WHERE substr(created_at, 1, 10) = ?",
        (today,),
    )
    counter_used = float(gc["used_credits"]) if gc else 0.0
    ledger_used = float(ledger_sum["total"]) if ledger_sum else 0.0
    denom = max(counter_used, ledger_used, 1.0)
    drift_pct = round(abs(counter_used - ledger_used) / denom * 100.0, 2)
    return JSONResponse(
        content={
            "period": today,
            "counter_used_credits": counter_used,
            "ledger_used_credits": ledger_used,
            "drift_pct": drift_pct,
            "drift_within_slo": drift_pct <= 2.0,
            "profile": {
                "mode": prof.get("mode", "normal"),
                "global_tranche": float(prof.get("global_tranche", 1000)),
                "per_user_cap": float(prof.get("per_user_cap", 30)),
                "demo_global_tranche": float(prof.get("demo_global_tranche", 1000)),
                "demo_per_user_cap": float(prof.get("demo_per_user_cap", 100)),
                "warn_threshold_pct": float(prof.get("warn_threshold_pct", 15)),
            },
        }
    )


@router.get("/guard")
def admin_get_guard(
    request: Request,
    _actor: str = Depends(require_admin_auth),
) -> JSONResponse:
    """API-A4 (GET): Read current credit guard state and profile configuration."""
    db = request.app.state.db
    guard = getattr(request.app.state, "guard", None)
    if guard is not None:
        status = guard.get_status()
        return JSONResponse(content=status.to_dict())

    prof = db.fetchone("SELECT * FROM guard_profile WHERE id = 1") or {}
    return JSONResponse(
        content={
            "mode": prof.get("mode", "normal"),
            "global_state": "ok",
            "global_used": 0.0,
            "global_cap": float(prof.get("global_tranche", 1000)),
            "per_user_cap": float(prof.get("per_user_cap", 30)),
            "warn_threshold_pct": float(prof.get("warn_threshold_pct", 15)),
        }
    )


class GuardProfileToggleRequest(BaseModel):
    mode: str


@router.post("/guard/profile")
def admin_toggle_guard_profile(
    body: GuardProfileToggleRequest,
    request: Request,
    actor: str = Depends(require_admin_auth),
) -> JSONResponse:
    """API-A4 (POST): Toggle guard profile (`normal` <-> `demo`), audit, and push state."""
    mode = body.mode.strip()
    if mode not in ("normal", "demo"):
        raise APIError("E-VALIDATION", status_code=422)

    guard = getattr(request.app.state, "guard", None)
    if guard is not None:
        status = guard.set_profile_mode(mode, actor=actor)
        return JSONResponse(content=status.to_dict())

    db = request.app.state.db
    prev = db.fetchone("SELECT mode FROM guard_profile WHERE id = 1")
    before_mode = str(prev["mode"]) if prev else "normal"
    now = _utc_now_iso()
    db.execute(
        "UPDATE guard_profile SET mode = ?, updated_at = ?, updated_by = ? WHERE id = 1",
        (mode, now, actor),
    )
    db.record_audit(
        actor=actor,
        action="guard_profile.flip",
        target="guard_profile",
        before_hash=before_mode,
        after_hash=mode,
    )
    return JSONResponse(content={"mode": mode, "updated_at": now, "updated_by": actor})


def _sync_runs_from_filesystem(db: Any, runs_dir: Path) -> None:
    """Index any run directories on disk (`runs/<run_id>/status.json`) into `factory_run`."""
    if not runs_dir.is_dir():
        return
    for status_file in runs_dir.glob("*/status.json"):
        try:
            run_dir = status_file.parent
            run_id = run_dir.name
            status_data = json.loads(status_file.read_text(encoding="utf-8"))
            report_file = run_dir / "run_report.json"
            durations: dict[str, Any] = {}
            if report_file.is_file():
                rep = json.loads(report_file.read_text(encoding="utf-8"))
                durations = rep.get("stage_durations_s") or {}
            verdict = "in_progress"
            if status_data.get("ok") is True:
                verdict = "pass"
            elif status_data.get("ok") is False:
                verdict = "fail"
            db.execute(
                """
                INSERT INTO factory_run (run_id, topic, class_level, stage, verdict, stage_durations, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (run_id) DO UPDATE SET
                    stage = excluded.stage,
                    verdict = excluded.verdict,
                    stage_durations = excluded.stage_durations,
                    ts = excluded.ts
                """,
                (
                    run_id,
                    status_data.get("chapter"),
                    status_data.get("class_level"),
                    status_data.get("current_stage"),
                    verdict,
                    json.dumps(durations),
                    _utc_now_iso(),
                ),
            )
        except Exception:
            continue


@router.get("/runs")
def admin_list_runs(
    request: Request,
    _actor: str = Depends(require_admin_auth),
) -> JSONResponse:
    """API-A5 (list): Factory run status rows + stage durations."""
    cfg: BackendConfig = request.app.state.config
    db = request.app.state.db
    _sync_runs_from_filesystem(db, Path(cfg.runs_dir))
    rows = db.fetchall(
        "SELECT run_id, topic, class_level, stage, verdict, stage_durations, ts FROM factory_run ORDER BY ts DESC LIMIT 50"
    )
    runs: list[dict[str, Any]] = []
    for r in rows:
        raw_dur = r.get("stage_durations")
        durations = (
            json.loads(raw_dur)
            if isinstance(raw_dur, str) and raw_dur
            else (raw_dur or {})
        )
        runs.append(
            {
                "run_id": r["run_id"],
                "topic": r["topic"],
                "class_level": r["class_level"],
                "stage": r["stage"],
                "verdict": r["verdict"],
                "stage_durations": durations,
                "ts": r["ts"],
            }
        )
    return JSONResponse(content={"runs": runs})


@router.get("/runs/{run_id}")
def admin_get_run(
    run_id: str,
    request: Request,
    _actor: str = Depends(require_admin_auth),
) -> JSONResponse:
    """API-A5 (detail): Single factory run status + stage durations."""
    cfg: BackendConfig = request.app.state.config
    db = request.app.state.db
    _sync_runs_from_filesystem(db, Path(cfg.runs_dir))
    r = db.fetchone(
        "SELECT run_id, topic, class_level, stage, verdict, stage_durations, ts FROM factory_run WHERE run_id = ?",
        (run_id,),
    )
    if r is None:
        raise APIError("E-NOT-FOUND", status_code=404)
    raw_dur = r.get("stage_durations")
    durations = (
        json.loads(raw_dur)
        if isinstance(raw_dur, str) and raw_dur
        else (raw_dur or {})
    )
    return JSONResponse(
        content={
            "run_id": r["run_id"],
            "topic": r["topic"],
            "class_level": r["class_level"],
            "stage": r["stage"],
            "verdict": r["verdict"],
            "stage_durations": durations,
            "ts": r["ts"],
        }
    )


@router.get("/reports")
def admin_list_reports(
    request: Request,
    status: str | None = Query(default=None),
    _actor: str = Depends(require_admin_auth),
) -> JSONResponse:
    """API-A6 (GET): Problem report inbox."""
    db = request.app.state.db
    if status:
        rows = db.fetchall(
            """
            SELECT report_id, course_id, class_level, block_id, category, text, status, created_at, resolved_at
            FROM problem_report
            WHERE status = ?
            ORDER BY created_at DESC
            """,
            (status.strip(),),
        )
    else:
        rows = db.fetchall(
            """
            SELECT report_id, course_id, class_level, block_id, category, text, status, created_at, resolved_at
            FROM problem_report
            ORDER BY created_at DESC
            """
        )
    return JSONResponse(content={"reports": rows})


class ReportStatusPatchRequest(BaseModel):
    status: str


@router.patch("/reports/{report_id}")
def admin_patch_report(
    report_id: str,
    body: ReportStatusPatchRequest,
    request: Request,
    actor: str = Depends(require_admin_auth),
) -> JSONResponse:
    """API-A6 (PATCH): Update problem report status (`open`|`fixed`|`shipped_next_run`)."""
    new_status = body.status.strip()
    if new_status not in ("open", "fixed", "shipped_next_run"):
        raise APIError("E-VALIDATION", status_code=422)

    db = request.app.state.db
    existing = db.fetchone(
        "SELECT report_id, status FROM problem_report WHERE report_id = ?",
        (report_id,),
    )
    if existing is None:
        raise APIError("E-NOT-FOUND", status_code=404)

    resolved_at = _utc_now_iso() if new_status in ("fixed", "shipped_next_run") else None
    db.execute(
        "UPDATE problem_report SET status = ?, resolved_at = ? WHERE report_id = ?",
        (new_status, resolved_at, report_id),
    )
    db.record_audit(
        actor=actor,
        action="report.status",
        target=report_id,
        before_hash=str(existing["status"]),
        after_hash=new_status,
    )
    return JSONResponse(
        content={
            "report_id": report_id,
            "status": new_status,
            "resolved_at": resolved_at,
        }
    )


@router.post("/actions/run-tests", status_code=202)
def admin_trigger_run_tests(
    request: Request,
    actor: str = Depends(require_admin_auth),
) -> JSONResponse:
    """API-A7: Wrap `scripts/trigger-tests.sh` semantics (parity-tested)."""
    db = request.app.state.db
    action_id = uuid7_str()
    script_path = "scripts/trigger-tests.sh"
    command = [script_path, "dashboard"]

    db.record_audit(
        actor=actor,
        action="trigger.run-tests",
        target=script_path,
        after_hash=action_id,
    )
    log_event(
        "dashboard.action_triggered",
        {"action": "run-tests", "args": "dashboard", "result": "accepted"},
        severity=Severity.INFO,
    )
    return JSONResponse(
        status_code=202,
        content={
            "action_id": action_id,
            "script": script_path,
            "command": command,
            "k8s_semantics": "kubectl create job test-dashboard-<HHMMSS> --from=cronjob/test-suite -n zivon",
            "status": "accepted",
        },
    )


class GenerateTopicActionRequest(BaseModel):
    chapter: str
    class_level: int | None = None
    fresh: bool = False


@router.post("/actions/generate-topic", status_code=202)
async def admin_trigger_generate_topic(
    request: Request,
    actor: str = Depends(require_admin_auth),
) -> JSONResponse:
    """API-A8: Wrap `scripts/trigger-factory-run.sh` (manual-only Job, never scheduled)."""
    try:
        raw_body = await request.json()
    except Exception as exc:
        raise APIError("E-VALIDATION", status_code=422) from exc
    if not isinstance(raw_body, dict):
        raise APIError("E-VALIDATION", status_code=422)

    chapter = str(raw_body.get("chapter") or "").strip()
    if not chapter or any(ch in chapter for ch in ("\n", "\r", ";", "`", "$")):
        raise APIError("E-VALIDATION", status_code=422)

    raw_cls = raw_body.get("class", raw_body.get("class_level"))
    cls_int: int | None = None
    if raw_cls is not None:
        try:
            cls_int = int(raw_cls)
        except (TypeError, ValueError) as exc:
            raise APIError("E-VALIDATION", status_code=422) from exc
        if cls_int < 6 or cls_int > 12:
            raise APIError("E-VALIDATION", status_code=422)

    fresh = bool(raw_body.get("fresh", False))
    script_path = "scripts/trigger-factory-run.sh"
    command: list[str] = [script_path, chapter]
    if cls_int is not None:
        command.append(str(cls_int))
    if fresh:
        command.append("--fresh")

    action_id = uuid7_str()
    db = request.app.state.db
    slug = "-".join(chapter.lower().split())
    run_id = f"{slug}-c{cls_int}" if cls_int is not None else slug
    db.execute(
        """
        INSERT INTO factory_run (run_id, topic, class_level, stage, verdict, stage_durations, ts)
        VALUES (?, ?, ?, '00-ingest', 'in_progress', '{}', ?)
        ON CONFLICT (run_id) DO UPDATE SET
            stage = '00-ingest',
            verdict = 'in_progress',
            ts = excluded.ts
        """,
        (run_id, chapter, cls_int, _utc_now_iso()),
    )
    db.record_audit(
        actor=actor,
        action="trigger.generate-topic",
        target=run_id,
        after_hash=action_id,
    )
    log_event(
        "dashboard.action_triggered",
        {
            "action": "generate-topic",
            "args": " ".join(command[1:]),
            "result": "accepted",
        },
        severity=Severity.INFO,
    )
    return JSONResponse(
        status_code=202,
        content={
            "action_id": action_id,
            "run_id": run_id,
            "script": script_path,
            "command": command,
            "manual_only": True,
            "status": "accepted",
        },
    )


@router.get("/actions/watch-run/{run_id}/logs")
def admin_watch_run_logs(
    run_id: str,
    request: Request,
    _actor: str = Depends(require_admin_auth),
) -> JSONResponse:
    """API-A9: Wrap `scripts/logs-factory-run.sh` semantics (label `task=factory-run`)."""
    cfg: BackendConfig = request.app.state.config
    run_dir = Path(cfg.runs_dir) / run_id
    lines: list[str] = []
    status_file = run_dir / "status.json"
    if status_file.is_file():
        lines.append(status_file.read_text(encoding="utf-8").strip())

    return JSONResponse(
        content={
            "run_id": run_id,
            "script": "scripts/logs-factory-run.sh",
            "label_selector": "task=factory-run",
            "command": ["scripts/logs-factory-run.sh", "--status"],
            "logs": lines,
        }
    )


@router.get("/audit")
def admin_list_audit(
    request: Request,
    from_ts: str | None = Query(default=None, alias="from"),
    _actor: str = Depends(require_admin_auth),
) -> JSONResponse:
    """API-A10: Audit log view (C13)."""
    db = request.app.state.db
    if from_ts:
        rows = db.fetchall(
            """
            SELECT audit_id, actor, action, target, before_hash, after_hash, at
            FROM audit_log
            WHERE at >= ?
            ORDER BY at DESC
            LIMIT 200
            """,
            (from_ts.strip(),),
        )
    else:
        rows = db.fetchall(
            """
            SELECT audit_id, actor, action, target, before_hash, after_hash, at
            FROM audit_log
            ORDER BY at DESC
            LIMIT 200
            """
        )
    return JSONResponse(content={"audit": rows})
