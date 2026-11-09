"""Two-Tier Translation Memory store and Storage Tiering hooks (ADR-0022).

Tier 1 (Phase A + B, always active):
- Content-addressed JSON files on the `zivon-sources` PVC under
  `sources/cache/tm/<locale>/<tm_key[:2]>/<tm_key>.json` (resolved via
  `cfg.repo_path(cfg.paths["text_cache"]) / "tm"`).
- Written atomically (`os.replace`) ONLY after a block passes both deterministic
  rules (`R1`..`R9`) and the `10b-transcheck` LLM reviewer gate (`verdict == "pass"`).
- Human-approved entries (`review_status == "human_approved"` or
  `translation_source == "human"`) take precedence over machine translations and
  are never overwritten by machine regeneration; when `glossary_version` or
  `prompt_version` bumps, human-approved entries matching `(source_content_sha256,
  locale)` are reused automatically (`ADR-0022` §1 & §3).

Tier 2 (Phase B/C relational backing):
- Mirrors Class C3 tables (`translation_memory_entry`, `block_translation`,
  `glossary_term`, `ui_string`, `locale_fallback`) and `outbox` sync jobs
  (`SYNC-01` for `C1` published localized bundles, `SYNC-02` for `C3` WAL/TM
  sync, `SYNC-03` for `C4` translation run evidence per `docs/backend/storage-tiering.md`).
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import Config

VALID_REVIEW_STATUSES = ("machine_verified", "human_approved")
VALID_TRANSLATION_SOURCES = ("machine", "human")
VALID_BLOCK_STATUSES = (
    "draft",
    "verified",
    "human_approved",
    "rejected",
    "fallback_en",
)


def can_evict_ssd_bundle(
    cold_verified_at: str | None,
    pinned: bool = False,
    cold_provider_reachable: bool = True,
) -> bool:
    """Enforce the storage-tiering eviction invariant (spec.md §3.3 SYNC-01 / RB-03):
    LRU eviction from SSD is permitted ONLY when `cold_verified_at IS NOT NULL`,
    the bundle is not `pinned`, and cold storage is reachable."""
    if not cold_provider_reachable:
        return False
    if pinned:
        return False
    return bool(cold_verified_at and cold_verified_at.strip())


class TranslationMemoryStore:
    """Two-tier Translation Memory manager (Tier 1 PVC files + Tier 2 SQL store)."""

    def __init__(self, cache_root: Path, db_path: Path | None = None) -> None:
        self.cache_root = cache_root
        self.cache_root.mkdir(parents=True, exist_ok=True)
        env_db = os.environ.get("ZIVON_TM_DB_PATH")
        self.db_path: Path | None = (
            db_path if db_path is not None else (Path(env_db) if env_db else None)
        )
        if self.db_path is not None:
            self._init_sqlite_tier2(self.db_path)

    # --------------------------------------------------------- Tier 1 PVC paths
    def entry_path(self, locale: str, tm_key: str) -> Path:
        return self.cache_root / locale / tm_key[:2] / f"{tm_key}.json"

    # --------------------------------------------------------- Lookup (Tier 1+2)
    def lookup(
        self,
        *,
        locale: str,
        tm_key: str,
        source_content_sha256: str | None = None,
    ) -> dict[str, Any] | None:
        """Look up a verified TM entry by exact `tm_key`, or fallback to a
        `human_approved` entry matching `(source_content_sha256, locale)` when
        glossary/prompt version bumped (ADR-0022 §1)."""
        # 1. Exact tm_key hit on Tier 1 PVC
        p = self.entry_path(locale, tm_key)
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if (
                    isinstance(data, dict)
                    and data.get("tm_key") == tm_key
                    and data.get("review_status") in VALID_REVIEW_STATUSES
                ):
                    return data
            except json.JSONDecodeError:
                pass

        # 2. Exact tm_key hit on Tier 2 relational DB (hydrates Tier 1 on hit)
        if self.db_path is not None:
            row = self._db_lookup_exact(tm_key)
            if row is not None:
                self._write_tier1_atomic(p, row)
                return row

        # 3. Human-approved override lookup by (source_content_sha256, locale)
        if source_content_sha256:
            human_override = self.lookup_human_approved(
                locale=locale, source_content_sha256=source_content_sha256
            )
            if human_override is not None:
                return human_override

        return None

    def lookup_human_approved(
        self, *, locale: str, source_content_sha256: str
    ) -> dict[str, Any] | None:
        """Search Tier 2 DB and Tier 1 locale directory for a human_approved
        override matching `(source_content_sha256, locale)`."""
        if self.db_path is not None:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.execute(
                    """
                    SELECT * FROM translation_memory_entry
                    WHERE source_content_sha256 = ? AND locale = ?
                      AND (review_status = 'human_approved' OR translation_source = 'human')
                    ORDER BY last_used_at DESC LIMIT 1
                    """,
                    (source_content_sha256, locale),
                )
                r = cur.fetchone()
                if r is not None:
                    return self._row_to_envelope(dict(r))

        loc_dir = self.cache_root / locale
        if not loc_dir.exists():
            return None
        for path in sorted(loc_dir.glob("*/*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if (
                isinstance(data, dict)
                and data.get("source_content_sha256") == source_content_sha256
                and data.get("locale") == locale
                and (
                    data.get("review_status") == "human_approved"
                    or data.get("translation_source") == "human"
                )
            ):
                return data
        return None

    # --------------------------------------------------------- Write (Verified)
    def store_verified_unit(self, envelope: dict[str, Any]) -> Path:
        """Persist a verified unit translation to Tier 1 PVC and Tier 2 DB.

        Enforces ADR-0022 §2:
        - Rejects unverified or rejected entries (`review_status` must be in
          `('machine_verified', 'human_approved')`).
        - Never overwrites an existing `human_approved` entry with a machine
          translation.
        """
        review_status = str(envelope.get("review_status", ""))
        if review_status not in VALID_REVIEW_STATUSES:
            raise ValueError(
                f"refusing to write unverified translation (review_status={review_status!r}) "
                "to Translation Memory; only machine_verified or human_approved entries are allowed"
            )
        translation_source = str(envelope.get("translation_source", "machine"))
        if translation_source not in VALID_TRANSLATION_SOURCES:
            raise ValueError(f"invalid translation_source {translation_source!r}")

        locale = str(envelope["locale"])
        tm_key = str(envelope["tm_key"])
        source_sha = str(envelope["source_content_sha256"])

        existing = self.lookup(
            locale=locale, tm_key=tm_key, source_content_sha256=source_sha
        )
        if (
            existing is not None
            and (
                existing.get("review_status") == "human_approved"
                or existing.get("translation_source") == "human"
            )
            and translation_source == "machine"
        ):
            # Preserve human override; do not clobber with machine output
            return self.entry_path(locale, str(existing["tm_key"]))

        now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        stored = {
            **envelope,
            "review_status": review_status,
            "translation_source": translation_source,
            "last_used_at": now_iso,
        }
        stored.setdefault("created_at", now_iso)

        path = self.entry_path(locale, tm_key)
        self._write_tier1_atomic(path, stored)

        if self.db_path is not None:
            self._db_upsert_tm_entry(stored)

        return path

    def record_block_translation(
        self,
        *,
        lesson_version_id: str,
        block_id_str: str,
        locale: str,
        source_content_sha256: str,
        tm_key: str | None,
        translated_spec: dict[str, Any],
        status: str = "verified",
        translation_source: str = "machine",
        reviewer_report: dict[str, Any] | None = None,
        reviewed_by: str | None = None,
        content_block_id: str | None = None,
    ) -> dict[str, Any]:
        """Record a per-lesson-version `block_translation` row (Class C3, spec.md §3.2)."""
        if status not in VALID_BLOCK_STATUSES:
            raise ValueError(f"invalid block_translation status {status!r}")
        now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        row = {
            "id": str(uuid.uuid4()),
            "lesson_version_id": lesson_version_id,
            "content_block_id": content_block_id,
            "block_id_str": block_id_str,
            "locale": locale,
            "source_content_sha256": source_content_sha256,
            "tm_key": tm_key,
            "translated_spec": translated_spec,
            "translation_source": translation_source,
            "status": status,
            "reviewer_report": reviewer_report,
            "reviewed_by": reviewed_by,
            "reviewed_at": now_iso if reviewed_by else None,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        if self.db_path is not None:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO block_translation (
                        id, lesson_version_id, content_block_id, block_id_str, locale,
                        source_content_sha256, tm_key, translated_spec, translation_source,
                        status, reviewer_report, reviewed_by, reviewed_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(lesson_version_id, block_id_str, locale) DO UPDATE SET
                        source_content_sha256 = excluded.source_content_sha256,
                        tm_key = excluded.tm_key,
                        translated_spec = excluded.translated_spec,
                        translation_source = excluded.translation_source,
                        status = excluded.status,
                        reviewer_report = excluded.reviewer_report,
                        reviewed_by = excluded.reviewed_by,
                        reviewed_at = excluded.reviewed_at,
                        updated_at = excluded.updated_at
                    """,
                    (
                        row["id"],
                        row["lesson_version_id"],
                        row["content_block_id"],
                        row["block_id_str"],
                        row["locale"],
                        row["source_content_sha256"],
                        row["tm_key"],
                        json.dumps(row["translated_spec"], ensure_ascii=False),
                        row["translation_source"],
                        row["status"],
                        json.dumps(row["reviewer_report"], ensure_ascii=False)
                        if row["reviewer_report"] is not None
                        else None,
                        row["reviewed_by"],
                        row["reviewed_at"],
                        row["created_at"],
                        row["updated_at"],
                    ),
                )
        return row

    # ------------------------------------------------ Storage Tiering & Outbox
    def queue_outbox_sync(
        self,
        *,
        rule_id: str,
        class_id: str,
        job_type: str,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Queue an idempotent cold-storage sync job (`SYNC-01` C1, `SYNC-02` C3,
        `SYNC-03` C4 per spec.md §3.3)."""
        now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        job = {
            "rule_id": rule_id,
            "class_id": class_id,
            "job_type": job_type,
            "idempotency_key": idempotency_key,
            "payload": payload,
            "attempts": 0,
            "created_at": now_iso,
            "processed_at": None,
        }
        if self.db_path is not None:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO outbox (idempotency_key, job_type, payload, attempts, created_at)
                    VALUES (?, ?, ?, 0, ?)
                    ON CONFLICT(idempotency_key) DO NOTHING
                    """,
                    (
                        idempotency_key,
                        job_type,
                        json.dumps(job, ensure_ascii=False),
                        now_iso,
                    ),
                )
        return job

    def record_bundle_publish_sync(
        self,
        *,
        topic_slug: str,
        class_level: int,
        locale: str,
        version: str,
        bundle_bytes: bytes,
    ) -> dict[str, Any]:
        """Create a SYNC-01 (Class C1) outbox job for a published localized bundle."""
        sha256 = hashlib.sha256(bundle_bytes).hexdigest()
        cold_key = f"c1/{topic_slug}/{class_level}/{locale}/{version}/{sha256}.tar.zst"
        return self.queue_outbox_sync(
            rule_id="SYNC-01",
            class_id="C1",
            job_type="upload",
            idempotency_key=f"sync01:{locale}:{sha256}",
            payload={
                "cold_key": cold_key,
                "sha256": sha256,
                "size_bytes": len(bundle_bytes),
                "locale": locale,
                "live_pointer_held_until_verified": True,
            },
        )

    # --------------------------------------------------------- Internals
    @staticmethod
    def _write_tier1_atomic(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        os.replace(tmp, path)

    def _init_sqlite_tier2(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS locale_fallback (
                    locale TEXT PRIMARY KEY,
                    autonym TEXT NOT NULL,
                    script_code TEXT NOT NULL,
                    fallback_locale TEXT NULL,
                    baseline_nudge_px REAL NOT NULL DEFAULT 0.0,
                    launch_tier TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS glossary_term (
                    id TEXT PRIMARY KEY,
                    term_slug TEXT NOT NULL,
                    locale TEXT NOT NULL,
                    english_term TEXT NOT NULL,
                    native_term TEXT NOT NULL,
                    first_mention_gloss TEXT NOT NULL,
                    short_label TEXT NOT NULL,
                    do_not_translate INTEGER NOT NULL DEFAULT 0,
                    pronunciation_hint TEXT NULL,
                    glossary_version TEXT NOT NULL DEFAULT '1.0.0',
                    updated_at TEXT NOT NULL,
                    UNIQUE (term_slug, locale, glossary_version)
                );
                CREATE TABLE IF NOT EXISTS translation_memory_entry (
                    tm_key TEXT PRIMARY KEY,
                    source_content_sha256 TEXT NOT NULL,
                    unit_type TEXT NOT NULL,
                    locale TEXT NOT NULL,
                    glossary_version TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    source_payload TEXT NOT NULL,
                    translated_payload TEXT NOT NULL,
                    translation_source TEXT NOT NULL DEFAULT 'machine',
                    model_id TEXT NOT NULL DEFAULT 'evon-v3.3',
                    review_status TEXT NOT NULL DEFAULT 'machine_verified',
                    created_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL,
                    UNIQUE (source_content_sha256, locale, glossary_version, prompt_version)
                );
                CREATE INDEX IF NOT EXISTS idx_tm_source_sha_locale
                    ON translation_memory_entry (source_content_sha256, locale);
                CREATE TABLE IF NOT EXISTS block_translation (
                    id TEXT PRIMARY KEY,
                    lesson_version_id TEXT NOT NULL,
                    content_block_id TEXT NULL,
                    block_id_str TEXT NOT NULL,
                    locale TEXT NOT NULL,
                    source_content_sha256 TEXT NOT NULL,
                    tm_key TEXT NULL,
                    translated_spec TEXT NOT NULL,
                    translation_source TEXT NOT NULL DEFAULT 'machine',
                    status TEXT NOT NULL DEFAULT 'draft',
                    reviewer_report TEXT NULL,
                    reviewed_by TEXT NULL,
                    reviewed_at TEXT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (lesson_version_id, block_id_str, locale)
                );
                CREATE TABLE IF NOT EXISTS ui_string (
                    copy_key TEXT NOT NULL,
                    locale TEXT NOT NULL,
                    text_value TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'human',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (copy_key, locale)
                );
                CREATE TABLE IF NOT EXISTS outbox (
                    outbox_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    idempotency_key TEXT UNIQUE NOT NULL,
                    job_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    processed_at TEXT NULL
                );
                """
            )

    def _db_lookup_exact(self, tm_key: str) -> dict[str, Any] | None:
        assert self.db_path is not None
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT * FROM translation_memory_entry WHERE tm_key = ?", (tm_key,)
            )
            r = cur.fetchone()
            if r is None:
                return None
            now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            conn.execute(
                "UPDATE translation_memory_entry SET last_used_at = ? WHERE tm_key = ?",
                (now_iso, tm_key),
            )
            return self._row_to_envelope(dict(r))

    def _db_upsert_tm_entry(self, envelope: dict[str, Any]) -> None:
        assert self.db_path is not None
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO translation_memory_entry (
                    tm_key, source_content_sha256, unit_type, locale,
                    glossary_version, prompt_version, source_payload,
                    translated_payload, translation_source, model_id,
                    review_status, created_at, last_used_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tm_key) DO UPDATE SET
                    translated_payload = excluded.translated_payload,
                    translation_source = excluded.translation_source,
                    model_id = excluded.model_id,
                    review_status = excluded.review_status,
                    last_used_at = excluded.last_used_at
                """,
                (
                    envelope["tm_key"],
                    envelope["source_content_sha256"],
                    envelope["unit_type"],
                    envelope["locale"],
                    envelope["glossary_version"],
                    envelope["prompt_version"],
                    json.dumps(envelope["source_payload"], ensure_ascii=False),
                    json.dumps(envelope["translated_payload"], ensure_ascii=False),
                    envelope["translation_source"],
                    envelope["model_id"],
                    envelope["review_status"],
                    envelope["created_at"],
                    envelope["last_used_at"],
                ),
            )

    @staticmethod
    def _row_to_envelope(row: dict[str, Any]) -> dict[str, Any]:
        src = row["source_payload"]
        tr = row["translated_payload"]
        return {
            "tm_key": row["tm_key"],
            "source_content_sha256": row["source_content_sha256"],
            "unit_type": row["unit_type"],
            "locale": row["locale"],
            "glossary_version": row["glossary_version"],
            "prompt_version": row["prompt_version"],
            "source_payload": json.loads(src) if isinstance(src, str) else src,
            "translated_payload": json.loads(tr) if isinstance(tr, str) else tr,
            "translation_source": row["translation_source"],
            "model_id": row["model_id"],
            "review_status": row["review_status"],
            "created_at": row["created_at"],
            "last_used_at": row["last_used_at"],
        }


def get_tm_store(cfg: Config, db_path: Path | None = None) -> TranslationMemoryStore:
    cache_root = cfg.repo_path(cfg.paths["text_cache"]) / "tm"
    return TranslationMemoryStore(cache_root=cache_root, db_path=db_path)
