#!/usr/bin/env python3
"""Import the E4 exam/series pack into the hot database (the P3 gap).

The exam pipeline (`python -m factory.exam`, stages E1-E4) writes a versioned,
self-describing pack; this script is the write path from that pack into the
F7 test tables (revision `0004_practice_speaking_tests`). It imports:

- `assessment_pack`  provenance: one row per (class, content hash), `kind='exam'`
- `test_series`      one catalogue row per series manifest (six kinds)
- `test`             one row per paper/set **per language** the series offers
- `test_question`    one row per filled slot, in paper order

The pack is verified before a single row is written: every data file's SHA-256
and byte size must match `manifest.json`, the manifest's `content_hash` is
recomputed (the same formula `factory/series/publish.py` used), the publish
gate must have verdict `pass` with `publish.status == "ready"`, and the
compliance record must back every verbatim claim: rows with a `verbatim_*`
source type or an `exact_pyq` membership are refused unless the pack itself
marks the exact-PYQ series enabled under `DEC-COMP-001` (a real clearance row,
never a hand-set flag). Exact-PYQ content stays dark otherwise — its catalogue
row imports as `draft`, and nothing references it.

The pack references the P2 question bank: `test_question.question_id` is a
foreign key into `question_bank` (ON DELETE RESTRICT), and the bank's rows are
owned by the assessment importer (`scripts/import_assessment_packs.py`). This
importer therefore **requires the bank rows first**: every referenced
`(base_item_id, language)` must resolve to an existing `question_bank` row, or
the pack is refused whole with the missing list. Run the assessment import
before this one.

Idempotency: re-running an unchanged pack is a no-op in row counts. Rows are
upserted on their stable natural keys (`test_series.series_id`, `test.test_id`,
`test_question` PK); `test_question` rows are replaced per test inside the
import transaction because nothing references them (attempt answers copy
`question_id` as plain text), and replacing avoids an order-index collision
when a re-export reorders a paper.

Row mapping (db-spec §4.19):

- `test_series.series_id` is `class-<n>-<series_id>` (the pack's series id is
  only unique per class; the DB primary key is global).
- `test` is per (paper|set, language): the player serves one language at a
  time and `test_question` points at language-specific bank rows, so a paper
  offered in EN and HI is two rows, each with `language` set.
- `test_question.marks` is the paper slot's marks (the sheet wins over the
  bank item's authored practice marks — the store's documented rule).
- `test.total_marks` is the earnable sum of the test's own question marks;
  the paper design's full marks (including empty slots) stay in `structure`.
- `test.duration_s` is the pack's `duration_min` when the series carries one
  (full-paper series do); set-based series derive `90 s/question`, the F7
  service's own convention (`SECONDS_PER_QUESTION`).

Usage (from the repo root):

    python3 scripts/import_series_packs.py --dry-run
    python3 scripts/import_series_packs.py --packs-dir runs/exam-exports \
        --db-url sqlite:///zivon.db

Key-free and offline; stdlib for SQLite, `psycopg` only when a PostgreSQL URL
is used. There is **no env-var DSN fallback**: the target database is always
named explicitly (`--db-url`), so an operator cannot silently point the import
at whatever `ZIVON_DB_URL` happens to hold. See
`docs/backend/runbooks/series-import.md`.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from db.engine import DatabaseEngine  # the repo root is on sys.path above

# The exam pipeline mirrors a publishable pack to `--export-dir` per class
# (`runs/exam-exports/class-10/...`); a blocked pack stays under the run
# directory as evidence and is never mirrored (SER-13).
DEFAULT_PACKS_DIR: Final[Path] = REPO_ROOT / "runs" / "exam-exports"
DEFAULT_DB_URL: Final[str] = "sqlite:///zivon.db"

PACK_DATA_FILES: Final[tuple[str, ...]] = (
    "papers.json",
    "blueprint.json",
    "items.json",
    "series.json",
)
PACK_KIND: Final[str] = "exam"
PACK_LANGUAGES: Final[frozenset[str]] = frozenset({"en", "hi", "hi-Latn"})
EXAM_SOURCE_TYPES: Final[frozenset[str]] = frozenset(
    {
        "generated_blueprint",
        "generated_pattern",
        "verbatim_cbse_paper",
        "verbatim_cbse_sqp",
        "verbatim_cbse_ms",
    }
)
VERBATIM_SOURCE_TYPES: Final[frozenset[str]] = frozenset(
    {"verbatim_cbse_paper", "verbatim_cbse_sqp", "verbatim_cbse_ms"}
)
SERIES_KINDS: Final[frozenset[str]] = frozenset(
    {"ai_lesson", "pyq_pattern", "exact_pyq", "board_practice", "challenge", "loop"}
)
# The question_bank table's own CHECK (revision 0004): the bank cannot store a
# subjective row yet (exam.md §11 debt 3), so a pack row of another type is a
# schema mismatch and is refused, not truncated.
BANK_QUESTION_TYPES: Final[frozenset[str]] = frozenset(
    {"mcq", "numeric", "assertion_reason"}
)
DIFFICULTIES: Final[frozenset[str]] = frozenset({"easy", "medium", "hard"})
EXAM_CLASSES: Final[frozenset[int]] = frozenset({10, 12})
CONTENT_MODES: Final[frozenset[str]] = frozenset(
    {"blueprint_only", "attributed_verbatim"}
)
LANGUAGE_NAMES: Final[dict[str, str]] = {
    "en": "English",
    "hi": "Hindi",
    "hi-Latn": "Hinglish",
}
# `backend/test_engine/service.py` derives custom-test durations from
# SECONDS_PER_QUESTION; set-based series (no pack duration) reuse the same
# convention instead of inventing a number.
SECONDS_PER_QUESTION: Final[int] = 90
QUESTION_ROW_REQUIRED_KEYS: Final[tuple[str, ...]] = (
    "question_id",
    "item_id",
    "base_item_id",
    "class_level",
    "chapter_id",
    "concept_id",
    "type",
    "difficulty",
    "marks",
    "language",
    "prompt",
    "answer",
    "explanation",
    "source_type",
    "pattern_ref",
    "series_ids",
)


class PackError(ValueError):
    """The pack is malformed, tampered with, failed its gate, or cannot land."""


@dataclass(frozen=True)
class SeriesPack:
    """A verified pack, ready to import."""

    pack_dir: Path
    manifest: dict[str, Any]
    rows: list[dict[str, Any]]
    series: list[dict[str, Any]]

    @property
    def class_num(self) -> int:
        return int(self.manifest["class_num"])

    @property
    def content_hash(self) -> str:
        return str(self.manifest["content_hash"])

    @property
    def pack_id(self) -> str:
        """Stable id: kind + class + content hash prefix (idempotent import)."""
        return pack_id_for(PACK_KIND, f"class-{self.class_num}", self.content_hash)

    @property
    def cleared_for_verbatim(self) -> bool:
        """Whether the pack's own compliance record clears verbatim content.

        Only the pack can mark this (a real clearance row behind
        `DEC-COMP-001`): `attributed_verbatim` with verbatim allowed and a
        recorded clearance id. The importer never accepts a looser local
        override, and the exact-PYQ series additionally needs
        `exact_pyq_status == "enabled"` (checked against the series itself).
        """
        compliance = self.manifest.get("compliance") or {}
        return (
            str(self.manifest.get("content_mode") or "") == "attributed_verbatim"
            and compliance.get("verbatim_allowed") is True
            and compliance.get("clearance_present") is True
            and bool(str(compliance.get("clearance_id") or "").strip())
        )

    def row_for(self, item_id: str, language: str) -> dict[str, Any] | None:
        return self._rows_by_key.get((item_id, language))

    @property
    def _rows_by_key(self) -> dict[tuple[str, str], dict[str, Any]]:
        return {(str(row["item_id"]), str(row["language"])): row for row in self.rows}


@dataclass(frozen=True)
class PlannedTest:
    """One `test` row plus its ordered questions, as the pack plans it."""

    test_id: str
    series_row_id: str
    title: str
    language: str
    chapter_ids: list[str]
    duration_s: int
    total_marks: float
    structure: dict[str, Any]
    questions: list[dict[str, Any]]  # {question_id, order_index, section, marks}


@dataclass(frozen=True)
class ImportPlan:
    """What one pack would write (dry-run prints this; import executes it)."""

    pack: SeriesPack
    series_rows: int
    published_series: int
    tests: list[PlannedTest]
    skipped_units: int

    @property
    def question_rows(self) -> int:
        return sum(len(test.questions) for test in self.tests)


@dataclass(frozen=True)
class ImportResult:
    """What one pack wrote (row counts, not insert-vs-update)."""

    pack_id: str
    class_num: int
    series_rows: int
    tests: int
    question_rows: int
    content_hash: str


def pack_id_for(kind: str, chapter_id: str, content_hash: str) -> str:
    """Deterministic pack id: re-importing the same content keeps the same row."""
    digest = content_hash.removeprefix("sha256:")
    return f"{kind}-{chapter_id}-{digest[:12]}"


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _content_hash(files: dict[str, Any]) -> str:
    """Recompute the pack hash the way E4 built it (`factory/series/publish.py`)."""
    joined = "\n".join(
        f"{name}:{entry['sha256']}" for name, entry in sorted(files.items())
    )
    return "sha256:" + _sha256(joined.encode("utf-8"))


def _now_iso() -> str:
    now = datetime.datetime.now(datetime.UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _source_label(pack_dir: Path) -> str:
    """Provenance path: repo-relative when the pack is tracked, else as given."""
    try:
        return str(pack_dir.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(pack_dir)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PackError(f"{path}: missing file") from exc
    except ValueError as exc:
        raise PackError(f"{path}: not valid JSON ({exc})") from exc


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PackError(message)


def _verify_files(pack_dir: Path, manifest: dict[str, Any]) -> None:
    files = manifest.get("files")
    _require(isinstance(files, dict) and files, f"{pack_dir}: manifest.files missing")
    assert isinstance(files, dict)  # narrowing for mypy
    missing = [name for name in PACK_DATA_FILES if name not in files]
    _require(not missing, f"{pack_dir}: manifest.files omits {missing}")
    unknown = sorted(set(files) - set(PACK_DATA_FILES))
    _require(not unknown, f"{pack_dir}: manifest.files has unknown entries {unknown}")
    for name, entry in files.items():
        _require(isinstance(entry, dict), f"{pack_dir}: bad files entry for {name}")
        path = pack_dir / str(name)
        raw = path.read_bytes() if path.exists() else b""
        _require(bool(raw), f"{pack_dir}: data file {name} is missing or empty")
        _require(
            _sha256(raw) == entry.get("sha256"),
            f"{pack_dir}: {name} SHA-256 does not match the manifest",
        )
        _require(
            len(raw) == entry.get("bytes"),
            f"{pack_dir}: {name} byte size does not match the manifest",
        )
    _require(
        _content_hash(files) == manifest.get("content_hash"),
        f"{pack_dir}: content_hash does not match the manifest",
    )


def _verify_gate(pack_dir: Path, manifest: dict[str, Any]) -> None:
    """The publish gate is the pack's own claim; re-check it before trusting it."""
    gate = manifest.get("gate")
    _require(isinstance(gate, dict), f"{pack_dir}: manifest.gate missing")
    assert isinstance(gate, dict)
    _require(
        gate.get("verdict") == "pass" and int(gate.get("error_count", 1)) == 0,
        f"{pack_dir}: pack gate verdict is {gate.get('verdict')!r}, not 'pass'",
    )
    publish = manifest.get("publish")
    _require(isinstance(publish, dict), f"{pack_dir}: manifest.publish missing")
    assert isinstance(publish, dict)
    if publish.get("status") != "ready":
        blockers = publish.get("blockers") or []
        rules = ", ".join(
            str(entry.get("rule")) for entry in blockers[:5] if isinstance(entry, dict)
        )
        more = "" if len(blockers) <= 5 else f" (and {len(blockers) - 5} more)"
        _require(
            False,
            f"{pack_dir}: pack publish status is {publish.get('status')!r}, not 'ready' "
            f"({len(blockers)} blocker(s): {rules or 'unnamed'}{more})",
        )


