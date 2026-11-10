"""Student-facing REST endpoints API-001 through API-009 (backend-spec §6.1)."""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import re
import time
import uuid
from typing import Any, Final

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from db.uuid7 import uuid7_str

from ..config import (
    CONSENT_ACTIONS,
    REPORT_CATEGORIES,
    BackendConfig,
    normalize_locale,
)
from ..errors import APIError
from ..logging_shim import ErrorClass, Severity, log_event

router = APIRouter()

_UUID4_RE: Final[re.Pattern[str]] = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

VALID_EVT_IDS: Final[frozenset[str]] = frozenset(
    [f"EVT-{i:03d}" for i in range(1, 19)]
    + [f"EVT-F{i:02d}" for i in range(1, 13)]
    + [
        "frontend.page_view",
        "frontend.section_view",
        "frontend.sim_open",
        "frontend.sim_interact",
        "frontend.check_answered",
        "frontend.mic_press",
        "frontend.voice_turn_done",
        "frontend.error",
        "frontend.language_bar_use",
        "frontend.session_end",
        "frontend.publish_view",
        "frontend.heartbeat",
    ]
)

PRE_CONSENT_ALLOWED_EVTS: Final[frozenset[str]] = frozenset(
    {"EVT-001", "EVT-016", "EVT-017"}
    | {f"EVT-F{i:02d}" for i in range(1, 13)}
    | {
        "frontend.page_view",
        "frontend.section_view",
        "frontend.sim_open",
        "frontend.sim_interact",
        "frontend.check_answered",
        "frontend.mic_press",
        "frontend.voice_turn_done",
        "frontend.error",
        "frontend.language_bar_use",
        "frontend.session_end",
        "frontend.publish_view",
        "frontend.heartbeat",
    }
)

FORBIDDEN_FREE_TEXT_PROP_KEYS: Final[frozenset[str]] = frozenset(
    {
        "transcript",
        "student_transcript",
        "tutor_text",
        "text",
        "free_text",
        "message",
        "audio",
        "raw_audio",
        "pcm",
        "wav",
        "name",
        "email",
        "phone",
        "prompt",
        "utterance",
    }
)

FORBIDDEN_REPORT_PII_KEYS: Final[frozenset[str]] = frozenset(
    {
        "name",
        "student_name",
        "guardian_name",
        "email",
        "phone",
        "mobile",
        "contact",
        "address",
    }
)


