"""Exam/series configuration and the compliance mode gate.

Two layers, same split as the rest of the factory:

- `config.json`'s `exam` section carries BEHAVIOUR: where the paper metadata
  fixtures, syllabus and item pools live, the blueprint policy, the series
  gate knobs, the similarity threshold and the *default* content mode.
  Committed and reviewable.
- Environment variables carry the compliance state
  (`EXAM_CONTENT_MODE`, `EXAM_VERBATIM_CLEARANCE_ID`,
  `SERIES_EXACT_PYQ_ENABLED`) and the runtime contact mailbox
  (`ZIVON_COMPLIANCE_EMAIL`). A deployment can therefore pin the mode without
  editing a committed file, and a CI run can prove the dark path without a
  secret.

`docs/compliance/cbse-exam-content.md` §7.1: the build fails closed. An unknown
mode, `attributed_verbatim` without a clearance row, or the exact-PYQ flag
turned on while verbatim is not cleared is a startup error - never a silent
fallback to the previous mode.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from . import CONTENT_MODES
from .clearance import (
    ClearanceRow,
    find_clearance,
    load_clearance_register,
)
from .errors import ExamConfigError

DEFAULT_EXAM_SECTION: dict[str, Any] = {
    "papers_dir": "sources/exam/papers",
    "syllabus_path": "sources/syllabus/syllabus.json",
    "chapters_dir": "sources/syllabus/chapters",
    "decision_log_path": "docs/compliance/decision-log.md",
    "export_dir": "",
    "content_mode": "blueprint_only",
    "verbatim_clearance_id": "",
    "exact_pyq_enabled": False,
    "blueprint_years": 5,
    "recency_decay": 0.8,
    "include_paper_types": ["main", "sample"],
    "chapter_question_floor": 10,
    "chapter_test_size": 10,
    "mixed_test_size": 20,
    "unit_test_size": 10,
    "set_size": 10,
    "similarity_ngram": 8,
    "similarity_max_overlap": 0.2,
}

_ENV_MODE = "EXAM_CONTENT_MODE"
_ENV_CLEARANCE = "EXAM_VERBATIM_CLEARANCE_ID"
_ENV_EXACT = "SERIES_EXACT_PYQ_ENABLED"
_ENV_CONTACT = "ZIVON_COMPLIANCE_EMAIL"


@dataclass(frozen=True)
class BlueprintPolicy:
    years_window: int = 5
    recency_decay: float = 0.8
    include_paper_types: tuple[str, ...] = ("main", "sample")

    def __post_init__(self) -> None:
        if self.years_window < 1 or self.years_window > 20:
            raise ExamConfigError("blueprint_years must be 1..20")
        if not 0.0 < self.recency_decay <= 1.0:
            raise ExamConfigError("recency_decay must be in (0, 1]")
        if not self.include_paper_types:
            raise ExamConfigError("include_paper_types must name at least one type")


@dataclass(frozen=True)
class SeriesPolicy:
    chapter_question_floor: int = 10
    chapter_test_size: int = 10
    mixed_test_size: int = 20
    unit_test_size: int = 10
    set_size: int = 10

    def __post_init__(self) -> None:
        for name in (
            "chapter_question_floor",
            "chapter_test_size",
            "mixed_test_size",
            "unit_test_size",
            "set_size",
        ):
            value = getattr(self, name)
            if value < 1 or value > 200:
                raise ExamConfigError(f"{name} must be 1..200 (got {value})")


@dataclass(frozen=True)
class SimilarityPolicy:
    ngram: int = 8
    max_overlap: float = 0.2

    def __post_init__(self) -> None:
        if self.ngram < 3 or self.ngram > 20:
            raise ExamConfigError("similarity_ngram must be 3..20")
        if not 0.0 <= self.max_overlap <= 1.0:
            raise ExamConfigError("similarity_max_overlap must be in [0, 1]")


@dataclass(frozen=True)
class ExamCompliance:
    """The resolved compliance state a run is allowed to operate in."""

    content_mode: str
    clearance_id: str
    exact_pyq_enabled: bool
    clearance: ClearanceRow | None = None
    contact_email: str = ""

    @property
    def verbatim_allowed(self) -> bool:
        return self.content_mode == "attributed_verbatim" and self.clearance is not None

    @property
    def exact_pyq_visible(self) -> bool:
        return self.exact_pyq_enabled and self.verbatim_allowed

    def clearance_covers(
        self, *, class_num: int, subject: str, year: int, language: str
    ) -> bool:
        if self.clearance is None:
            return False
        return self.clearance.covers(
            class_num=class_num, subject=subject, year=year, language=language
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_mode": self.content_mode,
            "clearance_id": self.clearance_id or None,
            "clearance_present": self.clearance is not None,
            "verbatim_allowed": self.verbatim_allowed,
            "exact_pyq_enabled": self.exact_pyq_enabled,
            "exact_pyq_visible": self.exact_pyq_visible,
            "contact_email_configured": bool(self.contact_email),
        }


def _parse_bool(raw: Any, *, name: str) -> bool:
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in ("true", "1", "yes", "on"):
        return True
    if text in ("false", "0", "no", "off", ""):
        return False
    raise ExamConfigError(
        f"{name}: {raw!r} is not a boolean; use 'true' or 'false'. "
        "An unreadable compliance flag fails closed."
    )


def resolve_compliance(
    *,
    section: dict[str, Any],
    decision_log_path: Path,
    env: dict[str, str] | None = None,
) -> ExamCompliance:
    """Resolve and validate the compliance state. Raises on any ambiguity."""
    env = dict(os.environ if env is None else env)
    mode = (
        env.get(_ENV_MODE) or section.get("content_mode") or "blueprint_only"
    ).strip()
    if mode not in CONTENT_MODES:
        raise ExamConfigError(
            f"{_ENV_MODE}={mode!r} is not one of {list(CONTENT_MODES)}. "
            "An unknown mode fails closed (DEC-COMP-001)."
        )
    clearance_id = str(
        env.get(_ENV_CLEARANCE) or section.get("verbatim_clearance_id") or ""
    ).strip()
    exact_raw = env.get(_ENV_EXACT)
    exact_enabled = _parse_bool(
        exact_raw if exact_raw is not None else section.get("exact_pyq_enabled", False),
        name=_ENV_EXACT,
    )
    contact_email = str(env.get(_ENV_CONTACT) or "").strip()

    clearance = None
    if mode == "attributed_verbatim":
        if not clearance_id:
            raise ExamConfigError(
                f"{_ENV_MODE}=attributed_verbatim requires {_ENV_CLEARANCE} naming a "
                "row in docs/compliance/decision-log.md#clearance-register. "
                "No clearance id means no verbatim publishing."
            )
        rows = load_clearance_register(decision_log_path)
        clearance = find_clearance(rows, clearance_id)
        if clearance is None:
            raise ExamConfigError(
                f"{_ENV_CLEARANCE}={clearance_id!r} does not match any row in the "
                "compliance clearance register. A notice is not a clearance "
                "(DEC-COMP-001); add the instrument's row first."
            )
    elif clearance_id:
        # A clearance id in blueprint mode is not an error, but it is inert.
        # Resolve the row anyway so a typo is caught now rather than on the day
        # the mode flips.
        rows = load_clearance_register(decision_log_path)
        clearance = find_clearance(rows, clearance_id)
        if clearance is None:
            raise ExamConfigError(
                f"{_ENV_CLEARANCE}={clearance_id!r} does not match any row in the "
                "compliance clearance register."
            )

    if exact_enabled and not (mode == "attributed_verbatim" and clearance is not None):
        raise ExamConfigError(
            f"{_ENV_EXACT}=true requires {_ENV_MODE}=attributed_verbatim with a "
            "valid clearance id. The exact-PYQ series stays dark until "
            "DEC-COMP-001 has a clearance record."
        )

    return ExamCompliance(
        content_mode=mode,
        clearance_id=clearance_id,
        exact_pyq_enabled=exact_enabled,
        clearance=clearance,
        contact_email=contact_email,
    )


@dataclass(frozen=True)
class ExamConfig:
    repo_root: Path
    runs_dir: Path
    papers_dir: Path
    syllabus_path: Path
    chapters_dir: Path
    decision_log_path: Path
    compliance: ExamCompliance = field(
        default_factory=lambda: ExamCompliance(
            content_mode="blueprint_only", clearance_id="", exact_pyq_enabled=False
        )
    )
    export_dir: Path | None = None
    blueprint: BlueprintPolicy = field(default_factory=BlueprintPolicy)
    series: SeriesPolicy = field(default_factory=SeriesPolicy)
    similarity: SimilarityPolicy = field(default_factory=SimilarityPolicy)

    @property
    def content_mode(self) -> str:
        return self.compliance.content_mode

    def with_overrides(
        self,
        *,
        export_dir: Path | None = None,
        runs_dir: Path | None = None,
        compliance: ExamCompliance | None = None,
    ) -> ExamConfig:
        changes: dict[str, Any] = {}
        if export_dir is not None:
            changes["export_dir"] = export_dir
        if runs_dir is not None:
            changes["runs_dir"] = runs_dir
        if compliance is not None:
            changes["compliance"] = compliance
        return replace(self, **changes)

    @classmethod
    def from_config(
        cls,
        cfg: Any,
        *,
        export_dir: Path | None = None,
        runs_dir: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> ExamConfig:
        section = dict(DEFAULT_EXAM_SECTION)
        section.update(cfg.data.get("exam") or {})
        decision_log = cfg.repo_path(str(section["decision_log_path"]))
        compliance = resolve_compliance(
            section=section, decision_log_path=decision_log, env=env
        )
        export = export_dir
        if export is None and str(section.get("export_dir") or "").strip():
            export = cfg.repo_path(str(section["export_dir"]))
        runs = runs_dir or (cfg.repo_path(cfg.paths["runs"]) / "exam")
        return cls(
            repo_root=cfg.root,
            runs_dir=runs,
            papers_dir=cfg.repo_path(str(section["papers_dir"])),
            syllabus_path=cfg.repo_path(str(section["syllabus_path"])),
            chapters_dir=cfg.repo_path(str(section["chapters_dir"])),
            decision_log_path=decision_log,
            compliance=compliance,
            export_dir=export,
            blueprint=BlueprintPolicy(
                years_window=int(section["blueprint_years"]),
                recency_decay=float(section["recency_decay"]),
                include_paper_types=tuple(section["include_paper_types"]),
            ),
            series=SeriesPolicy(
                chapter_question_floor=int(section["chapter_question_floor"]),
                chapter_test_size=int(section["chapter_test_size"]),
                mixed_test_size=int(section["mixed_test_size"]),
                unit_test_size=int(section["unit_test_size"]),
                set_size=int(section["set_size"]),
            ),
            similarity=SimilarityPolicy(
                ngram=int(section["similarity_ngram"]),
                max_overlap=float(section["similarity_max_overlap"]),
            ),
        )

    @classmethod
    def for_repo(
        cls,
        repo_root: Path,
        *,
        runs_dir: Path | None = None,
        export_dir: Path | None = None,
        section: dict[str, Any] | None = None,
        env: dict[str, str] | None = None,
    ) -> ExamConfig:
        """Key-free configuration straight from the repo layout (tests/evals)."""
        merged = dict(DEFAULT_EXAM_SECTION)
        merged.update(section or {})
        root = Path(repo_root).resolve()
        decision_log = root / str(merged["decision_log_path"])
        compliance = resolve_compliance(
            section=merged, decision_log_path=decision_log, env=env or {}
        )
        return cls(
            repo_root=root,
            runs_dir=runs_dir or (root / "runs" / "exam"),
            papers_dir=root / str(merged["papers_dir"]),
            syllabus_path=root / str(merged["syllabus_path"]),
            chapters_dir=root / str(merged["chapters_dir"]),
            decision_log_path=decision_log,
            compliance=compliance,
            export_dir=export_dir,
            blueprint=BlueprintPolicy(
                years_window=int(merged["blueprint_years"]),
                recency_decay=float(merged["recency_decay"]),
                include_paper_types=tuple(merged["include_paper_types"]),
            ),
            series=SeriesPolicy(
                chapter_question_floor=int(merged["chapter_question_floor"]),
                chapter_test_size=int(merged["chapter_test_size"]),
                mixed_test_size=int(merged["mixed_test_size"]),
                unit_test_size=int(merged["unit_test_size"]),
                set_size=int(merged["set_size"]),
            ),
            similarity=SimilarityPolicy(
                ngram=int(merged["similarity_ngram"]),
                max_overlap=float(merged["similarity_max_overlap"]),
            ),
        )


def repo_root() -> Path:
    override = os.environ.get("ZIVON_REPO_ROOT", "").strip()
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[2]


__all__ = [
    "DEFAULT_EXAM_SECTION",
    "BlueprintPolicy",
    "ExamCompliance",
    "ExamConfig",
    "SeriesPolicy",
    "SimilarityPolicy",
    "repo_root",
    "resolve_compliance",
]
