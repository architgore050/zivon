"""The generator seam for practice items and speaking prompts.

Two implementations behind one small interface:

- `SeedItemGenerator` is the key-free default: it reads the curated bank
  tracked under `sources/syllabus/chapters/`. CI, the deterministic evals and
  this wave's dry-run pack all use it.
- `LLMItemGenerator` is the live path (Q-10): DeepSeek V4.1 Flash through the
  existing `llm_manager` OpenAI-format transport, called via
  `factory.llm.LLMClient` so retries, validation rounds, attempt artifacts and
  the `factory.call.*` events are the factory's, not a second HTTP client's.

`repair()` returns `None` when a generator cannot improve a failing bank (the
seed path has no model to ask), which the A3 catcher treats as an honest
plateau and fails the stage instead of looping.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .config import AssessmentConfig, catalog_book_ids
from .errors import AssessmentStageError
from .schemas import ASSESSMENT_ITEM_BANK, ASSESSMENT_SPEAKING_BANK
from .validators import ItemGatePolicy, blocking_issues, validate_item_bank

PROMPT_VERSION = "asm-1"

_MAX_SOURCE_CHARS = 40_000


@dataclass
class GenerationResult:
    bank: dict[str, Any]
    generator: str
    model_calls: int = 0
    attempts: int = 0
    round_history: list[dict[str, Any]] = field(default_factory=list)


class ItemGenerator(Protocol):
    name: str

    def generate_items(self, chapter: dict[str, Any]) -> GenerationResult: ...

    def repair_items(
        self, chapter: dict[str, Any], previous: dict[str, Any], report: dict[str, Any]
    ) -> GenerationResult | None: ...

    def generate_speaking(self, chapter: dict[str, Any]) -> GenerationResult: ...


def _load_json(path: Path, what: str) -> dict[str, Any]:
    if not path.is_file():
        raise AssessmentStageError(
            f"{what} not found at {path}. The seed content is tracked data; "
            "see docs/content-factory/assessment.md."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AssessmentStageError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise AssessmentStageError(f"{path} must contain a JSON object")
    return data


class SeedItemGenerator:
    """Read the curated bank + speaking prompts from tracked chapter data."""

    name = "seed"

    def __init__(self, cfg: AssessmentConfig):
        self.cfg = cfg

    def generate_items(self, chapter: dict[str, Any]) -> GenerationResult:
        bank = _load_json(
            self.cfg.chapter_items_path(chapter["chapter_id"]),
            f"practice seed bank for {chapter['chapter_id']}",
        )
        return GenerationResult(bank=bank, generator=f"seed-{PROMPT_VERSION}")

    def repair_items(
        self, chapter: dict[str, Any], previous: dict[str, Any], report: dict[str, Any]
    ) -> GenerationResult | None:
        # No model, no repair: the gate fails with the full report. Re-running
        # the same seed would be a silent no-op loop.
        return None

    def generate_speaking(self, chapter: dict[str, Any]) -> GenerationResult:
        bank = _load_json(
            self.cfg.chapter_speaking_path(chapter["chapter_id"]),
            f"speaking seed bank for {chapter['chapter_id']}",
        )
        return GenerationResult(bank=bank, generator=f"seed-{PROMPT_VERSION}")


def _compact_concepts(chapter: dict[str, Any]) -> str:
    return "\n".join(
        f"- {c['concept_id']} | {c['title']} | NCERT sections {', '.join(c['section_refs'])}"
        for c in chapter["concepts"]
    )


def _source_excerpt(cfg: AssessmentConfig, chapter: dict[str, Any]) -> str | None:
    """Best-effort: the located NCERT text of a lesson run, when one exists.

    Live generation is better grounded with the chapter text, but the
    assessment pipeline must also run on a machine with no lesson run at all.
    We scan the lesson runs' `01-locate/output.json` for a chapter whose book +
    title agree; anything else is not evidence and is ignored.
    """
    model_cfg = cfg.model_cfg
    if model_cfg is None:
        return None
    runs_root = Path(model_cfg.repo_path(model_cfg.paths["runs"]))
    if not runs_root.is_dir():
        return None
    wanted_title = " ".join(chapter["title"].lower().split())
    for locate in sorted(runs_root.glob("*/01-locate/output.json")):
        try:
            data = json.loads(locate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        located = data.get("chapter") or {}
        title = " ".join(str(located.get("title", "")).lower().split())
        if (
            located.get("book_id") == chapter["book_id"]
            and title == wanted_title
            and data.get("ncert_text")
        ):
            return str(data["ncert_text"])[:_MAX_SOURCE_CHARS]
    return None


def _item_prompt(
    cfg: AssessmentConfig, chapter: dict[str, Any], policy: ItemGatePolicy
) -> tuple[str, str]:
    """Goal-first prompt: the model is told what the student needs, not just
    what JSON shape to emit. Harness guarantees (schema, answer integrity,
    duplicate detection, language completeness) live in the validator."""
    system = (
        "You are an experienced Indian school Physics teacher writing practice "
        "items for a Class {cls} student who has just read NCERT chapter "
        "'{title}' ({book}).\n\n"
        "The student needs retrieval practice and honest calculation practice, "
        "not trivia. Every item must be answerable from the named chapter "
        "sections alone; a concept the chapter does not teach is out of scope.\n\n"
        "Hard rules:\n"
        "- Exactly one correct answer per objective item; four options.\n"
        "- Explanation says WHY the answer is right (and, for MCQ, why the "
        "distractor is tempting).\n"
        "- Cite the NCERT section each item comes from (`source_ref.section`).\n"
        "- Do not copy the lesson's own check questions verbatim.\n"
        "- Write every item in English, Hindi (Devanagari) and Hinglish "
        "(Roman script); physics symbols and units stay Latin.\n"
        "- Keep numbers physically sensible and internally consistent.\n"
        "- No school names, no student data, no copyrighted textbook prose."
    ).format(
        cls=chapter["class"],
        title=chapter["title"],
        book=chapter["book_id"],
    )
    type_min = ", ".join(f"{t} >= {n}" for t, n in policy.min_type_counts.items())
    diff_mix = ", ".join(
        f"{d} {low:.0%}-{high:.0%}"
        for d, (low, high) in policy.difficulty_share.items()
    )
    parts = [
        (
            f"Chapter: {chapter['title']} (class {chapter['class']}, "
            f"NCERT {chapter['book_id']}, chapter {chapter['number']})."
        ),
        "Curated concepts (use these exact ids):",
        _compact_concepts(chapter),
        "",
        (
            f"Write {policy.min_items}-{policy.max_items} items. Type minimums: "
            f"{type_min}. Difficulty mix: {diff_mix}. Marks: 1 for "
            "MCQ/assertion-reason, 1-2 for numerical. `computation_steps` is the "
            "number of arithmetic steps a student actually performs (0 for recall)."
        ),
        "",
        "Item types:",
        "- mcq: a stem and four options; `answer.index` is the correct option.",
        (
            "- numeric: a numerical problem; `answer` is {value, tolerance, unit}; "
            "no options."
        ),
        (
            "- assertion_reason: prompt contains 'Assertion: ...' and "
            "'Reason: ...'; the four options are the standard (A) both true, R "
            "explains A; (B) both true, R does not explain A; (C) A true, R "
            "false; (D) A false, R true."
        ),
        "",
        "Return JSON with this shape:",
        (
            f'{{"schema_version": 1, "chapter_id": "{chapter["chapter_id"]}", '
            f'"class": {chapter["class"]}, "generator": "{PROMPT_VERSION}", '
            f'"source": {{"book_id": "{chapter["book_id"]}", '
            f'"chapter_number": {chapter["number"]}, '
            f'"chapter_title": "{chapter["title"]}", '
            '"source_type": "generated"}, "items": [ ... ]}'
        ),
        (
            "Each item: item_id (q-<short-slug>-NNN), concept_id, type, "
            "difficulty, marks, computation_steps, source_ref {book_id, section, "
            "example}, answer, distractor_index (optional), locales {en, hi, "
            "hi-Latn}, where a locale carries prompt, options (except numeric), "
            "explanation, misconception (optional)."
        ),
    ]
    source_text = _source_excerpt(cfg, chapter)
    if source_text:
        parts.extend(
            [
                "",
                "NCERT chapter text (the only ground truth):",
                source_text,
            ]
        )
    return system, "\n".join(parts)


class LLMItemGenerator:
    """Live generation through `factory.llm.LLMClient` (Q-10)."""

    name = "llm"

    def __init__(
        self,
        cfg: AssessmentConfig,
        chapter: dict[str, Any],
        client: Any,
        policy: ItemGatePolicy,
    ):
        self.cfg = cfg
        self.chapter = chapter
        self.client = client
        self.policy = policy
        self._book_ids = catalog_book_ids(cfg.catalog_path)

    # -- items --------------------------------------------------------------
    def generate_items(self, chapter: dict[str, Any]) -> GenerationResult:
        system, user = _item_prompt(self.cfg, chapter, self.policy)
        bank = self._call(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )
        return GenerationResult(
            bank=bank, generator=f"llm-{PROMPT_VERSION}", model_calls=1
        )

    def repair_items(
        self, chapter: dict[str, Any], previous: dict[str, Any], report: dict[str, Any]
    ) -> GenerationResult | None:
        reasons = [
            f"- [{i['severity']}] {i['rule']}: {i['message']}"
            for i in blocking_issues(report)
        ]
        if not reasons:
            return None
        system, user = _item_prompt(self.cfg, chapter, self.policy)
        user = (
            user + "\n\nThe previous batch failed the deterministic gate. Fix exactly "
            "these findings and return the COMPLETE corrected bank (not a patch):\n"
            + "\n".join(reasons)
        )
        bank = self._call(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )
        return GenerationResult(
            bank=bank, generator=f"llm-{PROMPT_VERSION}", model_calls=1
        )

    def _call(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        def extra_validator(parsed: dict[str, Any]) -> list[str]:
            try:
                issues = validate_item_bank(
                    parsed,
                    self.chapter,
                    self.policy,
                    catalog_book_ids=self._book_ids,
                )
            except Exception as exc:  # noqa: BLE001 - shape errors are model feedback
                return [str(exc)]
            return [
                f"[{i.severity}] {i.rule}: {i.message}"
                for i in issues
                if i.severity in ("fatal", "major")
            ]

        return self.client.call(
            "A3-practice-items",
            messages,
            ASSESSMENT_ITEM_BANK,
            "ASSESSMENT_ITEM_BANK",
            extra_validator=extra_validator,
        )

    # -- speaking -----------------------------------------------------------
    def generate_speaking(self, chapter: dict[str, Any]) -> GenerationResult:
        system = (
            "You write voice explain-back prompts for an Indian school Physics "
            "class. A student will speak an answer out loud for about 45 seconds; "
            "an assessor will look for a few key ideas, not exact wording. Write "
            "kind, concrete prompts; the model answer is a model, not a script."
        )
        user = "\n".join(
            [
                (
                    f"Chapter: {chapter['title']} (class {chapter['class']}, "
                    f"NCERT {chapter['book_id']}, chapter {chapter['number']})."
                ),
                "Curated concepts (use these exact ids):",
                _compact_concepts(chapter),
                "",
                (
                    f"Write {self.policy.speaking_prompts_min} prompts. For each: "
                    "prompt_id (spk-<slug>-NNN), concept_ids, source_ref {book_id, "
                    "section}, thresholds {pass_ratio, strong_ratio, "
                    "min_key_ideas, max_duration_s}, and locales {en, hi, "
                    "hi-Latn}. Each locale needs prompt, 3-5 key_ideas (short "
                    "checkable statements) and a model_answer that uses only "
                    "ideas taught in the cited section."
                ),
                "",
                (
                    '{"schema_version": 1, "chapter_id": '
                    f'"{chapter["chapter_id"]}", "class": {chapter["class"]}, '
                    '"prompts": [...]}'
                ),
            ]
        )
        bank = self.client.call(
            "A4-speaking-rubrics",
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            ASSESSMENT_SPEAKING_BANK,
            "ASSESSMENT_SPEAKING_BANK",
            extra_validator=self._speaking_validator,
        )
        return GenerationResult(
            bank=bank, generator=f"llm-{PROMPT_VERSION}", model_calls=1
        )

    def _speaking_validator(self, parsed: dict[str, Any]) -> list[str]:
        from .validators import validate_speaking_bank

        try:
            issues = validate_speaking_bank(
                parsed,
                self.chapter,
                self.policy,
                catalog_book_ids=self._book_ids,
            )
        except Exception as exc:  # noqa: BLE001 - shape errors are model feedback
            return [str(exc)]
        return [
            f"[{i.severity}] {i.rule}: {i.message}"
            for i in issues
            if i.severity in ("fatal", "major")
        ]


def make_generator(
    cfg: AssessmentConfig,
    chapter: dict[str, Any],
    *,
    llm_client: Any | None = None,
) -> ItemGenerator:
    if cfg.generator == "seed":
        return SeedItemGenerator(cfg)
    if cfg.generator == "llm":
        if llm_client is None:
            raise AssessmentStageError(
                "generator=llm needs a model endpoint: set ZIVON_BASE_URL and "
                "ZIVON_MODEL (Q-10 routes generation through llm_manager). "
                "No key is ever read from a file or committed."
            )
        return LLMItemGenerator(cfg, chapter, llm_client, cfg.policy)
    raise AssessmentStageError(f"unknown assessment generator {cfg.generator!r}")


__all__ = [
    "PROMPT_VERSION",
    "GenerationResult",
    "ItemGenerator",
    "LLMItemGenerator",
    "SeedItemGenerator",
    "make_generator",
]
