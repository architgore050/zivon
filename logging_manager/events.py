"""Event identity: schema version, closed vocabularies, the instrumentation map.

`LOG_SCHEMA_VERSION = 1` (logging-api.md §9). `Severity` and `ErrorClass` are
the closed vocabularies of logging-api.md §8 — additions are spec changes,
never call-site strings.

The instrumentation map (`docs/specs/observability/instrumentation-map.csv`)
is the per-event source of truth: severity is declared ONCE per event there
and `log_event` derives it; an emitted event with no row is flagged
(`log.event_unknown`) and CI map-lint makes that red. Loading degrades
honestly: when the CSV is not on disk (e.g. a slim image that ships only this
package), validation is disabled and every event is delivered — the module
never blocks a caller because it cannot find a doc file.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

LOG_SCHEMA_VERSION = 1

# ZIVON_LOG_LEVEL=DEBUG is the dev-mode switch (logging-api.md §2): it is the
# ONLY mode in which log_event raises on programmer errors. Never set it in
# cluster manifests (logging-api.md §5).
DEBUG_MODE_ENV = "ZIVON_LOG_LEVEL"
DEBUG_MODE_VALUE = "DEBUG"

_MAP_ENV = "ZIVON_INSTRUMENTATION_MAP"


class Severity(str, Enum):
    """stdlib logging names (logging-api.md §4 field table)."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ErrorClass(str, Enum):
    """The closed failure taxonomy (spec.md §7)."""

    TRANSPORT_ERROR = "transport_error"
    VALIDATION_ERROR = "validation_error"
    GATE_FAIL = "gate_fail"
    REPAIR_EXHAUSTED = "repair_exhausted"
    INFRA_ERROR = "infra_error"
    QUOTA_ERROR = "quota_error"
    AUTH_ERROR = "auth_error"
    CLIENT_ERROR = "client_error"
    PRIVACY_VIOLATION = "privacy_violation"
    STORE_ERROR = "store_error"


# The closed component enum (logging-api.md §8). The map may declare a row for
# a name outside this set (found live: `privacy.subject_deleted` is mapped
# with component `privacy`); per-event the MAP wins — the set below is the
# vocabulary for events WITHOUT a row.
COMPONENTS: frozenset[str] = frozenset(
    {
        "factory",
        "llm",
        "llm_node",
        "voice",
        "translator",
        "frontend",
        "dashboard",
        "credit",
        "log",
    }
)

DEFAULT_COMPONENT = "log"


@dataclass(frozen=True)
class MapRow:
    """One row of instrumentation-map.csv (a declared event)."""

    component: str
    event: str
    severity: str
    correlation_ids: str
    required_fields: str
    latency_ms: bool
    error_class: str
    privacy_class: str
    emitter: str
    notes: str


def default_map_path() -> Path:
    """The map ships in the repo's docs tree, next to this package's parent."""
    override = os.environ.get(_MAP_ENV, "").strip()
    if override:
        return Path(override)
    return (
        Path(__file__).resolve().parent.parent
        / "docs"
        / "specs"
        / "observability"
        / "instrumentation-map.csv"
    )


def load_map(path: Path | None = None) -> dict[str, MapRow]:
    """Parse the instrumentation map into {event_name: MapRow}.

    RFC-4180 via the stdlib csv module. A missing file, a ragged row or an
    unreadable cell degrades to "no map" for that row — telemetry must never
    depend on a doc parsing.
    """
    csv_path = default_map_path() if path is None else path
    rows: dict[str, MapRow] = {}
    try:
        text = csv_path.read_text(encoding="utf-8")
    except OSError:
        return rows
    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None:
        return rows
    for raw in reader:
        event = (raw.get("event") or "").strip()
        if not event:
            continue
        rows[event] = MapRow(
            component=(raw.get("component") or "").strip(),
            event=event,
            severity=(raw.get("severity") or "").strip(),
            correlation_ids=(raw.get("correlation_ids") or "").strip(),
            required_fields=(raw.get("required_fields") or "").strip(),
            latency_ms=(raw.get("latency_ms") or "").strip().lower() == "yes",
            error_class=(raw.get("error_class") or "").strip(),
            privacy_class=(raw.get("privacy_class") or "").strip(),
            emitter=(raw.get("emitter") or "").strip(),
            notes=(raw.get("notes") or "").strip(),
        )
    return rows


_MAP_CACHE: dict[str, MapRow] | None = None
_MAP_CACHE_PATH: str | None = None


def _map() -> dict[str, MapRow]:
    global _MAP_CACHE, _MAP_CACHE_PATH
    path = str(default_map_path())
    if _MAP_CACHE is None or _MAP_CACHE_PATH != path:
        _MAP_CACHE = load_map()
        _MAP_CACHE_PATH = path
    return _MAP_CACHE


def reset_map_cache() -> None:
    """Drop the cached map (tests that swap the CSV via env use this)."""
    global _MAP_CACHE, _MAP_CACHE_PATH
    _MAP_CACHE = None
    _MAP_CACHE_PATH = None


def known_event(event: str) -> MapRow | None:
    """The map row for an event name, or None when the name is undeclared."""
    return _map().get(event)


def severity_for(event: str) -> Severity:
    """The map-declared severity; INFO when the name has no row (undeclared
    events are delivered, flagged, and get the neutral default)."""
    row = known_event(event)
    if row is not None:
        try:
            return Severity(row.severity)
        except ValueError:
            return Severity.INFO
    return Severity.INFO


def component_for(event: str, emitter_module: str | None = None) -> str:
    """The event's component: the map row's declaration first (per-event the
    map is the contract), else inferred from the emitting module, else the
    module's own component. Unknown packages get `log` — honest, and CI
    map-lint flags the undeclared name anyway."""
    row = known_event(event)
    if row is not None and row.component:
        return row.component
    inferred = _infer_component(emitter_module)
    if inferred is not None:
        return inferred
    return DEFAULT_COMPONENT


def _infer_component(emitter_module: str | None) -> str | None:
    """Dotted module -> component. `llm_manager` splits: its client side
    (model-call events inside any consumer) is `llm`, its service node is
    `llm_node` (logging-api.md §8)."""
    if not emitter_module:
        return None
    if emitter_module == "llm_manager" or emitter_module.startswith("llm_manager."):
        node = emitter_module.startswith("llm_manager.service")
        return "llm_node" if node else "llm"
    top_level = emitter_module.split(".", 1)[0]
    if top_level in COMPONENTS:
        return top_level
    return None


def dev_mode(env: dict[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    return source.get(DEBUG_MODE_ENV, "").strip().upper() == DEBUG_MODE_VALUE


def env_name(env: dict[str, str] | None = None) -> str:
    """ZIVON_ENV (dev|cluster|prod), default dev. Unknown values fall back to
    dev — the enum is closed (logging-api.md §4) and a typo must not widen it."""
    source = os.environ if env is None else env
    value = source.get("ZIVON_ENV", "").strip().lower()
    return value if value in ("dev", "cluster", "prod") else "dev"


def validate_error_class(error_class: Any) -> ErrorClass | None:
    """Coerce an error_class argument into the closed enum. `None` passes
    through (absence is honest). Anything outside the enum returns None for
    delivery decisions — log_event decides between raising (dev) and
    delivering as-is (never breaks the caller's path)."""
    if error_class is None:
        return None
    if isinstance(error_class, ErrorClass):
        return error_class
    if isinstance(error_class, str) and error_class in ErrorClass.__members__:
        return ErrorClass(error_class)
    return None