def _utc_now_iso() -> str:
    now = datetime.datetime.now(datetime.UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _validate_device_id(device_pseudo_id: str) -> str:
    cleaned = (device_pseudo_id or "").strip().lower()
    if not _UUID4_RE.match(cleaned):
        raise APIError("E-VALIDATION", status_code=422)
    return cleaned


def _fallback_issue_session_token(
    cfg: BackendConfig, session_id: str, device_pseudo_id: str
) -> str:
    now = int(time.time())
    payload = {
        "session_id": session_id,
        "device_pseudo_id": device_pseudo_id,
        "iat": now,
        "exp": now + cfg.session_ttl_seconds,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    import base64

    b64 = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    sig = hmac.new(
        cfg.session_token_key.encode("utf-8"), b64.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return f"{b64}.{sig}"


def _fallback_verify_session_token(
    cfg: BackendConfig, token: str
) -> dict[str, Any] | None:
    if not token or "." not in token:
        return None
    b64, sig = token.rsplit(".", 1)
    expected = hmac.new(
        cfg.session_token_key.encode("utf-8"), b64.encode("ascii"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    import base64

    pad = "=" * ((4 - len(b64) % 4) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(b64 + pad).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if int(data.get("exp", 0)) < int(time.time()):
        return None
    return dict(data)


def _extract_session_token(
    request: Request,
    authorization: str | None,
    session_token_param: str | None = None,
) -> str:
    if session_token_param:
        return session_token_param.strip()
    auth = (authorization or request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("zivonsession "):
        return auth.split(" ", 1)[1].strip()
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    alt = request.headers.get("X-Session-Token", "").strip()
    return alt


def _verify_token(request: Request, token: str) -> dict[str, Any]:
    identity = getattr(request.app.state, "identity", None)
    if identity is not None:
        claims = identity.verify_session_token(token)
    else:
        cfg: BackendConfig = request.app.state.config
        claims = _fallback_verify_session_token(cfg, token)
    if claims is None:
        raise APIError("E-SESSION-EXPIRED", status_code=401, retryable=False)
    return dict(claims)


def _evaluate_consent_and_guard(
    request: Request, device_pseudo_id: str
) -> tuple[bool, str | None, str, str, dict[str, bool]]:
    """Compute (consent_required, consent_id, guard_state, flags_str, flags_obj)."""
    cfg: BackendConfig = request.app.state.config
    db = request.app.state.db
    consent_row = db.get_latest_consent(device_pseudo_id) if db is not None else None
    has_valid_consent = bool(
        consent_row
        and consent_row.get("action") == "granted"
        and consent_row.get("notice_version") == cfg.current_notice_version
    )
    consent_id = str(consent_row["consent_id"]) if consent_row else None
    consent_required = not has_valid_consent

    guard = getattr(request.app.state, "guard", None)
    if guard is not None:
        guard_status = guard.get_status(device_pseudo_id=device_pseudo_id)
        guard_state = guard_status.effective_state
    else:
        guard_state = "ok"

    if consent_required:
        flags_str = "voice_off"
        flags_obj = {"voice_enabled": False, "typed_only": False, "voice_off": True}
    elif guard_state == "exhausted":
        flags_str = "typed_only"
        flags_obj = {"voice_enabled": False, "typed_only": True, "voice_off": False}
    else:
        flags_str = "voice_enabled"
        flags_obj = {"voice_enabled": True, "typed_only": False, "voice_off": False}

    return consent_required, consent_id, guard_state, flags_str, flags_obj


class SessionBootstrapRequest(BaseModel):
    device_pseudo_id: str
    lang: str = "en-IN"
    consent_state: str | bool | None = None
    page: dict[str, Any] | None = None
    mode: str = "guide"


@router.post("/v1/session")
def bootstrap_session(body: SessionBootstrapRequest, request: Request) -> JSONResponse:
    """API-001: Bootstrap a pseudonymous lesson-page session and compute flags."""
    cfg: BackendConfig = request.app.state.config
    db = request.app.state.db
    device_id = _validate_device_id(body.device_pseudo_id)
    try:
        lang = normalize_locale(body.lang)
    except ValueError as exc:
        raise APIError("E-VALIDATION", status_code=422) from exc

    mode = body.mode if body.mode in ("guide", "tell") else "guide"
    course_id: str | None = None
    class_level: int | None = None
    if isinstance(body.page, dict):
        if body.page.get("course_id") is not None:
            course_id = str(body.page["course_id"])
        raw_cls = body.page.get("class", body.page.get("class_level"))
        if raw_cls is not None:
            try:
                class_level = int(raw_cls)
            except (TypeError, ValueError) as exc:
                raise APIError("E-VALIDATION", status_code=422) from exc
            if class_level < 6 or class_level > 12:
                raise APIError("E-VALIDATION", status_code=422)

    db.upsert_device(device_id, locale=lang)
    consent_required, consent_id, guard_state, flags_str, flags_obj = (
        _evaluate_consent_and_guard(request, device_id)
    )

    session_id = str(uuid.uuid4())
    now = _utc_now_iso()
    db.execute(
        """
        INSERT INTO session (
            session_id, device_pseudo_id, course_id, class_level,
            lang, mode, consent_ref, guardian_ref, flags,
            coverage, coverage_rev, started_at, turn_count, coverage_synced
        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, '[]', 0, ?, 0, 0)
        """,
        (
            session_id,
            device_id,
            course_id,
            class_level,
            lang,
            mode,
            consent_id if not consent_required else None,
            json.dumps(flags_obj),
            now,
        ),
    )

    identity = getattr(request.app.state, "identity", None)
    if identity is not None:
        session_token = identity.issue_session_token(session_id, device_id)
    else:
        session_token = _fallback_issue_session_token(cfg, session_id, device_id)

    log_event(
        "voice.session.started",
        {"topic": course_id or "unknown", "class_level": class_level or 9},
        severity=Severity.INFO,
        session_id=session_id,
    )

    return JSONResponse(
        content={
            "session_id": session_id,
            "session_token": session_token,
            "flags": flags_str,
            "flags_detail": flags_obj,
            "consent_required": consent_required,
            "guard_state": guard_state,
        }
    )


class CoverageUpdateRequest(BaseModel):
    covered: list[dict[str, Any]]
    rev: int | None = None


@router.put("/v1/session/{session_id}/coverage")
def update_session_coverage(
    session_id: str,
    body: CoverageUpdateRequest,
    request: Request,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """API-003: Persist covered items at turn boundaries (consent-gated)."""
    cfg: BackendConfig = request.app.state.config
    db = request.app.state.db
    token = _extract_session_token(request, authorization)
    claims = _verify_token(request, token)
    if claims.get("session_id") != session_id:
        raise APIError("E-SESSION-EXPIRED", status_code=401)

    if len(body.covered) > 32:
        raise APIError("E-VALIDATION", status_code=422)
    for item in body.covered:
        if not isinstance(item, dict) or not item.get("block_id"):
            raise APIError("E-VALIDATION", status_code=422)

    session_row = db.fetchone(
        "SELECT session_id, device_pseudo_id, coverage_rev FROM session WHERE session_id = ?",
        (session_id,),
    )
    if session_row is None:
        raise APIError("E-SESSION-EXPIRED", status_code=401)

    device_id = str(session_row["device_pseudo_id"])
    consent_row = db.get_latest_consent(device_id)
    if consent_row is None or consent_row.get("action") != "granted":
        raise APIError("E-CONSENT-REQUIRED", status_code=403)
    if consent_row.get("notice_version") != cfg.current_notice_version:
        raise APIError("E-CONSENT-STALE", status_code=403)

    current_rev = int(session_row.get("coverage_rev") or 0)
    if body.rev is not None and body.rev < current_rev:
        return JSONResponse(
            content={"ok": True, "coverage_synced": True, "rev": current_rev}
        )

    new_rev = (body.rev if body.rev is not None else current_rev) + 1
    now = _utc_now_iso()
    db.execute(
        """
        UPDATE session
        SET coverage = ?, coverage_rev = ?, coverage_updated_at = ?, coverage_synced = 1
        WHERE session_id = ?
        """,
        (json.dumps(body.covered), new_rev, now, session_id),
    )
    return JSONResponse(content={"ok": True, "coverage_synced": True, "rev": new_rev})


class ConsentUpdateRequest(BaseModel):
    device_pseudo_id: str
    consent_version: str
    notice_version: str | None = None
    guardian_flag: bool
    action: str = "granted"
    source: str = "overlay"
    ts: str | None = None


@router.put("/v1/consent")
def put_consent(body: ConsentUpdateRequest, request: Request) -> JSONResponse:
    """API-004: Append consent event (granted/declined/withdrawn) to ledger."""
    cfg: BackendConfig = request.app.state.config
    db = request.app.state.db
    device_id = _validate_device_id(body.device_pseudo_id)
    if body.action not in CONSENT_ACTIONS:
        raise APIError("E-VALIDATION", status_code=422)
    if body.source not in ("overlay", "imported"):
        raise APIError("E-VALIDATION", status_code=422)
    if not body.consent_version.strip():
        raise APIError("E-VALIDATION", status_code=422)

    notice_ver = (body.notice_version or cfg.current_notice_version).strip()
    consent_id = db.append_consent(
        device_pseudo_id=device_id,
        consent_version=body.consent_version.strip(),
        notice_version=notice_ver,
        guardian_flag=body.guardian_flag,
        action=body.action,
        source=body.source,
        recorded_at=body.ts,
    )
    return JSONResponse(content={"ok": True, "consent_id": consent_id})


def _ingest_events_impl(
    raw_body: dict[str, Any], request: Request, *, max_batch: int
) -> JSONResponse:
    cfg: BackendConfig = request.app.state.config
    db = request.app.state.db
    events = raw_body.get("events")
    if not isinstance(events, list) or len(events) > max_batch:
        raise APIError("E-VALIDATION", status_code=422)

    accepted = 0
    rejected: list[dict[str, Any]] = []
    now = _utc_now_iso()

    for idx, ev in enumerate(events):
        if not isinstance(ev, dict):
            rejected.append({"i": idx, "code": "E-EVT-SCHEMA"})
            continue

        evt_id = str(ev.get("evt_id") or ev.get("event") or "").strip()
        if evt_id not in VALID_EVT_IDS:
            rejected.append({"i": idx, "code": "E-EVT-SCHEMA"})
            continue

        props = ev.get("props")
        if props is None:
            props = ev.get("fields", {})
        if not isinstance(props, dict):
            rejected.append({"i": idx, "code": "E-EVT-SCHEMA"})
            continue

        # Reject any free-text or PII key in props (backend-spec §6.1 API-005)
        bad_key = False
        for k, v in props.items():
            if k.lower() in FORBIDDEN_FREE_TEXT_PROP_KEYS:
                bad_key = True
                break
            if isinstance(v, str) and len(v) > 256:
                bad_key = True
                break
        if bad_key:
            rejected.append({"i": idx, "code": "E-EVT-SCHEMA"})
            continue

        session_id = ev.get("session_id")
        device_id = ev.get("device_pseudo_id") or ev.get("client_session_id")
        if session_id and not device_id:
            s_row = db.fetchone(
                "SELECT device_pseudo_id FROM session WHERE session_id = ?",
                (str(session_id),),
            )
            if s_row:
                device_id = str(s_row["device_pseudo_id"])

        if not device_id:
            # Synthesize deterministic pseudonymous anchor when Core-safe beacon omits it
            if evt_id in PRE_CONSENT_ALLOWED_EVTS:
                device_id = "00000000-0000-4000-8000-000000000000"
            else:
                rejected.append({"i": idx, "code": "E-CONSENT-REQUIRED"})
                continue

        device_id = str(device_id).strip().lower()
        if not _UUID4_RE.match(device_id):
            rejected.append({"i": idx, "code": "E-EVT-SCHEMA"})
            continue

        # Consent gate: pre-consent only EVT-001/016/017 (+ EVT-Fxx beacons) allowed
        if evt_id not in PRE_CONSENT_ALLOWED_EVTS:
            consent_row = db.get_latest_consent(device_id)
            if (
                consent_row is None
                or consent_row.get("action") != "granted"
                or consent_row.get("notice_version") != cfg.current_notice_version
            ):
                rejected.append({"i": idx, "code": "E-CONSENT-REQUIRED"})
                continue

        event_uuid = ev.get("event_uuid") or ev.get("id")
        if event_uuid:
            dup = db.fetchone(
                "SELECT event_id FROM telemetry_event WHERE event_uuid = ?",
                (str(event_uuid),),
            )
            if dup is not None:
                accepted += 1
                continue

        db.upsert_device(device_id)
        course_id = ev.get("course_id") or ev.get("page_id") or props.get("topic")
        block_id = ev.get("block_id") or props.get("block_id")
        client_ts = ev.get("client_ts") or ev.get("ts")

        valid_session_id: str | None = None
        if session_id:
            s_exists = db.fetchone(
                "SELECT session_id FROM session WHERE session_id = ?",
                (str(session_id),),
            )
            if s_exists:
                valid_session_id = str(session_id)

        db.execute(
            """
            INSERT INTO telemetry_event (
                event_id, event_uuid, evt_id, session_id, device_pseudo_id,
                course_id, block_id, props, ts, client_ts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid7_str(),
                str(event_uuid) if event_uuid else None,
                evt_id,
                valid_session_id,
                device_id,
                str(course_id) if course_id else None,
                str(block_id) if block_id else None,
                json.dumps(props),
                now,
                str(client_ts) if client_ts else None,
            ),
        )
        accepted += 1

    if rejected:
        log_event(
            "voice.events.ingest_rejected",
            {"reasons_count": len(rejected)},
            severity=Severity.WARNING,
            error_class=ErrorClass.CLIENT_ERROR,
        )

    return JSONResponse(content={"accepted": accepted, "rejected": rejected})


@router.post("/v1/events")
async def ingest_events_v1(request: Request) -> JSONResponse:
    """API-005: Batched schema-validated telemetry ingestion (<= 20 events)."""
    try:
        raw_body = await request.json()
    except Exception as exc:
        raise APIError("E-VALIDATION", status_code=422) from exc
    if not isinstance(raw_body, dict):
        raise APIError("E-VALIDATION", status_code=422)
    return _ingest_events_impl(raw_body, request, max_batch=20)


@router.post("/api/v1/events")
async def ingest_events_sp3(request: Request) -> JSONResponse:
    """SP3 logging-api §10 event ingest endpoint alias (<= 32 events)."""
    try:
        raw_body = await request.json()
    except Exception as exc:
        raise APIError("E-VALIDATION", status_code=422) from exc
    if not isinstance(raw_body, dict):
        raise APIError("E-VALIDATION", status_code=422)
    return _ingest_events_impl(raw_body, request, max_batch=32)


@router.post("/v1/reports")
async def submit_problem_report(request: Request) -> JSONResponse:
    """API-006: Problem-report intake (strictly rejects PII fields)."""
    try:
        raw_body = await request.json()
    except Exception as exc:
        raise APIError("E-VALIDATION", status_code=422) from exc
    if not isinstance(raw_body, dict):
        raise APIError("E-VALIDATION", status_code=422)

    for key in raw_body:
        if key.lower() in FORBIDDEN_REPORT_PII_KEYS:
            raise APIError("E-VALIDATION", status_code=422)

    course_id = str(raw_body.get("course_id") or raw_body.get("page_id") or "").strip()
    if not course_id:
        raise APIError("E-VALIDATION", status_code=422)

    category = str(raw_body.get("category") or "").strip()
    if category not in REPORT_CATEGORIES:
        raise APIError("E-VALIDATION", status_code=422)

    class_level: int | None = None
    raw_cls = raw_body.get("class", raw_body.get("class_level"))
    if raw_cls is not None:
        try:
            class_level = int(raw_cls)
        except (TypeError, ValueError) as exc:
            raise APIError("E-VALIDATION", status_code=422) from exc
        if class_level < 6 or class_level > 12:
            raise APIError("E-VALIDATION", status_code=422)

    text_val = raw_body.get("text")
    if text_val is not None and (not isinstance(text_val, str) or len(text_val) > 500):
        raise APIError("E-VALIDATION", status_code=422)

    device_id: str | None = None
    if raw_body.get("device_pseudo_id"):
        device_id = _validate_device_id(str(raw_body["device_pseudo_id"]))

    db = request.app.state.db
    report_nonce = raw_body.get("report_nonce")
    if report_nonce:
        existing = db.fetchone(
            "SELECT report_id FROM problem_report WHERE report_nonce = ?",
            (str(report_nonce),),
        )
        if existing is not None:
            return JSONResponse(content={"report_id": str(existing["report_id"])})

    report_id = uuid7_str()
    db.execute(
        """
        INSERT INTO problem_report (
            report_id, report_nonce, device_pseudo_id, course_id,
            class_level, block_id, category, text, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
        """,
        (
            report_id,
            str(report_nonce) if report_nonce else None,
            device_id,
            course_id,
            class_level,
            str(raw_body["block_id"]) if raw_body.get("block_id") else None,
            category,
            text_val,
            _utc_now_iso(),
        ),
    )
    return JSONResponse(content={"report_id": report_id})


@router.get("/v1/data/challenge")
def get_deletion_challenge(
    request: Request,
    device_pseudo_id: str = Query(...),
) -> JSONResponse:
    """Issue a server confirm_token challenge for API-007 (backend-spec §6.1)."""
    device_id = _validate_device_id(device_pseudo_id)
    identity = getattr(request.app.state, "identity", None)
    if identity is not None:
        token = identity.issue_confirm_token(device_id)
    else:
        cfg: BackendConfig = request.app.state.config
        token = hmac.new(
            cfg.session_token_key.encode("utf-8"),
            f"confirm:{device_id}".encode(),
            hashlib.sha256,
        ).hexdigest()
    return JSONResponse(content={"device_pseudo_id": device_id, "confirm_token": token})


class DeleteDataRequest(BaseModel):
    device_pseudo_id: str
    confirm_token: str
    scope: str = "device"


@router.delete("/v1/data")
async def delete_device_data(request: Request) -> JSONResponse:
    """API-007: Right-to-erasure device-scoped wipe (NEED-013)."""
    try:
        raw_body = await request.json()
    except Exception as exc:
        raise APIError("E-CONFIRM-REQUIRED", status_code=400) from exc
    if not isinstance(raw_body, dict):
        raise APIError("E-CONFIRM-REQUIRED", status_code=400)

    device_id = _validate_device_id(str(raw_body.get("device_pseudo_id") or ""))
    confirm_token = str(raw_body.get("confirm_token") or "").strip()
    scope = str(raw_body.get("scope") or "device").strip()
    if scope != "device" or not confirm_token:
        raise APIError("E-CONFIRM-REQUIRED", status_code=400)

    identity = getattr(request.app.state, "identity", None)
    if identity is not None:
        valid = identity.verify_confirm_token(device_id, confirm_token)
    else:
        cfg: BackendConfig = request.app.state.config
        expected = hmac.new(
            cfg.session_token_key.encode("utf-8"),
            f"confirm:{device_id}".encode(),
            hashlib.sha256,
        ).hexdigest()
        valid = hmac.compare_digest(confirm_token, expected)

    if not valid:
        raise APIError("E-CONFIRM-REQUIRED", status_code=400)

    privacy_pipeline = getattr(request.app.state, "privacy", None)
    if privacy_pipeline is not None:
        result = privacy_pipeline.wipe_device(device_id)
        return JSONResponse(content=result)

    # Inline fallback wipe before backend/privacy.py is wired
    db = request.app.state.db
    with db.transaction() as tx:
        turns = tx.fetchone(
            """
            SELECT COUNT(*) AS cnt FROM voice_turn
            WHERE session_id IN (SELECT session_id FROM session WHERE device_pseudo_id = ?)
            """,
            (device_id,),
        )
        sessions = tx.fetchone(
            "SELECT COUNT(*) AS cnt FROM session WHERE device_pseudo_id = ?",
            (device_id,),
        )
        consents = tx.fetchone(
            "SELECT COUNT(*) AS cnt FROM consent_record WHERE device_pseudo_id = ?",
            (device_id,),
        )
        events = tx.fetchone(
            "SELECT COUNT(*) AS cnt FROM telemetry_event WHERE device_pseudo_id = ?",
            (device_id,),
        )
        reports = tx.fetchone(
            "SELECT COUNT(*) AS cnt FROM problem_report WHERE device_pseudo_id = ?",
            (device_id,),
        )
        counts = {
            "sessions": int(sessions["cnt"]) if sessions else 0,
            "consents": int(consents["cnt"]) if consents else 0,
            "events": int(events["cnt"]) if events else 0,
            "turns": int(turns["cnt"]) if turns else 0,
            "reports": int(reports["cnt"]) if reports else 0,
        }
        req_id = uuid7_str()
        now = _utc_now_iso()
        tx.execute(
            """
            INSERT INTO deletion_request (
                request_id, device_pseudo_id, scope, status, counts, requested_at, completed_at
            ) VALUES (?, ?, 'device', 'completed', ?, ?, ?)
            """,
            (req_id, device_id, json.dumps(counts), now, now),
        )
        tx.execute(
            "DELETE FROM problem_report WHERE device_pseudo_id = ?",
            (device_id,),
        )
        tx.execute("DELETE FROM device WHERE device_pseudo_id = ?", (device_id,))
    return JSONResponse(content={"deleted": counts, "tombstone_id": req_id})


@router.get("/v1/health")
def get_v1_health(request: Request) -> JSONResponse:
    """API-008: Liveness/readiness probe with schema_version, release, and guard mode."""
    cfg: BackendConfig = request.app.state.config
    db = request.app.state.db
    if db is None or not db.ping():
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "db": "error",
                "schema_version": "0000",
                "release": cfg.release_tag,
                "guard_profile_mode": "normal",
            },
        )
    profile_row = db.fetchone("SELECT mode FROM guard_profile WHERE id = 1")
    mode = str(profile_row["mode"]) if profile_row else "normal"
    return JSONResponse(
        content={
            "status": "ok",
            "db": "ok",
            "schema_version": db.schema_version(),
            "release": cfg.release_tag,
            "guard_profile_mode": mode,
        }
    )


@router.get("/v1/session/{session_id}")
def get_session_resume(
    session_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
    session_token: str | None = Query(default=None),
) -> JSONResponse:
    """API-009: Revalidate session_token and return flags + coverage after reconnect."""
    db = request.app.state.db
    token = _extract_session_token(request, authorization, session_token)
    claims = _verify_token(request, token)
    if claims.get("session_id") != session_id:
        raise APIError("E-SESSION-EXPIRED", status_code=401)

    row = db.fetchone(
        """
        SELECT session_id, device_pseudo_id, coverage, coverage_rev, coverage_synced
        FROM session WHERE session_id = ?
        """,
        (session_id,),
    )
    if row is None:
        raise APIError("E-SESSION-EXPIRED", status_code=401)

    device_id = str(row["device_pseudo_id"])
    consent_required, _, guard_state, flags_str, flags_obj = (
        _evaluate_consent_and_guard(request, device_id)
    )
    raw_cov = row.get("coverage")
    if isinstance(raw_cov, str):
        try:
            coverage = json.loads(raw_cov)
        except Exception:  # noqa: BLE001
            coverage = []
    elif isinstance(raw_cov, list):
        coverage = raw_cov
    else:
        coverage = []

    return JSONResponse(
        content={
            "session_id": session_id,
            "flags": flags_str,
            "flags_detail": flags_obj,
            "consent_required": consent_required,
            "guard_state": guard_state,
            "coverage": coverage,
            "rev": int(row.get("coverage_rev") or 0),
            "coverage_synced": bool(row.get("coverage_synced")),
        }
    )