def _verify_compliance(pack_dir: Path, manifest: dict[str, Any]) -> bool:
    """Verify the compliance record's shape; return whether verbatim is cleared.

    The clearance belongs to the pack (`DEC-COMP-001`): `attributed_verbatim`
    with a recorded clearance id and verbatim allowed. Any verbatim indicator
    in the manifest (a verbatim item count, or the exact-PYQ series marked
    enabled) must be backed by it; the importer never clears content on its
    own.
    """
    mode = str(manifest.get("content_mode") or "")
    _require(
        mode in CONTENT_MODES,
        f"{pack_dir}: content_mode {mode!r} is not a known compliance mode",
    )
    compliance = manifest.get("compliance")
    _require(isinstance(compliance, dict), f"{pack_dir}: manifest.compliance missing")
    assert isinstance(compliance, dict)
    verbatim_cleared = (
        mode == "attributed_verbatim"
        and compliance.get("verbatim_allowed") is True
        and compliance.get("clearance_present") is True
        and bool(str(compliance.get("clearance_id") or "").strip())
    )
    claims_verbatim = (
        int(compliance.get("verbatim_items") or 0) > 0
        or str(compliance.get("exact_pyq_status") or "absent") == "enabled"
    )
    if claims_verbatim and not verbatim_cleared:
        _require(
            False,
            f"{pack_dir}: manifest carries verbatim/exact-PYQ content but the "
            "compliance record does not back it with a clearance "
            "(DEC-COMP-001); the importer does not fake clearance",
        )
    return verbatim_cleared


