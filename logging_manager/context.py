"""Correlation-ID context: contextvars helpers plus the cross-process headers.

Within a process the four IDs (run_id / session_id / turn_id / request_id,
spec.md §3) live here so component code never threads them through function
arguments. `contextvars.ContextVar` is the mechanism because it is correct
for BOTH concurrency shapes this repo runs: asyncio voice handlers and the
factory's threaded stages — a child task inherits, a new edge binds fresh.

Edge discipline (logging-api.md §3): exactly one `bind_context` per edge —
`run_pipeline()` (run_id), voice session start (session_id), the turn
handler (turn_id), every HTTP/WS request entry (request_id). Components
never pass IDs through function arguments unless crossing a process
boundary; across a boundary the IDs ride the §7 headers, and the receiving
service validates + rebinds via `bind_from_headers`.

`client_session_id` (frontend-only, logging-api.md §4) rides the same
context so the event-ingest re-emission path can set it without widening
the frozen `log_event` signature.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

# default=None (a mutable dict default is unsafe — B039): every read goes
# through _current(), every write .set()s a NEW dict, so nothing mutates a
# shared default.
_CONTEXT: ContextVar[dict[str, str] | None] = ContextVar(
    "zivon_log_context", default=None
)


def _current() -> dict[str, str]:
    value = _CONTEXT.get()
    return value if value is not None else {}


CONTEXT_KEYS = frozenset(
    {"run_id", "session_id", "turn_id", "request_id", "client_session_id"}
)

# A UUID4 (request/session/turn ids) and a factory run id (a slug) have
# different shapes; both are validated before an inbound header is trusted
# (logging-api.md §7: accept inbound ids only when they look sane).
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")

_HEADER_MAP = {
    "request_id": "X-Request-Id",
    "run_id": "X-Zivon-Run-Id",
    "session_id": "X-Zivon-Session-Id",
}


def bind_context(**ids: str) -> None:
    """Set correlation IDs at an edge; merges over what is already bound.

    Raises on an unknown key (a typo at an edge is a programmer error, and
    silently dropping an ID would break the join this whole module exists
    for). Values are coerced to str; empty strings are dropped.
    """
    unknown = set(ids) - CONTEXT_KEYS
    if unknown:
        raise ValueError(
            f"unknown correlation key(s) {sorted(unknown)}; valid: {sorted(CONTEXT_KEYS)}"
        )
    clean = {key: str(value) for key, value in ids.items() if str(value)}
    if not clean:
        return
    merged = {**_current(), **clean}
    _CONTEXT.set(merged)


@contextmanager
def context_scope(**ids: str) -> Iterator[None]:
    """Scoped override: inside the block the given IDs apply, after it the
    previous binding is restored exactly (async-safe, task-local)."""
    outer = _current()
    unknown = set(ids) - CONTEXT_KEYS
    if unknown:
        raise ValueError(
            f"unknown correlation key(s) {sorted(unknown)}; valid: {sorted(CONTEXT_KEYS)}"
        )
    _CONTEXT.set(
        {**outer, **{key: str(value) for key, value in ids.items() if str(value)}}
    )
    try:
        yield
    finally:
        _CONTEXT.set(outer)


def current_context() -> dict[str, str]:
    """A read-only snapshot of the current correlation IDs (tests, debugging)."""
    return dict(_current())


def get_id(key: str) -> str | None:
    """One correlation ID from the context, or None when unset."""
    return _current().get(key) or None


def correlation_headers() -> dict[str, str]:
    """The §7 headers for an outbound call to the llm-manager node (or any
    same-cluster consumer edge), built from the current context. Headers for
    IDs that are not bound are omitted — absence is honest."""
    ctx = _current()
    return {header: ctx[key] for key, header in _HEADER_MAP.items() if ctx.get(key)}


def bind_from_headers(headers: Mapping[str, str]) -> str:
    """Receive an inbound request at an HTTP/WS edge.

    An inbound `X-Request-Id` (and `X-Zivon-*` ids) is accepted only from a
    well-formed value (logging-api.md §7: validate UUID shape; run ids are
    slug-shaped); absent or malformed ids are regenerated, never trusted.
    Returns the request_id this exchange will carry.
    """
    request_id: str | None = None
    raw = headers.get("X-Request-Id")
    if raw and _UUID_RE.fullmatch(raw.strip()):
        request_id = raw.strip().lower()
    run_id: str | None = None
    raw = headers.get("X-Zivon-Run-Id")
    if raw and _SLUG_RE.fullmatch(raw.strip()):
        run_id = raw.strip()
    session_id: str | None = None
    raw = headers.get("X-Zivon-Session-Id")
    if raw and _UUID_RE.fullmatch(raw.strip()):
        session_id = raw.strip().lower()
    if request_id is None:
        request_id = str(uuid.uuid4())
    bound: dict[str, str] = {"request_id": request_id}
    if run_id:
        bound["run_id"] = run_id
    if session_id:
        bound["session_id"] = session_id
    bind_context(**bound)
    return request_id


def new_request_id() -> str:
    """A fresh request edge id (the caller binds it itself when it needs to
    keep it around, e.g. the factory's per-call leg)."""
    return str(uuid.uuid4())


def snapshot_for(event_ids: dict[str, Any]) -> dict[str, str]:
    """Merge the context under explicit per-event IDs: an argument beats the
    context (logging-api.md §2: 'omitted -> taken from context vars')."""
    ctx = _current()
    merged = {key: value for key, value in ctx.items() if value}
    for key in CONTEXT_KEYS:
        value = event_ids.get(key)
        if value:
            merged[key] = str(value)
    return merged
