#!/usr/bin/env python3
"""Import the tracked assessment packs into the hot database (W4 foundation).

The assessment pipeline (`python -m factory.assessment`, stages A1-A6) writes a
versioned, self-describing pack; this script is the **only** write path from a
pack into `db` (practice/speaking/test foundation, revision
`0004_practice_speaking_tests`). It imports:

- `question_bank`       one row per (item, language)  <- `questions.json`
- `speaking_prompt`     one row per (prompt, language) <- `speaking.json`
- `topic_time_prior`    chapter + concept priors       <- `time-priors.json`
- `assessment_pack`     provenance: chapter, class, version, content hash, gate

The pack is verified before a single row is written: every data file's SHA-256
and byte size must match `manifest.json`, the manifest's `content_hash` is
recomputed, the gate verdict must be `pass`, and the chapter identity must
agree across the manifest, the pack documents, and the directory name. A pack
that fails any check is refused whole, so the DB never holds half a pack.

Re-running an unchanged pack is a no-op in row counts (upserts keyed by the
stable ids; `assessment_pack` is keyed by chapter + content hash). Question and
speaking rows are updated in place, never deleted: learner evidence keeps its
`question_id`, and a withdrawn item is retired by status, not by deletion.
Topic priors are replaced per chapter because nothing references them.

Usage (from the repo root):

    python3 scripts/import_assessment_packs.py --dry-run
    python3 scripts/import_assessment_packs.py --db-url sqlite:///zivon.db
    ZIVON_DB_URL=postgresql://... python3 scripts/import_assessment_packs.py

Key-free and offline; stdlib for SQLite, `psycopg` only when a PostgreSQL URL
is used. See `docs/backend/runbooks/assessment-import.md`.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from db.engine import DatabaseEngine  # the repo root is on sys.path above

DEFAULT_PACKS_DIR: Final[Path] = REPO_ROOT / "sources" / "assessment" / "packs"
DEFAULT_DB_URL: Final[str] = "sqlite:///zivon.db"

PACK_DATA_FILES: Final[tuple[str, ...]] = (
    "syllabus.json",
    "concepts.json",
    "questions.json",
    "speaking.json",
    "time-priors.json",
)
PACK_KIND: Final[str] = "assessment"
PACK_LANGUAGES: Final[frozenset[str]] = frozenset({"en", "hi", "hi-Latn"})
QUESTION_TYPES: Final[frozenset[str]] = frozenset(
    {"mcq", "numeric", "assertion_reason"}
)
DIFFICULTIES: Final[frozenset[str]] = frozenset({"easy", "medium", "hard"})
SOURCE_TYPES: Final[frozenset[str]] = frozenset(
    {"generated", "past_paper", "sample_paper", "curated_pyq"}
)
REVIEW_STATUSES: Final[frozenset[str]] = frozenset(
    {"draft", "reviewed", "published", "retired"}
)
REVIEW_MODES: Final[frozenset[str]] = frozenset({"deterministic", "judged", "human"})
PRIOR_SCOPES: Final[frozenset[str]] = frozenset({"chapter", "concept"})

QUESTION_REQUIRED_KEYS: Final[tuple[str, ...]] = (
    "question_id",
    "base_item_id",
    "class_level",
    "chapter_id",
    "concept_id",
    "type",
    "difficulty",
    "marks",
    "language",
    "source_type",
    "prompt",
    "answer",
    "explanation",
    "expected_time_ms",
)


class PackError(ValueError):
    """The pack is malformed, tampered with, or failed its own gate."""


@dataclass(frozen=True)
class PackData:
    """A verified pack, ready to import."""

    pack_dir: Path
    manifest: dict[str, Any]
    questions: list[dict[str, Any]]
    speaking: list[dict[str, Any]]
    priors: list[dict[str, Any]]

    @property
    def chapter_id(self) -> str:
        return str(self.manifest["chapter_id"])

    @property
    def class_level(self) -> int:
        return int(self.manifest["class_level"])

    @property
    def content_hash(self) -> str:
        return str(self.manifest["content_hash"])

    @property
    def pack_id(self) -> str:
        """Stable id: chapter + kind + content hash prefix (idempotent import)."""
        return pack_id_for(PACK_KIND, self.chapter_id, self.content_hash)


@dataclass(frozen=True)
class ImportResult:
    """What one pack wrote (row counts, not insert-vs-update)."""

    pack_id: str
    chapter_id: str
    class_level: int
    questions: int
    speaking_rows: int
    topic_priors: int
    content_hash: str


def pack_id_for(kind: str, chapter_id: str, content_hash: str) -> str:
    """Deterministic pack id: re-importing the same content keeps the same row."""
    digest = content_hash.removeprefix("sha256:")
    return f"{kind}-{chapter_id}-{digest[:12]}"


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _content_hash(files: Mapping[str, Mapping[str, Any]]) -> str:
    """Recompute the pack hash the way A6 built it (`factory/assessment/pack.py`)."""
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


def _verify_files(pack_dir: Path, manifest: Mapping[str, Any]) -> None:
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


def _verify_identity(pack_dir: Path, manifest: Mapping[str, Any]) -> None:
    _require(
        str(manifest.get("chapter_id") or "") == pack_dir.name,
        f"{pack_dir}: manifest chapter_id does not match the directory name",
    )
    gate = manifest.get("gate")
    _require(isinstance(gate, dict), f"{pack_dir}: manifest.gate missing")
    assert isinstance(gate, dict)
    _require(
        gate.get("verdict") == "pass" and int(gate.get("error_count", 1)) == 0,
        f"{pack_dir}: pack gate verdict is {gate.get('verdict')!r}, not 'pass'",
    )
    _require(
        int(manifest.get("pack_version") or 0) >= 1,
        f"{pack_dir}: pack_version is missing or not a positive integer",
    )
    _require(
        isinstance(manifest.get("class_level"), int),
        f"{pack_dir}: manifest.class_level is missing",
    )


def _verify_questions(
    pack_dir: Path, manifest: Mapping[str, Any], doc: Any
) -> list[dict[str, Any]]:
    _require(isinstance(doc, dict), f"{pack_dir}: questions.json is not an object")
    assert isinstance(doc, dict)
    _require(
        doc.get("chapter_id") == manifest["chapter_id"],
        f"{pack_dir}: questions.json chapter_id does not match the manifest",
    )
    rows = doc.get("questions")
    _require(isinstance(rows, list) and rows, f"{pack_dir}: no question rows")
    assert isinstance(rows, list)
    counts = manifest.get("counts") or {}
    _require(
        len(rows) == int(counts.get("question_rows", len(rows))),
        f"{pack_dir}: question_rows count disagrees with the manifest",
    )
    seen_ids: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    for row in rows:
        _require(isinstance(row, dict), f"{pack_dir}: question row is not an object")
        missing = [key for key in QUESTION_REQUIRED_KEYS if key not in row]
        _require(not missing, f"{pack_dir}: question row misses {missing}")
        question_id = str(row["question_id"])
        _require(
            question_id not in seen_ids,
            f"{pack_dir}: duplicate question_id {question_id}",
        )
        seen_ids.add(question_id)
        pair = (str(row["base_item_id"]), str(row["language"]))
        _require(
            pair not in seen_pairs, f"{pack_dir}: duplicate (item, language) {pair}"
        )
        seen_pairs.add(pair)
        _require(
            row["type"] in QUESTION_TYPES,
            f"{pack_dir}: {question_id} has type {row['type']!r}",
        )
        _require(
            row["difficulty"] in DIFFICULTIES,
            f"{pack_dir}: {question_id} has difficulty {row['difficulty']!r}",
        )
        _require(
            row["language"] in PACK_LANGUAGES,
            f"{pack_dir}: {question_id} has language {row['language']!r}",
        )
        _require(
            row["source_type"] in SOURCE_TYPES,
            f"{pack_dir}: {question_id} has source_type {row['source_type']!r}",
        )
        _require(
            float(row["marks"]) > 0, f"{pack_dir}: {question_id} has non-positive marks"
        )
        _require(
            int(row["expected_time_ms"]) > 0,
            f"{pack_dir}: {question_id} has no expected_time_ms",
        )
        _require(
            isinstance(row["answer"], dict),
            f"{pack_dir}: {question_id} answer is not an object",
        )
        _require(
            int(row["class_level"]) == int(manifest["class_level"]),
            f"{pack_dir}: {question_id} class_level disagrees with the manifest",
        )
        _require(
            row["chapter_id"] == manifest["chapter_id"],
            f"{pack_dir}: {question_id} chapter_id disagrees with the manifest",
        )
        status = str(row.get("status") or "reviewed")
        _require(
            status in REVIEW_STATUSES,
            f"{pack_dir}: {question_id} has status {status!r}",
        )
        mode = str(row.get("review_mode") or "deterministic")
        _require(
            mode in REVIEW_MODES, f"{pack_dir}: {question_id} has review_mode {mode!r}"
        )
    return [dict(row) for row in rows]


def _verify_speaking(
    pack_dir: Path, manifest: Mapping[str, Any], doc: Any
) -> list[dict[str, Any]]:
    _require(isinstance(doc, dict), f"{pack_dir}: speaking.json is not an object")
    assert isinstance(doc, dict)
    _require(
        doc.get("chapter_id") == manifest["chapter_id"],
        f"{pack_dir}: speaking.json chapter_id does not match the manifest",
    )
    rows = doc.get("prompts")
    _require(isinstance(rows, list) and rows, f"{pack_dir}: no speaking prompts")
    assert isinstance(rows, list)
    counts = manifest.get("counts") or {}
    prompt_ids = {str(row["prompt_id"]) for row in rows}
    _require(
        len(prompt_ids) == int(counts.get("speaking_prompts", len(prompt_ids))),
        f"{pack_dir}: speaking prompt count disagrees with the manifest",
    )
    seen: set[tuple[str, str]] = set()
    for row in rows:
        _require(isinstance(row, dict), f"{pack_dir}: speaking row is not an object")
        for key in (
            "prompt_id",
            "language",
            "chapter_id",
            "prompt",
            "key_ideas",
            "model_answer",
        ):
            _require(key in row, f"{pack_dir}: speaking row misses {key}")
        pair = (str(row["prompt_id"]), str(row["language"]))
        _require(pair not in seen, f"{pack_dir}: duplicate speaking row {pair}")
        seen.add(pair)
        _require(
            row["language"] in PACK_LANGUAGES,
            f"{pack_dir}: speaking language {row['language']!r}",
        )
        _require(
            row["chapter_id"] == manifest["chapter_id"],
            f"{pack_dir}: speaking row chapter_id mismatch",
        )
        _require(
            bool(str(row["prompt"]).strip()),
            f"{pack_dir}: speaking prompt text is empty",
        )
        _require(
            isinstance(row["key_ideas"], list),
            f"{pack_dir}: speaking key_ideas is not a list",
        )
        _require(
            bool(str(row["model_answer"]).strip()),
            f"{pack_dir}: speaking model_answer is empty",
        )
    return [dict(row) for row in rows]


def _verify_priors(
    pack_dir: Path, manifest: Mapping[str, Any], doc: Any
) -> list[dict[str, Any]]:
    _require(isinstance(doc, dict), f"{pack_dir}: time-priors.json is not an object")
    assert isinstance(doc, dict)
    _require(
        bool(str(doc.get("formula_version") or "")),
        f"{pack_dir}: time priors have no formula_version",
    )
    rows = doc.get("topics")
    _require(isinstance(rows, list) and rows, f"{pack_dir}: no topic time priors")
    assert isinstance(rows, list)
    scopes = {"chapter"}
    for row in rows:
        _require(isinstance(row, dict), f"{pack_dir}: time-prior row is not an object")
        for key in ("chapter_id", "scope", "scope_id", "expected_time_ms"):
            _require(key in row, f"{pack_dir}: time-prior row misses {key}")
        _require(
            row["scope"] in PRIOR_SCOPES,
            f"{pack_dir}: time-prior scope {row['scope']!r}",
        )
        _require(
            int(row["expected_time_ms"]) > 0,
            f"{pack_dir}: time-prior has no expected_time_ms",
        )
        _require(
            row["chapter_id"] == manifest["chapter_id"],
            f"{pack_dir}: time-prior chapter_id mismatch",
        )
        scopes.add(str(row["scope"]))
    _require("chapter" in scopes, f"{pack_dir}: no chapter-scope time prior")
    return [dict(row) for row in rows]


def load_pack(pack_dir: Path) -> PackData:
    """Read and verify one pack directory; raise `PackError` on any defect."""
    pack_dir = Path(pack_dir)
    manifest = _load_json(pack_dir / "manifest.json")
    _require(isinstance(manifest, dict), f"{pack_dir}: manifest.json is not an object")
    assert isinstance(manifest, dict)
    _verify_files(pack_dir, manifest)
    _verify_identity(pack_dir, manifest)
    questions = _verify_questions(
        pack_dir, manifest, _load_json(pack_dir / "questions.json")
    )
    speaking = _verify_speaking(
        pack_dir, manifest, _load_json(pack_dir / "speaking.json")
    )
    priors_doc = _load_json(pack_dir / "time-priors.json")
    priors = _verify_priors(pack_dir, manifest, priors_doc)
    assert isinstance(priors_doc, dict)
    for row in priors:
        row.setdefault("formula_version", priors_doc.get("formula_version"))
    return PackData(
        pack_dir=pack_dir,
        manifest=manifest,
        questions=questions,
        speaking=speaking,
        priors=priors,
    )


_QUESTION_UPSERT_SQL: Final[str] = """
INSERT INTO question_bank (
    question_id, base_item_id, class_level, chapter_id, concept_id, type,
    difficulty, marks, language, source_type, source_ref, prompt, options,
    answer, explanation, misconception, expected_time_ms, status, review_mode,
    version, generator, pack_id, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (question_id) DO UPDATE SET
    base_item_id = excluded.base_item_id,
    class_level = excluded.class_level,
    chapter_id = excluded.chapter_id,
    concept_id = excluded.concept_id,
    type = excluded.type,
    difficulty = excluded.difficulty,
    marks = excluded.marks,
    language = excluded.language,
    source_type = excluded.source_type,
    source_ref = excluded.source_ref,
    prompt = excluded.prompt,
    options = excluded.options,
    answer = excluded.answer,
    explanation = excluded.explanation,
    misconception = excluded.misconception,
    expected_time_ms = excluded.expected_time_ms,
    status = excluded.status,
    review_mode = excluded.review_mode,
    version = excluded.version,
    generator = excluded.generator,
    pack_id = excluded.pack_id,
    updated_at = excluded.updated_at
"""

_SPEAKING_UPSERT_SQL: Final[str] = """
INSERT INTO speaking_prompt (
    prompt_id, language, class_level, chapter_id, concept_ids, prompt,
    key_ideas, model_answer, model_answer_source, rubric, status, version,
    pack_id, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (prompt_id, language) DO UPDATE SET
    class_level = excluded.class_level,
    chapter_id = excluded.chapter_id,
    concept_ids = excluded.concept_ids,
    prompt = excluded.prompt,
    key_ideas = excluded.key_ideas,
    model_answer = excluded.model_answer,
    model_answer_source = excluded.model_answer_source,
    rubric = excluded.rubric,
    status = excluded.status,
    version = excluded.version,
    pack_id = excluded.pack_id,
    updated_at = excluded.updated_at
"""

_PRIOR_INSERT_SQL: Final[str] = """
INSERT INTO topic_time_prior (
    chapter_id, scope, scope_id, class_level, expected_time_ms,
    question_count, formula_version, pack_id, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def import_pack(
    db: DatabaseEngine, pack: PackData, *, now: str | None = None
) -> ImportResult:
    """Write one verified pack inside a single transaction."""
    stamp = now or _now_iso()
    manifest = pack.manifest
    counts = manifest.get("counts") or {}
    with db.transaction() as tx:
        tx.execute(
            """
            INSERT INTO assessment_pack (
                pack_id, kind, chapter_id, class_level, subject, pack_version,
                content_hash, source_path, run_id, generator, gate_verdict,
                counts, generated_at, imported_at
            ) VALUES (?, ?, ?, ?, 'physics', ?, ?, ?, ?, ?, 'pass', ?, ?, ?)
            ON CONFLICT (pack_id) DO UPDATE SET
                source_path = excluded.source_path,
                run_id = excluded.run_id,
                generator = excluded.generator,
                counts = excluded.counts,
                generated_at = excluded.generated_at,
                imported_at = excluded.imported_at
            """,
            (
                pack.pack_id,
                PACK_KIND,
                pack.chapter_id,
                pack.class_level,
                int(manifest["pack_version"]),
                pack.content_hash,
                _source_label(pack.pack_dir),
                manifest.get("run_id"),
                manifest.get("generator"),
                _json(counts),
                manifest.get("generated_at"),
                stamp,
            ),
        )
        for row in pack.questions:
            tx.execute(
                _QUESTION_UPSERT_SQL,
                (
                    str(row["question_id"]),
                    str(row["base_item_id"]),
                    int(row["class_level"]),
                    str(row["chapter_id"]),
                    str(row["concept_id"]),
                    str(row["type"]),
                    str(row["difficulty"]),
                    float(row["marks"]),
                    str(row["language"]),
                    str(row["source_type"]),
                    _json(row.get("source_ref") or {}),
                    str(row["prompt"]),
                    _json(row.get("options") or []),
                    _json(row["answer"]),
                    str(row["explanation"]),
                    row.get("misconception"),
                    int(row["expected_time_ms"]),
                    str(row.get("status") or "reviewed"),
                    str(row.get("review_mode") or "deterministic"),
                    int(row.get("version") or 1),
                    row.get("generator"),
                    pack.pack_id,
                    stamp,
                    stamp,
                ),
            )
        for row in pack.speaking:
            tx.execute(
                _SPEAKING_UPSERT_SQL,
                (
                    str(row["prompt_id"]),
                    str(row["language"]),
                    int(row.get("class_level") or pack.class_level),
                    str(row["chapter_id"]),
                    _json(row.get("concept_ids") or []),
                    str(row["prompt"]),
                    _json(row.get("key_ideas") or []),
                    str(row["model_answer"]),
                    _json(row.get("model_answer_source") or {}),
                    _json(row.get("thresholds") or {}),
                    str(row.get("status") or "reviewed"),
                    int(row.get("version") or 1),
                    pack.pack_id,
                    stamp,
                    stamp,
                ),
            )
        # Topic priors have no learner references: replace the chapter's set so a
        # removed concept cannot linger with a stale prior.
        tx.execute(
            "DELETE FROM topic_time_prior WHERE chapter_id = ?", (pack.chapter_id,)
        )
        for row in pack.priors:
            tx.execute(
                _PRIOR_INSERT_SQL,
                (
                    str(row["chapter_id"]),
                    str(row["scope"]),
                    str(row["scope_id"]),
                    pack.class_level,
                    int(row["expected_time_ms"]),
                    int(row.get("questions") or 0),
                    str(row["formula_version"]),
                    pack.pack_id,
                    stamp,
                ),
            )
    return ImportResult(
        pack_id=pack.pack_id,
        chapter_id=pack.chapter_id,
        class_level=pack.class_level,
        questions=len(pack.questions),
        speaking_rows=len(pack.speaking),
        topic_priors=len(pack.priors),
        content_hash=pack.content_hash,
    )


def import_packs(db: DatabaseEngine, packs_dir: Path) -> list[ImportResult]:
    """Verify every pack under `packs_dir`, then import each one."""
    pack_dirs = sorted(path.parent for path in Path(packs_dir).glob("*/manifest.json"))
    if not pack_dirs:
        raise PackError(f"{packs_dir}: no pack directories (expected */manifest.json)")
    packs = [load_pack(path) for path in pack_dirs]  # verify all before writing any
    return [import_pack(db, pack) for pack in packs]


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: verify + import the tracked packs."""
    parser = argparse.ArgumentParser(
        description="Import assessment packs into question_bank/speaking_prompt/topic_time_prior."
    )
    parser.add_argument(
        "--packs-dir",
        default=str(DEFAULT_PACKS_DIR),
        help=f"directory of pack sub-directories (default: {DEFAULT_PACKS_DIR})",
    )
    parser.add_argument(
        "--db-url",
        default=os.environ.get("ZIVON_DB_URL", DEFAULT_DB_URL),
        help="database URL (default: $ZIVON_DB_URL or sqlite:///zivon.db)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="verify the packs and print what would be written; no DB writes",
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
    except PackError as exc:
        print(f"[import] refused: {exc}", file=sys.stderr)
        return 1

    for pack in packs:
        print(
            f"[import] verified {pack.chapter_id}: "
            f"{len(pack.questions)} question rows, {len(pack.speaking)} speaking rows, "
            f"{len(pack.priors)} topic priors, {pack.content_hash[:19]}..."
        )
    if args.dry_run:
        print(f"[import] dry run: {len(packs)} pack(s) verified, nothing written")
        return 0

    try:
        db = DatabaseEngine.from_url(args.db_url, auto_migrate=not args.no_migrate)
        results = [import_pack(db, pack) for pack in packs]
    except PackError as exc:
        print(f"[import] refused: {exc}", file=sys.stderr)
        return 1

    questions = sum(result.questions for result in results)
    speaking = sum(result.speaking_rows for result in results)
    priors = sum(result.topic_priors for result in results)
    print(
        f"[import] imported {len(results)} pack(s): {questions} question rows, "
        f"{speaking} speaking rows, {priors} topic priors (schema {db.schema_version()})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