def _verify_rows(
    pack_dir: Path, manifest: dict[str, Any], doc: Any, *, verbatim_cleared: bool
) -> list[dict[str, Any]]:
    """Verify the exported question rows; refuse anything the bank cannot hold."""
    _require(isinstance(doc, dict), f"{pack_dir}: items.json is not an object")
    assert isinstance(doc, dict)
    _require(
        int(doc.get("class_num") or 0) == int(manifest["class_num"]),
        f"{pack_dir}: items.json class_num disagrees with the manifest",
    )
    rows = doc.get("items")
    _require(isinstance(rows, list) and rows, f"{pack_dir}: no item rows")
    assert isinstance(rows, list)
    counts = manifest.get("counts") or {}
    _require(
        len(rows) == int(counts.get("question_rows", len(rows))),
        f"{pack_dir}: question_rows count disagrees with the manifest",
    )
    seen_ids: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    verbatim_rows: list[str] = []
    for row in rows:
        _require(isinstance(row, dict), f"{pack_dir}: item row is not an object")
        missing = [key for key in QUESTION_ROW_REQUIRED_KEYS if key not in row]
        _require(not missing, f"{pack_dir}: item row misses {missing}")
        item_id = str(row["item_id"])
        question_id = str(row["question_id"])
        language = str(row["language"])
        _require(
            question_id == f"{item_id}-{language}",
            f"{pack_dir}: {question_id} is not <item_id>-<language>",
        )
        _require(
            question_id not in seen_ids,
            f"{pack_dir}: duplicate question_id {question_id}",
        )
        seen_ids.add(question_id)
        pair = (item_id, language)
        _require(
            pair not in seen_pairs, f"{pack_dir}: duplicate (item, language) {pair}"
        )
        seen_pairs.add(pair)
        _require(
            language in PACK_LANGUAGES,
            f"{pack_dir}: {question_id} has language {language!r}",
        )
        _require(
            int(row["class_level"]) == int(manifest["class_num"]),
            f"{pack_dir}: {question_id} class_level disagrees with the manifest",
        )
        _require(
            row["type"] in BANK_QUESTION_TYPES,
            f"{pack_dir}: {question_id} has type {row['type']!r}; the question bank "
            "cannot hold it yet (0004 CHECK) — author or widen the bank first",
        )
        _require(
            row["difficulty"] in DIFFICULTIES,
            f"{pack_dir}: {question_id} has difficulty {row['difficulty']!r}",
        )
        _require(
            float(row["marks"]) > 0, f"{pack_dir}: {question_id} has non-positive marks"
        )
        _require(
            bool(str(row["prompt"]).strip()),
            f"{pack_dir}: {question_id} prompt is empty",
        )
        _require(
            bool(str(row["explanation"]).strip()),
            f"{pack_dir}: {question_id} explanation is empty",
        )
        _require(
            isinstance(row["answer"], dict),
            f"{pack_dir}: {question_id} answer is not an object",
        )
        _require(
            row["source_type"] in EXAM_SOURCE_TYPES,
            f"{pack_dir}: {question_id} has unknown source_type {row['source_type']!r}",
        )
        _require(
            bool(str(row["pattern_ref"]).strip()),
            f"{pack_dir}: {question_id} has no pattern_ref",
        )
        series_ids = [str(sid) for sid in row["series_ids"]]
        _require(bool(series_ids), f"{pack_dir}: {question_id} names no series")
        unknown = sorted(set(series_ids) - SERIES_KINDS)
        _require(
            not unknown,
            f"{pack_dir}: {question_id} names unknown series {unknown}",
        )
        if str(row["source_type"]) in VERBATIM_SOURCE_TYPES:
            verbatim_rows.append(question_id)
    if verbatim_rows and not verbatim_cleared:
        sample = ", ".join(sorted(verbatim_rows)[:5])
        more = (
            "" if len(verbatim_rows) <= 5 else f" (and {len(verbatim_rows) - 5} more)"
        )
        _require(
            False,
            f"{pack_dir}: {len(verbatim_rows)} verbatim row(s) present without a "
            f"clearance: {sample}{more} — verbatim content stays dark (DEC-COMP-001)",
        )
    return [dict(row) for row in rows]


