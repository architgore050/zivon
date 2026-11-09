"""Narration publish: availability manifests + cold upload/verify.

Two responsibilities, both at the publishing boundary (never during
synthesis):

1. Availability manifests (gap-register GAP-015): after a narration pass the
   topic's manifest.json carries

       "narration": {
         "available": <bool - does read-aloud have anything to play>,
         "lang": "<locale>",
         "hash": "<sha256[:16] of narration-manifest.json bytes>",
         "mode": "mock" | "live",
         "blocks": {"<block_id>": {"available": bool, "path", "hash",
                                    "duration_ms"}}
       }

   (a superset of the mini-spec's `{available, lang, hash}` flag: the
   per-block map is what makes the features-card "partial" state expressible
   - some blocks speakable, others not - and the mode field makes a mock
   asset visible as such). Next to it, narration-manifest.json holds the
   per-locale narration catalogue `{block_id, lang, hash, chars,
   duration_ms, path}`. The hash is the manifest's own content hash, so the
   client can cache-bust it; a republish that changes anything bumps it.

2. Cold upload + verify (backend-spec SYNC-01 P0 form, class C2 "on
   generation: upload -> verify -> then serve"): a synchronous, checksummed
   copy of every opus asset to the cold provider via operator-configured
   commands - no cloud SDK, no credentials in code (the command lives in
   env, the provider CLI holds the key). Verification is a READ-BACK
   sha256 comparison, not a response code. EX0's generic publish hook does
   not exist on this base branch, so this module is the narration-side hook;
   reconciliation with EX0's hook is flagged for the merge agent.

Cold commands (template placeholders {src} and {dst}, args shell-quoted):
    ZIVON_COLDSTORE_UPLOAD_CMD    e.g. rclone copyto {src} b2:zivon/{dst}
    ZIVON_COLDSTORE_READBACK_CMD  e.g. rclone cat b2:zivon/{dst}
    ZIVON_COLDSTORE_PREFIX        key prefix (default "narration")
Unconfigured = loud skip (assets serve from the PVC; the durability gate is
reported as NOT satisfied rather than silently claimed).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .env import STAGE_ID, NarrationEnv
from .errors import NarrationError

COLD_VERIFY_FILE = "cold-verify.json"


# --------------------------------------------------------------- manifests
def manifest_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]


def update_manifests(
    topic_dir: Path,
    lang: str,
    mode: str,
    assets: list[dict[str, Any]],
    speakable_block_ids: list[str],
    voice: str = "",
) -> dict[str, Any]:
    """Write narration-manifest.json + stamp the availability flag into the
    topic's manifest.json. Idempotent: the same narration state always
    produces byte-identical manifests (the hash is derived from content)."""
    narration_manifest = {
        "lang": lang,
        "voice": voice or "(provider default)",
        "mode": mode,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "blocks": [
            {
                "block_id": asset["block_id"],
                "lang": lang,
                "hash": asset["hash"],
                "chars": asset["chars"],
                "duration_ms": asset.get("duration_ms"),
                "path": asset["path"],
            }
            for asset in assets
        ],
    }
    manifest_path = topic_dir / "narration-manifest.json"
    _write_json(manifest_path, narration_manifest)

    blocks_flag: dict[str, Any] = {}
    available_ids = {asset["block_id"] for asset in assets}
    for block_id in speakable_block_ids:
        asset = next((a for a in assets if a["block_id"] == block_id), None)
        if asset:
            blocks_flag[block_id] = {
                "available": True,
                "path": asset["path"],
                "hash": asset["hash"],
                "duration_ms": asset.get("duration_ms"),
            }
        else:
            blocks_flag[block_id] = {"available": False}
    flag = {
        "available": bool(assets),
        "lang": lang,
        "hash": manifest_hash(narration_manifest),
        "mode": mode,
        "blocks": blocks_flag,
    }

    topic_manifest_path = topic_dir / "manifest.json"
    if not topic_manifest_path.exists():
        raise NarrationError(
            STAGE_ID,
            f"topic manifest vanished at {topic_manifest_path} - the topic "
            "must be published (stage 11-link) before narration stamps it",
        )
    topic_manifest = json.loads(topic_manifest_path.read_text(encoding="utf-8"))
    topic_manifest["narration"] = flag
    _write_json(topic_manifest_path, topic_manifest)
    return {
        "manifest_updated": True,
        "available": flag["available"],
        "hash": flag["hash"],
        "narration_manifest": str(manifest_path),
        "blocks_total": len(speakable_block_ids),
        "blocks_available": len(available_ids & set(speakable_block_ids)),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


# ------------------------------------------------------- cold upload+verify
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _local_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_template(
    template: str, src: Path, dst: str, timeout_s: float
) -> subprocess.CompletedProcess[bytes]:
    """Execute an operator command template with {src}/{dst} substituted
    (shell-quoted). The operator owns the command and the provider
    credentials; this code never sees a secret."""
    command = template.format(src=shlex.quote(str(src)), dst=shlex.quote(dst))
    return subprocess.run(
        command,
        # shell=True is deliberate: the template is operator-owned ops config
        # (env), with {src}/{dst} substituted via shlex.quote.
        shell=True,
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )


def cold_upload_and_verify(audio_root: Path, env: NarrationEnv) -> dict[str, Any]:
    """Synchronous upload + read-back verification for every opus asset.

    Idempotent: a file whose sha256 is already verified in cold-verify.json
    is not re-uploaded (content-addressed assets are immutable). Returns a
    report; a single unverified file marks the whole gate unsatisfied - the
    publish flow decides what that means (SYNC-01: the gate stays held).
    """
    upload_cmd = env.coldstore_upload_cmd
    readback_cmd = env.coldstore_readback_cmd
    if not upload_cmd or not readback_cmd:
        return {
            "skipped": True,
            "reason": (
                "ZIVON_COLDSTORE_UPLOAD_CMD / ZIVON_COLDSTORE_READBACK_CMD not "
                "configured - cold copies NOT verified; narration serves from "
                "the PVC only and the C2 durability gate is unsatisfied"
            ),
            "verified": [],
            "failed": [],
            "verified_count": 0,
            "failed_count": 0,
        }
    if not audio_root.exists():
        return {
            "skipped": True,
            "reason": f"no audio dir at {audio_root}",
            "verified": [],
            "failed": [],
            "verified_count": 0,
            "failed_count": 0,
        }

    state_path = audio_root / COLD_VERIFY_FILE
    prior: dict[str, Any] = {}
    if state_path.exists():
        try:
            prior = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prior = {}
    prior_files: dict[str, str] = prior.get("files", {}) or {}

    files = sorted(audio_root.rglob("*.opus"))
    verified: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for path in files:
        rel = path.relative_to(audio_root).as_posix()
        key = f"{env.coldstore_prefix}/{rel}"
        digest = _local_sha256(path)
        if prior_files.get(rel) == digest:
            verified.append({"file": rel, "sha256": digest, "cached": True})
            continue
        upload = _run_template(upload_cmd, path, key, env.coldstore_timeout_s)
        if upload.returncode != 0:
            failed.append(
                {
                    "file": rel,
                    "sha256": digest,
                    "stage": "upload",
                    "detail": upload.stderr.decode("utf-8", "replace")[-300:],
                }
            )
            continue
        readback = _run_template(readback_cmd, path, key, env.coldstore_timeout_s)
        remote_digest = sha256_bytes(readback.stdout)
        if readback.returncode == 0 and remote_digest == digest:
            verified.append({"file": rel, "sha256": digest, "cached": False})
        else:
            failed.append(
                {
                    "file": rel,
                    "sha256": digest,
                    "stage": "verify",
                    "detail": (
                        f"read-back sha256 mismatch or failure "
                        f"(rc={readback.returncode}, "
                        f"remote={remote_digest[:16]}... local={digest[:16]}...)"
                    ),
                }
            )

    report = {
        "skipped": False,
        "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "prefix": env.coldstore_prefix,
        "files": {v["file"]: v["sha256"] for v in verified},
        "verified": verified,
        "failed": failed,
        "verified_count": len(verified),
        "failed_count": len(failed),
    }
    _write_json(state_path, report)
    return report


# ---------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    """python -m factory.narration.publish --root frontend/audio --cold"""
    parser = argparse.ArgumentParser(
        description="Narration publish helpers: cold upload + sha256 read-back verify"
    )
    parser.add_argument(
        "--root",
        default="frontend/audio",
        help="audio root to verify (default: frontend/audio)",
    )
    parser.add_argument(
        "--cold",
        action="store_true",
        help="run the synchronous cold upload + verify (SYNC-01 P0 form)",
    )
    args = parser.parse_args(argv)
    if not args.cold:
        root = Path(args.root)
        count = len(list(root.rglob("*.opus"))) if root.exists() else 0
        print(json.dumps({"root": str(root), "opus_assets": count}))
        return 0
    env = NarrationEnv.from_env()
    report = cold_upload_and_verify(Path(args.root), env)
    print(json.dumps(report, indent=2))
    if report.get("skipped"):
        print(f"COLD VERIFY SKIPPED: {report['reason']}", file=sys.stderr)
        return 0
    if report["failed_count"]:
        print(
            f"COLD VERIFY FAILED for {report['failed_count']} file(s) - the "
            "C2 durability gate is unsatisfied; inspect cold-verify.json and "
            "re-run after fixing the provider",
            file=sys.stderr,
        )
        return 2
    print(
        f"cold verified {report['verified_count']} narration asset(s) "
        f"(prefix {report['prefix']})"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
