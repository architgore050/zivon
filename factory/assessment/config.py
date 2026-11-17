"""Assessment-pipeline configuration.

Two layers, same split as the lesson factory (AGENTS.md):

- `config.json`'s `assessment` section carries BEHAVIOUR: where the syllabus
  and chapter data live, which generator is the default, the language set, the
  gate bounds and the bounded repair budget. Committed and reviewable.
- Environment variables (`ZIVON_BASE_URL`, `ZIVON_MODEL`, ...) carry the model
  endpoint, and only live generation (`--generator llm`) needs them. The
  default `seed` generator is key-free: a dry-run pack must build in CI.

`for_repo()` exists because the deterministic evals assemble packs without a
model endpoint and without the lesson factory's `Config` object.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from . import LANGUAGES
from .validators import ItemGatePolicy

GENERATORS = ("seed", "llm")

DEFAULT_ASSESSMENT_SECTION: dict[str, Any] = {
    "syllabus_path": "sources/syllabus/syllabus.json",
    "chapters_dir": "sources/syllabus/chapters",
    "export_dir": "",
    "generator": "seed",
    "languages": list(LANGUAGES),
    "min_items_per_chapter": 15,
    "max_items_per_chapter": 20,
    "max_items_per_concept": 6,
    "speaking_prompts_min": 3,
    "item_repair_rounds": 2,
    "time_prior_min_ms": 15000,
    "time_prior_max_ms": 300000,
}


class AssessmentConfigError(ValueError):
    """A configuration value the assessment pipeline cannot run with."""


@dataclass(frozen=True)
class AssessmentConfig:
    repo_root: Path
    runs_dir: Path
    syllabus_path: Path
    chapters_dir: Path
    frontend_dir: Path
    catalog_path: Path
    export_dir: Path | None = None
    generator: str = "seed"
    languages: tuple[str, ...] = LANGUAGES
    policy: ItemGatePolicy = field(default_factory=ItemGatePolicy)
    repair_rounds: int = 2
    model_cfg: Any | None = None

    def __post_init__(self) -> None:
        if self.generator not in GENERATORS:
            raise AssessmentConfigError(
                f"assessment generator {self.generator!r} is not one of {GENERATORS}"
            )
        if tuple(self.languages) != LANGUAGES:
            raise AssessmentConfigError(
                "assessment languages are fixed to EN/HI/Hinglish for practice and "
                f"speaking (FEATURE-MAP #3); got {list(self.languages)}"
            )

    # -- derived paths ------------------------------------------------------
    def chapter_items_path(self, chapter_id: str) -> Path:
        return self.chapters_dir / f"{chapter_id}.items.json"

    def chapter_speaking_path(self, chapter_id: str) -> Path:
        return self.chapters_dir / f"{chapter_id}.speaking.json"

    def with_overrides(
        self,
        *,
        export_dir: Path | None = None,
        generator: str | None = None,
        runs_dir: Path | None = None,
    ) -> AssessmentConfig:
        changes: dict[str, Any] = {}
        if export_dir is not None:
            changes["export_dir"] = export_dir
        if generator is not None:
            changes["generator"] = generator
        if runs_dir is not None:
            changes["runs_dir"] = runs_dir
        return replace(self, **changes)

    @classmethod
    def from_config(
        cls,
        cfg: Any,
        *,
        generator: str | None = None,
        export_dir: Path | None = None,
        runs_dir: Path | None = None,
    ) -> AssessmentConfig:
        """Build from the lesson factory's `Config` (its `assessment` section).

        `generator`/`export_dir`/`runs_dir` are CLI overrides, so an operator
        can try a live run or an alternate export target without editing the
        committed config.
        """
        section = dict(DEFAULT_ASSESSMENT_SECTION)
        section.update(cfg.data.get("assessment") or {})
        policy = ItemGatePolicy(
            min_items=int(section["min_items_per_chapter"]),
            max_items=int(section["max_items_per_chapter"]),
            max_items_per_concept=int(section["max_items_per_concept"]),
            speaking_prompts_min=int(section["speaking_prompts_min"]),
            time_prior_min_ms=int(section["time_prior_min_ms"]),
            time_prior_max_ms=int(section["time_prior_max_ms"]),
        )
        runs = runs_dir or (cfg.repo_path(cfg.paths["runs"]) / "assessment")
        export = export_dir
        if export is None and str(section.get("export_dir") or "").strip():
            export = cfg.repo_path(str(section["export_dir"]))
        return cls(
            repo_root=cfg.root,
            runs_dir=runs,
            syllabus_path=cfg.repo_path(section["syllabus_path"]),
            chapters_dir=cfg.repo_path(section["chapters_dir"]),
            frontend_dir=cfg.repo_path(cfg.paths["frontend"]),
            catalog_path=cfg.repo_path(cfg.paths["catalog"]),
            export_dir=export,
            generator=generator or str(section["generator"]),
            languages=tuple(section["languages"]),
            policy=policy,
            repair_rounds=int(section["item_repair_rounds"]),
            model_cfg=cfg,
        )

    @classmethod
    def for_repo(
        cls,
        repo_root: Path,
        *,
        runs_dir: Path | None = None,
        export_dir: Path | None = None,
        generator: str = "seed",
        section: dict[str, Any] | None = None,
    ) -> AssessmentConfig:
        """Key-free configuration straight from the repo layout (evals/tests)."""
        merged = dict(DEFAULT_ASSESSMENT_SECTION)
        merged.update(section or {})
        policy = ItemGatePolicy(
            min_items=int(merged["min_items_per_chapter"]),
            max_items=int(merged["max_items_per_chapter"]),
            max_items_per_concept=int(merged["max_items_per_concept"]),
            speaking_prompts_min=int(merged["speaking_prompts_min"]),
            time_prior_min_ms=int(merged["time_prior_min_ms"]),
            time_prior_max_ms=int(merged["time_prior_max_ms"]),
        )
        root = Path(repo_root).resolve()
        return cls(
            repo_root=root,
            runs_dir=runs_dir or (root / "runs" / "assessment"),
            syllabus_path=root / str(merged["syllabus_path"]),
            chapters_dir=root / str(merged["chapters_dir"]),
            frontend_dir=root / "frontend",
            catalog_path=root / "sources" / "catalog.json",
            export_dir=export_dir,
            generator=generator,
            languages=tuple(merged["languages"]),
            policy=policy,
            repair_rounds=int(merged["item_repair_rounds"]),
        )


def catalog_book_ids(path: Path) -> set[str]:
    """The catalog is the only place the pipeline learns about source books."""
    import json

    if not path.is_file():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(book["id"]) for book in data.get("books", []) if book.get("id")}


def repo_root() -> Path:
    """`ZIVON_REPO_ROOT` exists for tests that move the tree; default is the
    checkout this module ships in."""
    override = os.environ.get("ZIVON_REPO_ROOT", "").strip()
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[2]


__all__ = [
    "DEFAULT_ASSESSMENT_SECTION",
    "GENERATORS",
    "AssessmentConfig",
    "AssessmentConfigError",
    "catalog_book_ids",
    "repo_root",
]