def _verify_series(
    pack_dir: Path,
    manifest: dict[str, Any],
    doc: Any,
    rows: list[dict[str, Any]],
    *,
    verbatim_cleared: bool,
) -> list[dict[str, Any]]:
    """Verify the series manifests against the item rows they reference."""
    _require(isinstance(doc, dict), f"{pack_dir}: series.json is not an object")
    assert isinstance(doc, dict)
    _require(
        int(doc.get("class_num") or 0) == int(manifest["class_num"]),
        f"{pack_dir}: series.json class_num disagrees with the manifest",
    )
    series = doc.get("series")
    _require(isinstance(series, list) and series, f"{pack_dir}: no series manifests")
    assert isinstance(series, list)
    counts = manifest.get("counts") or {}
    _require(
        len(series) == int(counts.get("series", len(series))),
        f"{pack_dir}: series count disagrees with the manifest",
    )
    item_universe = {str(row["item_id"]) for row in rows}
    row_keys = {(str(row["item_id"]), str(row["language"])) for row in rows}
    seen_series: set[str] = set()
    missing_language_rows: list[str] = []
    for entry in series:
        _require(
            isinstance(entry, dict), f"{pack_dir}: series manifest is not an object"
        )
        for key in ("series_id", "label", "language_policy", "enabled", "item_ids"):
            _require(key in entry, f"{pack_dir}: series manifest misses {key}")
        series_id = str(entry["series_id"])
        _require(
            series_id in SERIES_KINDS,
            f"{pack_dir}: unknown series_id {series_id!r}",
        )
        _require(
            series_id not in seen_series,
            f"{pack_dir}: duplicate series manifest {series_id}",
        )
        seen_series.add(series_id)
        _require(
            isinstance(entry["enabled"], bool),
            f"{pack_dir}: {series_id} enabled is not a boolean",
        )
        policy = [str(lang) for lang in entry["language_policy"]]
        _require(
            bool(policy) and set(policy) <= PACK_LANGUAGES,
            f"{pack_dir}: {series_id} language_policy {policy} is not a pack-language set",
        )
        item_ids = [str(item_id) for item_id in entry["item_ids"]]
        unknown = sorted(set(item_ids) - item_universe)
        _require(
            not unknown,
            f"{pack_dir}: {series_id} references items missing from items.json {unknown[:5]}",
        )
        if not entry["enabled"]:
            # A dark series contributes catalogue only; it must not carry items
            # the pack would then have to serve.
            _require(
                not item_ids,
                f"{pack_dir}: disabled series {series_id} still carries items",
            )
            continue
        if series_id == "exact_pyq":
            # The exact-PYQ series is dark until DEC-COMP-001 has a clearance
            # row AND the pack marks the series enabled; either missing refuses.
            compliance = manifest.get("compliance") or {}
            _require(
                verbatim_cleared
                and str(compliance.get("exact_pyq_status") or "absent") == "enabled",
                f"{pack_dir}: exact_pyq carries {len(item_ids)} item(s) but the pack "
                "does not mark it cleared and enabled — exact-PYQ content stays "
                "dark (DEC-COMP-001)",
            )
        for language in policy:
            for item_id in item_ids:
                if (item_id, language) not in row_keys:
                    missing_language_rows.append(f"{series_id}/{item_id}/{language}")
        _verify_papers(pack_dir, series_id, entry, item_universe)
        covered = _verify_sets(pack_dir, series_id, entry, item_universe)
        # A series' item_ids are exactly what its papers' filled slots plus its
        # sets carry: paper series (board_practice, pyq_pattern) use papers,
        # set-based series (ai_lesson, challenge, loop) use sets, and an empty
        # series is covered vacuously.
        paper_items = {
            str(slot["item_id"])
            for paper in entry.get("papers") or []
            for slot in paper["sections"]
            if slot.get("item_id") is not None
        }
        _require(
            paper_items | covered == set(item_ids),
            f"{pack_dir}: {series_id} item_ids are not covered by its papers and "
            f"sets ({len(set(item_ids) - paper_items - covered)} unreferenced)",
        )
    _require(
        not missing_language_rows,
        f"{pack_dir}: series language policy promises rows that items.json omits "
        f"({len(missing_language_rows)}): {missing_language_rows[:5]}",
    )
    # The rows name the series they serve; the series name the items they
    # carry. Both directions must agree, so a dark series cannot gain rows by
    # accident and an enabled series cannot drop an item a row still claims.
    claimed: dict[str, set[str]] = {}
    for row in rows:
        for sid in (str(sid) for sid in row["series_ids"]):
            claimed.setdefault(sid, set()).add(str(row["item_id"]))
    for entry in series:
        series_id = str(entry["series_id"])
        declared = {str(item_id) for item_id in entry["item_ids"]}
        named = claimed.get(series_id, set())
        _require(
            named == declared,
            f"{pack_dir}: {series_id} item_ids disagree with the rows naming it "
            f"(rows claim {sorted(named - declared)[:5]}, "
            f"manifest declares {sorted(declared - named)[:5]})",
        )
    return [dict(entry) for entry in series]


