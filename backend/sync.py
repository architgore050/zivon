"""Cold-storage sync, base backup, eviction guard, and publish verification hook.

Implements `docs/backend/storage-tiering.md` §3–§6 and `sync-policy.csv`.
**SIMULATED STORE (honest state, 2026-11-10):** `COLD_BUCKET_*` object
storage is NOT wired — `_write_cold_object` only stages to the local
cold-staging directory (`ZIVON_COLD_STAGING_DIR`). SYNC-02/-03 "upload to B2/R2"
means "stage locally + SHA-256 read-back verify"; getting bytes into real
object storage is a manual copy of the staged files (restore path =
`python -m backend.sync decrypt` + manual upload, see
`docs/deployment/restore-drill.md`).

- `SYNC-01`: Publish-time synchronous "upload" + SHA-256 read-back verification +
  `cold_verified_at` stamp before flipping `live_pointer` (`NFR-18`). Generic
  hook shared by `scripts/publish-frontend.sh`, EX2-TRANS, and EX8-NARRATION.
- `SYNC-02` (simulated staging): Daily DB base backup
  (`base/{YYYY-MM-DD}.enc`, HMAC-CTR envelope-encrypted) + read-back
  verification (`C14`). **No WAL archiving / PITR is implemented** — the
  effective RPO is the last base backup (<= 24 h), not the `<= 5 min` target
  in `backend-spec.md` NFR-17.
- `SYNC-03` (simulated staging): Nightly client-side envelope-encrypted snapshot
  of `consent_record` (`C9`), `audit_log` (`C13`), and `deletion_request`
  (`C18`).
- `SYNC-05`: Nightly archive of completed factory runs (`C4`) with manifest and
  read-back checksum verification.
- `EVICT-01`: Hard eviction invariant (`cold_verified_at IS NOT NULL AND NOT pinned`
  and cold provider reachable).
- `REDEL-01`: Re-apply `deletion_request` tombstones after any DB restore before
  serving traffic.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import io
import json
import os
import sys
import tarfile
import zlib
from pathlib import Path
from typing import Any

from db.engine import DatabaseEngine
from db.schema import ALL_TABLES
from db.uuid7 import uuid7_str

from .config import BackendConfig, normalize_locale
from .logging_shim import ErrorClass, Severity, log_event
from .privacy import DeletionAndRetentionService


class SyncVerificationError(RuntimeError):
    """Raised when a cold upload or read-back checksum verification fails."""


class EvictionInvariantError(RuntimeError):
    """Raised when an eviction attempt violates EVICT-01 preconditions."""


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _fmt_iso(dt: datetime.datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.UTC)
    else:
        dt = dt.astimezone(datetime.UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _keystream_xor(key_bytes: bytes, nonce: bytes, data: bytes) -> bytes:
    """XOR `data` with the ordered HMAC-SHA256(nonce+counter) keystream (both directions)."""
    stream = bytearray(data)
    block_count = (len(data) + 31) // 32
    for idx in range(block_count):
        blk = hmac.new(
            key_bytes, nonce + idx.to_bytes(4, "big"), hashlib.sha256
        ).digest()
        start = idx * 32
        end = min(start + 32, len(data))
        for j in range(start, end):
            stream[j] = data[j] ^ blk[j - start]
    return bytes(stream)


def _encrypt_envelope(plaintext: bytes, secret_key: str) -> bytes:
    """Client-side authenticated envelope encryption for child-adjacent archives (A-13).

    Reversible via the `decrypt` CLI subcommand below; the key source
    (`ZIVON_SESSION_TOKEN_KEY`, ref `k8s:zivon-voice-env`) is the same one that
    encrypted — see `docs/deployment/restore-drill.md` §2.
    """
    compressed = zlib.compress(plaintext, level=6)
    nonce = os.urandom(16)
    key_bytes = hashlib.sha256(secret_key.encode("utf-8")).digest()
    ciphertext = _keystream_xor(key_bytes, nonce, compressed)
    mac = hmac.new(key_bytes, nonce + ciphertext, hashlib.sha256).hexdigest()
    envelope = {
        "v": 1,
        "alg": "ZIVON-HMAC-CTR-SHA256",
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "mac": mac,
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }
    return json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _decrypt_envelope(envelope: bytes, secret_key: str) -> bytes:
    """Reverse of `_encrypt_envelope`: verify the MAC, undo the keystream, decompress."""
    try:
        obj = json.loads(envelope.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SyncVerificationError(
            f"Not a Zivon envelope (JSON parse failed): {exc}"
        ) from exc
    if (
        not isinstance(obj, dict)
        or obj.get("v") != 1
        or obj.get("alg") != "ZIVON-HMAC-CTR-SHA256"
    ):
        raise SyncVerificationError(
            f"Unsupported envelope format: v={obj.get('v')!r} alg={obj.get('alg')!r}"
        )
    try:
        nonce = base64.b64decode(obj["nonce"], validate=True)
        ciphertext = base64.b64decode(obj["ciphertext"], validate=True)
    except (KeyError, ValueError) as exc:
        raise SyncVerificationError(
            "Envelope is missing or has invalid base64 fields"
        ) from exc
    key_bytes = hashlib.sha256(secret_key.encode("utf-8")).digest()
    expected_mac = hmac.new(key_bytes, nonce + ciphertext, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_mac, str(obj.get("mac", ""))):
        raise SyncVerificationError(
            "Envelope MAC mismatch — wrong key or tampered ciphertext"
        )
    return zlib.decompress(_keystream_xor(key_bytes, nonce, ciphertext))


def _bundle_path_bytes(target_path: Path) -> tuple[bytes, str, int]:
    """Read a file or deterministic tar bundle of a directory, returning (bytes, content_type, file_count)."""
    if target_path.is_file():
        raw = target_path.read_bytes()
        ctype = (
            "audio/opus"
            if target_path.suffix == ".opus"
            else (
                "application/json"
                if target_path.suffix == ".json"
                else "application/octet-stream"
            )
        )
        return raw, ctype, 1

    if not target_path.is_dir():
        raise FileNotFoundError(f"Artifact path does not exist: {target_path}")

    buf = io.BytesIO()
    files = sorted(p for p in target_path.rglob("*") if p.is_file())
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.PAX_FORMAT) as tf:
        for fpath in files:
            rel = fpath.relative_to(target_path).as_posix()
            info = tarfile.TarInfo(name=rel)
            data = fpath.read_bytes()
            info.size = len(data)
            info.mtime = 0
            info.uid = 1000
            info.gid = 1000
            info.mode = 0o644
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue(), "application/gzip", len(files)


class ColdStorageSync:
    """Executes SYNC-01..05, EVICT-01, and REDEL-01 against `object_catalog` and cold store."""

    def __init__(
        self,
        db: DatabaseEngine,
        config: BackendConfig | None = None,
        *,
        cold_reachable: bool = True,
        corrupt_readback: bool = False,
    ) -> None:
        self.db = db
        self.config = config or BackendConfig.from_env()
        self.cold_reachable = cold_reachable
        self.corrupt_readback = corrupt_readback
        self._staging_root = Path(self.config.cold_staging_dir)

    def _write_cold_object(self, provider: str, cold_key: str, data: bytes) -> Path:
        if not self.cold_reachable:
            raise SyncVerificationError(
                f"Cold storage provider '{provider}' is unreachable"
            )
        dest = self._staging_root / provider / cold_key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return dest

    def _readback_verify(
        self, provider: str, cold_key: str, expected_sha256: str
    ) -> bool:
        if not self.cold_reachable:
            return False
        dest = self._staging_root / provider / cold_key
        if not dest.is_file():
            return False
        actual_bytes = dest.read_bytes()
        if self.corrupt_readback:
            actual_bytes = actual_bytes + b"corrupted"
        return _sha256_bytes(actual_bytes) == expected_sha256

    def publish_and_verify_artifact(
        self,
        artifact_path: str | Path,
        *,
        class_id: str = "C1",
        course_id: str | None = None,
        class_level: int | None = None,
        locale: str = "en-IN",
        version: str | None = None,
        pinned: bool = True,
        sources: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """SYNC-01: Upload artifact to cold storage, read-back verify SHA-256, and flip live_pointer.

        Used as the generic publish-time verification hook by `scripts/publish-frontend.sh`,
        `EX2-TRANS` (localized bundles), and `EX8-NARRATION` (pre-generated Opus audio).
        """
        path = Path(artifact_path)
        payload_bytes, content_type, file_count = _bundle_path_bytes(path)
        sha256 = _sha256_bytes(payload_bytes)
        size_bytes = len(payload_bytes)
        norm_locale = normalize_locale(locale)
        eff_version = version or sha256[:12]
        eff_course = course_id or path.name

        obj_key = f"{class_id.lower()}/{eff_course}/{class_level or 0}/{norm_locale}/{eff_version}/{sha256}"
        cold_key = f"{obj_key}.bundle"
        now_iso = _fmt_iso(_utc_now())

        # 1. Insert object_catalog (state='uploading') + outbox job in one transaction
        object_id = uuid7_str()
        page_version_id = uuid7_str()
        with self.db.transaction() as tx:
            existing_obj = tx.fetchone(
                "SELECT object_id FROM object_catalog WHERE key = ?",
                (obj_key,),
            )
            if existing_obj is not None:
                object_id = str(existing_obj["object_id"])
                tx.execute(
                    """
                    UPDATE object_catalog
                    SET sha256 = ?, size_bytes = ?, state = 'uploading', cold_verified_at = NULL
                    WHERE object_id = ?
                    """,
                    (sha256, size_bytes, object_id),
                )
            else:
                tx.execute(
                    """
                    INSERT INTO object_catalog (
                        object_id, class_id, key, sha256, size_bytes, content_type,
                        version_ref, ssd_path, cold_provider, cold_key,
                        cold_verified_at, pinned, state, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, 'uploading', ?)
                    """,
                    (
                        object_id,
                        class_id,
                        obj_key,
                        sha256,
                        size_bytes,
                        content_type,
                        eff_version,
                        str(path),
                        self.config.cold_provider,
                        cold_key,
                        1 if pinned else 0,
                        now_iso,
                    ),
                )

            tx.execute(
                """
                INSERT INTO outbox (idempotency_key, object_id, job_type, payload, created_at)
                VALUES (?, ?, 'upload', ?, ?)
                ON CONFLICT (idempotency_key) DO UPDATE SET
                    attempts = outbox.attempts + 1
                """,
                (
                    f"sync01:{obj_key}",
                    object_id,
                    json.dumps(
                        {
                            "key": obj_key,
                            "sha256": sha256,
                            "file_count": file_count,
                        }
                    ),
                    now_iso,
                ),
            )

            if course_id is not None and class_level is not None:
                tx.execute(
                    """
                    INSERT INTO content_page (course_id, class_level, title, chapter, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT (course_id, class_level) DO NOTHING
                    """,
                    (
                        course_id,
                        class_level,
                        course_id.replace("-", " ").title(),
                        course_id,
                        now_iso,
                    ),
                )
                existing_pv = tx.fetchone(
                    """
                    SELECT page_version_id FROM page_version
                    WHERE course_id = ? AND class_level = ? AND version = ?
                    """,
                    (course_id, class_level, eff_version),
                )
                if existing_pv is not None:
                    page_version_id = str(existing_pv["page_version_id"])
                else:
                    tx.execute(
                        """
                        INSERT INTO page_version (
                            page_version_id, course_id, class_level, version,
                            status, sha256, size_bytes, manifest, sources,
                            object_id, generated_at
                        ) VALUES (?, ?, ?, ?, 'reviewed', ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            page_version_id,
                            course_id,
                            class_level,
                            eff_version,
                            sha256,
                            size_bytes,
                            json.dumps({"files": file_count, "sha256": sha256}),
                            json.dumps(sources or [{"source": "ncert"}]),
                            object_id,
                            now_iso,
                        ),
                    )

        # 2. Upload to cold provider and read-back verify SHA-256
        try:
            self._write_cold_object(self.config.cold_provider, cold_key, payload_bytes)
            verified = self._readback_verify(
                self.config.cold_provider, cold_key, sha256
            )
        except Exception as exc:
            log_event(
                "factory.publish.fail",
                {"target": "snapshot", "reason_code": "cold_unreachable"},
                severity=Severity.ERROR,
                error_class=ErrorClass.INFRA_ERROR,
            )
            raise SyncVerificationError(str(exc)) from exc

        verified_iso = _fmt_iso(_utc_now())
        if not verified:
            with self.db.transaction() as tx:
                tx.execute(
                    "UPDATE object_catalog SET state = 'quarantined' WHERE object_id = ?",
                    (object_id,),
                )
            log_event(
                "factory.publish.fail",
                {"target": "snapshot", "reason_code": "checksum_mismatch"},
                severity=Severity.ERROR,
                error_class=ErrorClass.INFRA_ERROR,
            )
            raise SyncVerificationError(
                f"Cold read-back SHA-256 mismatch for key '{obj_key}' (quarantined)"
            )

        # 3. Stamp cold_verified_at and ONLY THEN flip live_pointer (NFR-18)
        with self.db.transaction() as tx:
            tx.execute(
                """
                UPDATE object_catalog
                SET cold_verified_at = ?, state = 'cold_verified'
                WHERE object_id = ?
                """,
                (verified_iso, object_id),
            )
            tx.execute(
                """
                UPDATE outbox
                SET processed_at = ?
                WHERE idempotency_key = ?
                """,
                (verified_iso, f"sync01:{obj_key}"),
            )
            if course_id is not None and class_level is not None:
                tx.execute(
                    """
                    UPDATE page_version
                    SET status = 'published', published_at = ?
                    WHERE page_version_id = ?
                    """,
                    (verified_iso, page_version_id),
                )
                tx.execute(
                    """
                    INSERT INTO live_pointer (course_id, class_level, locale, page_version_id, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT (course_id, class_level, locale) DO UPDATE SET
                        page_version_id = excluded.page_version_id,
                        updated_at = excluded.updated_at
                    """,
                    (
                        course_id,
                        class_level,
                        norm_locale,
                        page_version_id,
                        verified_iso,
                    ),
                )

        log_event(
            "factory.publish.ok",
            {"target": "snapshot", "asset_count": file_count},
            severity=Severity.INFO,
        )
        return {
            "object_id": object_id,
            "key": obj_key,
            "sha256": sha256,
            "size_bytes": size_bytes,
            "file_count": file_count,
            "cold_verified_at": verified_iso,
            "state": "cold_verified",
            "page_version_id": page_version_id if course_id else None,
        }

    def run_base_backup(
        self, *, now_dt: datetime.datetime | None = None
    ) -> dict[str, Any]:
        """SYNC-02: Export U2 database base backup (`C14`), encrypt client-side, upload to B2+R2, and verify."""
        now = now_dt or _utc_now()
        day_str = now.strftime("%Y-%m-%d")
        now_iso = _fmt_iso(now)

        tables_dump: dict[str, list[dict[str, Any]]] = {}
        allowed_tables = set(ALL_TABLES) | {"alembic_version"}
        for tbl in self.db.list_tables():
            if tbl in allowed_tables:
                tables_dump[tbl] = self.db.fetchall(f"SELECT * FROM {tbl}")

        raw_json = json.dumps(
            {"backup_date": day_str, "ts": now_iso, "tables": tables_dump},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        encrypted = _encrypt_envelope(raw_json, self.config.session_token_key)
        sha256 = _sha256_bytes(encrypted)
        cold_key = f"base/{day_str}.enc"
        obj_key = f"c14/base/{day_str}/{sha256[:16]}"

        # Upload to primary (B2) and secondary (R2) per ADR-0004
        self._write_cold_object(self.config.cold_provider, cold_key, encrypted)
        self._write_cold_object("r2", cold_key, encrypted)

        if not (
            self._readback_verify(self.config.cold_provider, cold_key, sha256)
            and self._readback_verify("r2", cold_key, sha256)
        ):
            raise SyncVerificationError("Base backup checksum verification failed")

        object_id = uuid7_str()
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO object_catalog (
                    object_id, class_id, key, sha256, size_bytes, content_type,
                    version_ref, cold_provider, cold_key, cold_verified_at,
                    pinned, encryption_key_ref, state, created_at
                ) VALUES (?, 'C14', ?, ?, ?, 'application/octet-stream', ?, ?, ?, ?, 1, 'k8s:zivon-voice-env', 'cold_verified', ?)
                ON CONFLICT (key) DO UPDATE SET
                    cold_verified_at = excluded.cold_verified_at,
                    state = 'cold_verified'
                """,
                (
                    object_id,
                    obj_key,
                    sha256,
                    len(encrypted),
                    day_str,
                    f"{self.config.cold_provider}+r2",
                    cold_key,
                    now_iso,
                    now_iso,
                ),
            )
        return {
            "object_id": object_id,
            "key": obj_key,
            "cold_key": cold_key,
            "sha256": sha256,
            "size_bytes": len(encrypted),
            "providers": [self.config.cold_provider, "r2"],
            "cold_verified_at": now_iso,
        }

    def run_nightly_sync(
        self, *, now_dt: datetime.datetime | None = None
    ) -> dict[str, Any]:
        """SYNC-03 & SYNC-05: Snapshot append-only legal ledgers (C9/C13/C18) and archive completed runs (C4)."""
        now = now_dt or _utc_now()
        day_str = now.strftime("%Y-%m-%d")
        now_iso = _fmt_iso(now)

        consents = self.db.fetchall(
            "SELECT * FROM consent_record ORDER BY recorded_at ASC"
        )
        audits = self.db.fetchall("SELECT * FROM audit_log ORDER BY at ASC")
        tombstones = self.db.fetchall(
            "SELECT * FROM deletion_request ORDER BY requested_at ASC"
        )

        snapshot_payload = {
            "snapshot_date": day_str,
            "ts": now_iso,
            "row_counts": {
                "consent_record": len(consents),
                "audit_log": len(audits),
                "deletion_request": len(tombstones),
            },
            "consent_record": consents,
            "audit_log": audits,
            "deletion_request": tombstones,
        }
        raw_bytes = json.dumps(
            snapshot_payload, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        encrypted = _encrypt_envelope(raw_bytes, self.config.session_token_key)
        sha256 = _sha256_bytes(encrypted)
        cold_key = f"consent-snap/{day_str}.jsonl.enc"
        obj_key = f"c9/consent-snap/{day_str}/{sha256[:16]}"

        self._write_cold_object(self.config.cold_provider, cold_key, encrypted)
        self._write_cold_object("r2", cold_key, encrypted)
        if not (
            self._readback_verify(self.config.cold_provider, cold_key, sha256)
            and self._readback_verify("r2", cold_key, sha256)
        ):
            raise SyncVerificationError(
                "SYNC-03 consent snapshot checksum verification failed"
            )

        snap_obj_id = uuid7_str()
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO object_catalog (
                    object_id, class_id, key, sha256, size_bytes, content_type,
                    version_ref, cold_provider, cold_key, cold_verified_at,
                    pinned, encryption_key_ref, state, created_at
                ) VALUES (?, 'C9', ?, ?, ?, 'application/octet-stream', ?, ?, ?, ?, 1, 'k8s:zivon-voice-env', 'cold_verified', ?)
                ON CONFLICT (key) DO UPDATE SET
                    cold_verified_at = excluded.cold_verified_at,
                    state = 'cold_verified'
                """,
                (
                    snap_obj_id,
                    obj_key,
                    sha256,
                    len(encrypted),
                    day_str,
                    f"{self.config.cold_provider}+r2",
                    cold_key,
                    now_iso,
                    now_iso,
                ),
            )

        # SYNC-05: Mirror completed runs on disk
        runs_archived = 0
        runs_root = Path(self.config.runs_dir)
        if runs_root.is_dir():
            for status_file in sorted(runs_root.glob("*/status.json")):
                run_dir = status_file.parent
                try:
                    st_data = json.loads(status_file.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    log_event(
                        "factory.sync.run_status_unreadable",
                        {
                            "artifact_path": str(status_file),
                            "reason_code": "unreadable",
                        },
                        severity=Severity.WARNING,
                        error_class=ErrorClass.STORE_ERROR,
                    )
                    continue
                if not st_data.get("completed_at"):
                    continue
                run_bytes, ctype, _fcount = _bundle_path_bytes(run_dir)
                r_sha = _sha256_bytes(run_bytes)
                r_cold_key = f"c4/runs/{run_dir.name}/{r_sha}.tar.gz"
                r_obj_key = f"c4/runs/{run_dir.name}/{r_sha[:16]}"
                self._write_cold_object(
                    self.config.cold_provider, r_cold_key, run_bytes
                )
                if not self._readback_verify(
                    self.config.cold_provider, r_cold_key, r_sha
                ):
                    raise SyncVerificationError(
                        f"SYNC-05 run archive verification failed for {run_dir.name}"
                    )
                with self.db.transaction() as tx:
                    tx.execute(
                        """
                        INSERT INTO object_catalog (
                            object_id, class_id, key, sha256, size_bytes, content_type,
                            version_ref, ssd_path, cold_provider, cold_key,
                            cold_verified_at, pinned, state, created_at
                        ) VALUES (?, 'C4', ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'cold_verified', ?)
                        ON CONFLICT (key) DO UPDATE SET
                            cold_verified_at = excluded.cold_verified_at,
                            state = 'cold_verified'
                        """,
                        (
                            uuid7_str(),
                            r_obj_key,
                            r_sha,
                            len(run_bytes),
                            ctype,
                            run_dir.name,
                            str(run_dir),
                            self.config.cold_provider,
                            r_cold_key,
                            now_iso,
                            now_iso,
                        ),
                    )
                runs_archived += 1

        return {
            "snapshot_object_id": snap_obj_id,
            "snapshot_sha256": sha256,
            "row_counts": snapshot_payload["row_counts"],
            "runs_archived": runs_archived,
            "cold_verified_at": now_iso,
        }

    def evict_hot_object(self, key: str) -> dict[str, Any]:
        """EVICT-01: Evict an unpinned, cold-verified object from hot SSD storage."""
        if not self.cold_reachable:
            raise EvictionInvariantError(
                "EVICT-01 violation: cannot evict while cold provider is unreachable"
            )

        now_iso = _fmt_iso(_utc_now())
        with self.db.transaction() as tx:
            row = tx.fetchone(
                """
                SELECT object_id, key, ssd_path, cold_verified_at, pinned, state
                FROM object_catalog WHERE key = ?
                """,
                (key,),
            )
            if row is None:
                raise KeyError(f"Object key not found: {key}")
            if not row.get("cold_verified_at") or row.get("state") != "cold_verified":
                raise EvictionInvariantError(
                    f"EVICT-01 violation: object '{key}' is not cold_verified"
                )
            if bool(row.get("pinned")):
                raise EvictionInvariantError(
                    f"EVICT-01 violation: object '{key}' is pinned and cannot be evicted"
                )

            tx.execute(
                """
                UPDATE object_catalog
                SET evicted_at = ?, state = 'evicted'
                WHERE object_id = ?
                """,
                (now_iso, row["object_id"]),
            )
            ssd_path = row.get("ssd_path")
            if ssd_path:
                p = Path(str(ssd_path))
                if p.is_file():
                    p.unlink()

            return {
                "object_id": row["object_id"],
                "key": key,
                "state": "evicted",
                "evicted_at": now_iso,
            }

    def apply_redelete_on_restore(self) -> dict[str, int]:
        """REDEL-01: Re-apply all completed `deletion_request` tombstones after a DB restore."""
        rows = self.db.fetchall(
            """
            SELECT DISTINCT device_pseudo_id
            FROM deletion_request
            WHERE status = 'completed'
            """
        )
        privacy = DeletionAndRetentionService(self.db)
        reapplied = 0
        for r in rows:
            dev_id = str(r["device_pseudo_id"])
            privacy.wipe_device(dev_id)
            reapplied += 1
        return {"tombstones_checked": len(rows), "reapplied": reapplied}


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for sync/backup CronJobs and `scripts/publish-verify-hook.sh`."""
    args = argv if argv is not None else sys.argv[1:]
    cmd = args[0] if args else "sync-nightly"
    cfg = BackendConfig.from_env(strict_secrets=False)
    engine = DatabaseEngine.from_url(cfg.db_url, auto_migrate=True)
    sync = ColdStorageSync(engine, cfg)

    if cmd == "publish-verify":
        if len(args) < 2:
            print(
                "usage: python -m backend.sync publish-verify <path> [--class-id C1|C2|C3]",
                file=sys.stderr,
            )
            return 2
        target_path = args[1]
        class_id = "C1"
        if "--class-id" in args:
            idx = args.index("--class-id")
            if idx + 1 < len(args):
                class_id = args[idx + 1]
        res = sync.publish_and_verify_artifact(target_path, class_id=class_id)
        print(f"[publish-verify] ok sha256={res['sha256']} key={res['key']}")
        return 0

    if cmd == "base-backup":
        res = sync.run_base_backup()
        print(f"[base-backup] ok sha256={res['sha256']} cold_key={res['cold_key']}")
        return 0

    if cmd == "sync-nightly":
        res = sync.run_nightly_sync()
        print(f"[sync-nightly] ok {json.dumps(res)}")
        return 0

    if cmd == "redelete-restore":
        res = sync.apply_redelete_on_restore()
        print(f"[redelete-restore] ok {json.dumps(res)}")
        return 0

    if cmd == "decrypt":
        if len(args) < 2:
            print(
                "usage: python -m backend.sync decrypt <path> [--out FILE]",
                file=sys.stderr,
            )
            return 2
        enc_path = Path(args[1])
        out_path: Path | None = None
        if "--out" in args:
            idx = args.index("--out")
            if idx + 1 < len(args):
                out_path = Path(args[idx + 1])
        # Key source: ZIVON_SESSION_TOKEN_KEY (config.session_token_key) — the
        # same secret that encrypted the archive (A-13, ref `k8s:zivon-voice-env`).
        key = cfg.session_token_key
        try:
            plaintext = _decrypt_envelope(enc_path.read_bytes(), key)
        except SyncVerificationError as exc:
            print(f"[decrypt] FAILED: {exc}", file=sys.stderr)
            return 1
        if out_path is not None:
            out_path.write_bytes(plaintext)
            print(f"[decrypt] ok wrote {len(plaintext)} bytes -> {out_path}")
        else:
            sys.stdout.buffer.write(plaintext + b"\n")
        return 0

    print(f"Unknown sync command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