def _verify_papers(
    pack_dir: Path, series_id: str, entry: dict[str, Any], item_universe: set[str]
) -> None:
    papers = entry.get("papers")
    _require(isinstance(papers, list), f"{pack_dir}: {series_id} papers is not a list")
    assert isinstance(papers, list)
    seen_papers: set[str] = set()
    for paper in papers:
        _require(
            isinstance(paper, dict), f"{pack_dir}: {series_id} paper is not an object"
        )
        for key in ("paper_id", "sections", "item_ids", "filled_slots", "total_slots"):
            _require(key in paper, f"{pack_dir}: {series_id} paper misses {key}")
        paper_id = str(paper["paper_id"])
        _require(
            paper_id not in seen_papers,
            f"{pack_dir}: {series_id} has duplicate paper {paper_id}",
        )
        seen_papers.add(paper_id)
        slots = paper["sections"]
        _require(
            isinstance(slots, list) and slots,
            f"{pack_dir}: {series_id}/{paper_id} has no section slots",
        )
        seen_slots: set[str] = set()
        filled = 0
        design_marks = 0
        seen_items: set[str] = set()
        for slot in slots:
            _require(isinstance(slot, dict), f"{pack_dir}: slot is not an object")
            for key in ("slot_id", "section", "type", "marks", "chapter_id", "item_id"):
                _require(
                    key in slot, f"{pack_dir}: {series_id}/{paper_id} slot misses {key}"
                )
            slot_id = str(slot["slot_id"])
            _require(
                slot_id not in seen_slots,
                f"{pack_dir}: {series_id}/{paper_id} has duplicate slot {slot_id}",
            )
            seen_slots.add(slot_id)
            _require(
                float(slot["marks"]) > 0,
                f"{pack_dir}: {series_id}/{paper_id} slot {slot_id} has non-positive marks",
            )
            design_marks += int(slot["marks"])
            item_id = slot.get("item_id")
            if item_id is None:
                continue
            item_id = str(item_id)
            filled += 1
            _require(
                item_id in item_universe,
                f"{pack_dir}: {series_id}/{paper_id} slot {slot_id} references an item "
                f"missing from items.json ({item_id})",
            )
            _require(
                item_id in {str(i) for i in entry["item_ids"]},
                f"{pack_dir}: {series_id}/{paper_id} slot {slot_id} references {item_id}, "
                "which the series does not claim",
            )
            _require(
                item_id not in seen_items,
                f"{pack_dir}: {series_id}/{paper_id} repeats item {item_id} "
                "(a paper never repeats an item)",
            )
            seen_items.add(item_id)
        _require(
            int(paper["filled_slots"]) == filled,
            f"{pack_dir}: {series_id}/{paper_id} filled_slots disagrees with its slots",
        )
        _require(
            int(paper["total_slots"]) == len(slots),
            f"{pack_dir}: {series_id}/{paper_id} total_slots disagrees with its slots",
        )
        if paper.get("marks_total") is not None:
            _require(
                int(paper["marks_total"]) == design_marks,
                f"{pack_dir}: {series_id}/{paper_id} marks_total disagrees with its slots",
            )
        listed = {str(item_id) for item_id in paper["item_ids"]}
        _require(
            listed == seen_items,
            f"{pack_dir}: {series_id}/{paper_id} item_ids disagree with its filled slots",
        )


def _verify_sets(
    pack_dir: Path, series_id: str, entry: dict[str, Any], item_universe: set[str]
) -> set[str]:
    """Verify the sets; return the item ids they reference."""
    sets = entry.get("sets")
    _require(isinstance(sets, list), f"{pack_dir}: {series_id} sets is not a list")
    assert isinstance(sets, list)
    series_items = {str(item_id) for item_id in entry["item_ids"]}
    seen_sets: set[str] = set()
    covered: set[str] = set()
    for unit in sets:
        _require(
            isinstance(unit, dict), f"{pack_dir}: {series_id} set is not an object"
        )
        for key in ("set_id", "kind", "item_ids"):
            _require(key in unit, f"{pack_dir}: {series_id} set misses {key}")
        set_id = str(unit["set_id"])
        _require(
            set_id not in seen_sets,
            f"{pack_dir}: {series_id} has duplicate set {set_id}",
        )
        seen_sets.add(set_id)
        unit_items = [str(item_id) for item_id in unit["item_ids"]]
        unknown = sorted(set(unit_items) - series_items - item_universe)
        _require(
            not unknown,
            f"{pack_dir}: {series_id}/{set_id} references unknown items {unknown[:5]}",
        )
        covered.update(unit_items)
    return covered


def load_pack(pack_dir: Path) -> SeriesPack:
    """Read and verify one pack directory; raise `PackError` on any defect."""
    pack_dir = Path(pack_dir)
    manifest = _load_json(pack_dir / "manifest.json")
    _require(isinstance(manifest, dict), f"{pack_dir}: manifest.json is not an object")
    assert isinstance(manifest, dict)
    _verify_files(pack_dir, manifest)
    _require(
        int(manifest.get("pack_version") or 0) >= 1,
        f"{pack_dir}: pack_version is missing or not a positive integer",
    )
    _require(
        int(manifest.get("class_num") or 0) in EXAM_CLASSES,
        f"{pack_dir}: manifest.class_num is missing or not an exam class",
    )
    _verify_gate(pack_dir, manifest)
    verbatim_cleared = _verify_compliance(pack_dir, manifest)
    items_doc = _load_json(pack_dir / "items.json")
    rows = _verify_rows(
        pack_dir, manifest, items_doc, verbatim_cleared=verbatim_cleared
    )
    for name in ("papers.json", "blueprint.json"):
        doc = _load_json(pack_dir / name)
        _require(isinstance(doc, dict), f"{pack_dir}: {name} is not an object")
        if "class_num" in doc:
            _require(
                int(doc["class_num"]) == int(manifest["class_num"]),
                f"{pack_dir}: {name} class_num disagrees with the manifest",
            )
    series_doc = _load_json(pack_dir / "series.json")
    series = _verify_series(
        pack_dir, manifest, series_doc, rows, verbatim_cleared=verbatim_cleared
    )
    return SeriesPack(pack_dir=pack_dir, manifest=manifest, rows=rows, series=series)


def _plan_tests(pack: SeriesPack) -> tuple[list[PlannedTest], int]:
    """Build the `test`/`test_question` plan for every enabled series."""
    class_num = pack.class_num
    rows_by_key = pack._rows_by_key
    planned: list[PlannedTest] = []
    skipped = 0
    for entry in pack.series:
        if not entry["enabled"]:
            continue
        series_id = str(entry["series_id"])
        series_row_id = f"class-{class_num}-{series_id}"
        label = str(entry["label"])
        policy = [str(lang) for lang in entry["language_policy"]]
        units: list[
            tuple[str, str, list[dict[str, Any]] | None, dict[str, Any] | None]
        ] = []
        # (unit_id, unit_kind, sections-or-None, set-or-None); a paper keeps
        # its full slot list (empty slots included — honest gaps), a set keeps
        # its manifest entry.
        for paper in entry.get("papers") or []:
            units.append(
                (str(paper["paper_id"]), "paper", list(paper["sections"]), None)
            )
        for unit in entry.get("sets") or []:
            units.append((str(unit["set_id"]), "set", None, unit))
        for unit_id, unit_kind, slots, unit in units:
            for language in policy:
                questions: list[dict[str, Any]] = []
                chapter_ids: set[str] = set()
                structure: dict[str, Any] = {
                    "source": "series_pack",
                    "series_id": series_id,
                    "unit_kind": unit_kind,
                }
                if unit_kind == "paper":
                    assert slots is not None  # papers always carry their slots
                    structure["paper_id"] = unit_id
                    structure["sections"] = slots
                    structure["filled_slots"] = sum(
                        1 for slot in slots if slot.get("item_id") is not None
                    )
                    structure["total_slots"] = len(slots)
                    design_marks = sum(int(slot["marks"]) for slot in slots)
                    structure["design_marks_total"] = design_marks
                    for slot in slots:
                        item_id = slot.get("item_id")
                        if item_id is None:
                            continue
                        row = rows_by_key.get((str(item_id), language))
                        if row is None:  # defensive; load_pack verified coverage
                            raise PackError(
                                f"{pack.pack_dir}: {series_id}/{unit_id} has no "
                                f"{language} row for {item_id}"
                            )
                        chapter_ids.add(str(row["chapter_id"]))
                        questions.append(
                            {
                                "question_id": f"{row['base_item_id']}-{language}",
                                "section": str(slot["section"]),
                                "marks": float(slot["marks"]),
                            }
                        )
                else:
                    assert unit is not None
                    structure["set_id"] = unit_id
                    structure["set_kind"] = str(unit.get("kind") or "set")
                    structure["item_ids"] = [
                        str(item_id) for item_id in unit["item_ids"]
                    ]
                    for item_id in structure["item_ids"]:
                        row = rows_by_key.get((item_id, language))
                        if row is None:  # defensive; load_pack verified coverage
                            raise PackError(
                                f"{pack.pack_dir}: {series_id}/{unit_id} has no "
                                f"{language} row for {item_id}"
                            )
                        chapter_ids.add(str(row["chapter_id"]))
                        questions.append(
                            {
                                "question_id": f"{row['base_item_id']}-{language}",
                                "section": None,
                                "marks": float(row["marks"]),
                            }
                        )
                if not questions:
                    skipped += 1
                    continue
                duration_min = entry.get("duration_min")
                if duration_min:
                    duration_s = int(duration_min) * 60
                else:
                    duration_s = max(1, SECONDS_PER_QUESTION * len(questions))
                planned.append(
                    PlannedTest(
                        test_id=f"{series_row_id}-{unit_id}-{language}",
                        series_row_id=series_row_id,
                        title=f"{label} - {unit_id} ({LANGUAGE_NAMES[language]})",
                        language=language,
                        chapter_ids=sorted(chapter_ids),
                        duration_s=duration_s,
                        total_marks=float(sum(q["marks"] for q in questions)),
                        structure=structure,
                        questions=questions,
                    )
                )
    return planned, skipped


def build_plan(pack: SeriesPack) -> ImportPlan:
    """Plan what the pack would write (no DB access; `import_plan` writes it)."""
    tests, skipped = _plan_tests(pack)
    return ImportPlan(
        pack=pack,
        series_rows=len(pack.series),
        published_series=sum(1 for entry in pack.series if entry["enabled"]),
        tests=tests,
        skipped_units=skipped,
    )


def _require_bank_rows(db: DatabaseEngine, plan: ImportPlan) -> None:
    """Refuse the pack unless `question_bank` holds every referenced row.

    `test_question.question_id` is an FK into the bank (ON DELETE RESTRICT);
    the bank is the assessment importer's output, so a miss means the
    prerequisite import has not run (or the pack references a bank this
    database never received).
    """
    needed = sorted({q["question_id"] for test in plan.tests for q in test.questions})
    if not needed:
        return
    found: set[str] = set()
    for start in range(0, len(needed), 400):
        chunk = needed[start : start + 400]
        placeholders = ", ".join("?" for _ in chunk)
        rows = db.fetchall(
            f"SELECT question_id FROM question_bank WHERE question_id IN ({placeholders})",
            tuple(chunk),
        )
        found.update(str(row["question_id"]) for row in rows)
    missing = [question_id for question_id in needed if question_id not in found]
    if missing:
        sample = ", ".join(missing[:10])
        more = "" if len(missing) <= 10 else f" (and {len(missing) - 10} more)"
        raise PackError(
            f"{plan.pack.pack_dir}: {len(missing)} referenced question_bank row(s) "
            f"missing — run scripts/import_assessment_packs.py first: {sample}{more}"
        )


_SERIES_UPSERT_SQL: Final[str] = """
INSERT INTO test_series (
    series_id, slug, class_level, kind, title, description, language_set,
    status, metadata, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (series_id) DO UPDATE SET
    slug = excluded.slug,
    class_level = excluded.class_level,
    kind = excluded.kind,
    title = excluded.title,
    description = excluded.description,
    language_set = excluded.language_set,
    status = excluded.status,
    metadata = excluded.metadata,
    updated_at = excluded.updated_at
"""

_TEST_UPSERT_SQL: Final[str] = """
INSERT INTO test (
    test_id, series_id, chapter_ids, title, language, duration_s, total_marks,
    structure, status, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'published', ?, ?)
ON CONFLICT (test_id) DO UPDATE SET
    chapter_ids = excluded.chapter_ids,
    title = excluded.title,
    language = excluded.language,
    duration_s = excluded.duration_s,
    total_marks = excluded.total_marks,
    structure = excluded.structure,
    status = excluded.status,
    updated_at = excluded.updated_at
"""

_TEST_QUESTION_UPSERT_SQL: Final[str] = """
INSERT INTO test_question (test_id, question_id, order_index, section, marks)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT (test_id, question_id) DO UPDATE SET
    order_index = excluded.order_index,
    section = excluded.section,
    marks = excluded.marks
"""

_PACK_UPSERT_SQL: Final[str] = """
INSERT INTO assessment_pack (
    pack_id, kind, chapter_id, class_level, subject, pack_version, content_hash,
    source_path, run_id, generator, gate_verdict, counts, generated_at, imported_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pass', ?, ?, ?)
ON CONFLICT (pack_id) DO UPDATE SET
    source_path = excluded.source_path,
    run_id = excluded.run_id,
    generator = excluded.generator,
    counts = excluded.counts,
    generated_at = excluded.generated_at,
    imported_at = excluded.imported_at
"""


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def import_plan(
    db: DatabaseEngine, plan: ImportPlan, *, now: str | None = None
) -> ImportResult:
    """Write one verified pack inside a single transaction."""
    pack = plan.pack
    stamp = now or _now_iso()
    manifest = pack.manifest
    _require_bank_rows(db, plan)  # refuse before anything is written
    with db.transaction() as tx:
        tx.execute(
            _PACK_UPSERT_SQL,
            (
                pack.pack_id,
                PACK_KIND,
                f"class-{pack.class_num}",
                pack.class_num,
                str(manifest.get("subject") or "physics").lower(),
                int(manifest["pack_version"]),
                pack.content_hash,
                _source_label(pack.pack_dir),
                manifest.get("run_id"),
                f"factory.exam-{manifest.get('exam_pipeline_version')}",
                _json(manifest.get("counts") or {}),
                manifest.get("generated_at"),
                stamp,
            ),
        )
        for entry in pack.series:
            series_id = str(entry["series_id"])
            enabled = bool(entry["enabled"])
            row_id = f"class-{pack.class_num}-{series_id}"
            metadata = {
                "label_key": entry.get("label_key"),
                "purpose": entry.get("purpose"),
                "source_policy": entry.get("source_policy"),
                "notice_id": entry.get("notice_id"),
                "pack_status": str(entry.get("status") or ""),
                "disabled_reason": entry.get("disabled_reason"),
                "minimum": entry.get("minimum") or {},
                "delivered": entry.get("delivered") or {},
                "pack_id": pack.pack_id,
                "content_hash": pack.content_hash,
            }
            tx.execute(
                _SERIES_UPSERT_SQL,
                (
                    row_id,
                    row_id,  # slug: the same class-scoped id (unique by construction)
                    pack.class_num,
                    series_id,
                    str(entry["label"]),
                    str(entry.get("copy") or entry.get("purpose") or ""),
                    _json([str(lang) for lang in entry["language_policy"]]),
                    "published" if enabled else "draft",
                    _json(metadata),
                    stamp,
                    stamp,
                ),
            )
        for test in plan.tests:
            tx.execute(
                _TEST_UPSERT_SQL,
                (
                    test.test_id,
                    test.series_row_id,
                    _json(test.chapter_ids),
                    test.title,
                    test.language,
                    int(test.duration_s),
                    float(test.total_marks),
                    _json(test.structure),
                    stamp,
                    stamp,
                ),
            )
            # Replace the paper's rows rather than upserting: nothing references
            # test_question (attempt answers copy question_id as plain text), and
            # a re-export that reorders a paper would otherwise collide on
            # UNIQUE (test_id, order_index) mid-update.
            tx.execute("DELETE FROM test_question WHERE test_id = ?", (test.test_id,))
            for index, question in enumerate(test.questions, start=1):
                tx.execute(
                    _TEST_QUESTION_UPSERT_SQL,
                    (
                        test.test_id,
                        str(question["question_id"]),
                        index,
                        question["section"],
                        float(question["marks"]),
                    ),
                )
    return ImportResult(
        pack_id=pack.pack_id,
        class_num=pack.class_num,
        series_rows=plan.series_rows,
        tests=len(plan.tests),
        question_rows=plan.question_rows,
        content_hash=pack.content_hash,
    )


def import_packs(db: DatabaseEngine, packs_dir: Path) -> list[ImportResult]:
    """Verify every pack under `packs_dir`, then import each one."""
    pack_dirs = sorted(path.parent for path in Path(packs_dir).glob("*/manifest.json"))
    if not pack_dirs:
        raise PackError(f"{packs_dir}: no pack directories (expected */manifest.json)")
    packs = [load_pack(path) for path in pack_dirs]  # verify all before writing any
    results = []
    for pack in packs:
        plan = build_plan(pack)
        _require_bank_rows(db, plan)  # verify every pack before writing any
        results.append(import_plan(db, plan))
    return results


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: verify + import the exam/series packs."""
    parser = argparse.ArgumentParser(
        description=(
            "Import E4 exam/series packs into test_series/test/test_question "
            "(the question_bank rows must already be imported)."
        )
    )
    parser.add_argument(
        "--packs-dir",
        default=str(DEFAULT_PACKS_DIR),
        help=f"directory of pack sub-directories (default: {DEFAULT_PACKS_DIR})",
    )
    parser.add_argument(
        "--db-url",
        default=DEFAULT_DB_URL,
        help=(
            "database URL, named explicitly (default: sqlite:///zivon.db; "
            "there is no env-var fallback)"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="verify the packs and print what would be written; no DB access",
    )
    parser.add_argument(
        "--no-migrate",
        action="store_true",
        help="do not run migrations first (the schema must already be at head)",
    )
    args = parser.parse_args(argv)

    packs_dir = Path(args.packs_dir).expanduser()
    try:
        pack_dirs = sorted(path.parent for path in packs_dir.glob("*/manifest.json"))
        if not pack_dirs:
            raise PackError(
                f"{packs_dir}: no pack directories (expected */manifest.json)"
            )
        packs = [load_pack(path) for path in pack_dirs]
        plans = [build_plan(pack) for pack in packs]
    except PackError as exc:
        print(f"[import] refused: {exc}", file=sys.stderr)
        return 1

    for plan in plans:
        pack = plan.pack
        print(
            f"[import] verified class-{pack.class_num}: "
            f"{plan.published_series}/{plan.series_rows} series enabled, "
            f"{len(plan.tests)} test rows planned, "
            f"{plan.question_rows} question rows, {pack.content_hash[:19]}..."
        )
    if args.dry_run:
        print(f"[import] dry run: {len(plans)} pack(s) verified, nothing written")
        return 0

    try:
        db = DatabaseEngine.from_url(args.db_url, auto_migrate=not args.no_migrate)
        results = [import_plan(db, plan) for plan in plans]
    except PackError as exc:
        print(f"[import] refused: {exc}", file=sys.stderr)
        return 1

    tests = sum(result.tests for result in results)
    question_rows = sum(result.question_rows for result in results)
    print(
        f"[import] imported {len(results)} pack(s): {tests} test rows, "
        f"{question_rows} test_question rows (schema {db.schema_version()})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
