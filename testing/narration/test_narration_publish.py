"""Tests for narration publish: availability manifests + cold upload/verify."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from factory.narration.audio import content_hash
from factory.narration.env import NarrationEnv
from factory.narration.publish import (
    cold_upload_and_verify,
    manifest_hash,
    sha256_bytes,
)


def _env(**overrides) -> NarrationEnv:
    values: dict = {
        "enabled": True,
        "mode": "mock",
        "langs": ("en",),
        "budget_credits": 1500.0,
        "repair_rounds": 2,
        "timbre_base_url": None,
        "timbre_api_key": None,
        "timbre_tts_path": "/v1/tts",
        "timbre_voice": "",
        "credits_per_char": 0.0167,
        "timbre_timeout_s": 30.0,
        "timbre_connect_timeout_s": 5.0,
        "timbre_max_attempts": 3,
        "timbre_backoff_base_s": 0.0,
        "coldstore_upload_cmd": None,
        "coldstore_readback_cmd": None,
        "coldstore_prefix": "narration",
        "coldstore_timeout_s": 60.0,
    }
    values.update(overrides)
    return NarrationEnv(**values)


def _assets(n: int = 2) -> list[dict]:
    out = []
    for i in range(1, n + 1):
        text = f"block {i} prose"
        out.append(
            {
                "block_id": f"b-{i:02d}",
                "path": f"audio/class-9-physics/b-{i:02d}.en.{content_hash('en', '', text)}.opus",
                "hash": content_hash("en", "", text),
                "chars": len(text),
                "duration_ms": 900 + i,
                "bytes": 1234,
                "outcome": "narrated",
            }
        )
    return out


class TestAvailabilityManifests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="zivon-pub-"))
        self.topic = self.tmp / "courses" / "class-9-physics" / "motion"
        self.topic.mkdir(parents=True)
        (self.topic / "manifest.json").write_text(
            json.dumps({"course_id": "class-9-physics", "title": "Motion"}),
            encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_flag_and_catalogue_written(self):
        from factory.narration.publish import update_manifests

        assets = _assets(2)
        summary = update_manifests(
            self.topic,
            "en",
            "mock",
            assets,
            ["b-00-meta", "b-01", "b-02", "b-03"],
            voice="",
        )
        self.assertTrue(summary["manifest_updated"])
        self.assertTrue(summary["available"])

        manifest = json.loads((self.topic / "manifest.json").read_text())
        flag = manifest["narration"]
        # GAP-015 exact fields, present and honest:
        self.assertTrue(flag["available"])
        self.assertEqual(flag["lang"], "en")
        self.assertEqual(len(flag["hash"]), 16)
        self.assertEqual(flag["mode"], "mock")
        # per-block superset: partial availability expressible (INF-089)
        self.assertTrue(flag["blocks"]["b-01"]["available"])
        self.assertFalse(flag["blocks"]["b-03"]["available"])
        self.assertNotIn("b-04", flag["blocks"])  # non-speakable: absent

        catalogue = json.loads((self.topic / "narration-manifest.json").read_text())
        self.assertEqual([b["block_id"] for b in catalogue["blocks"]], ["b-01", "b-02"])
        for entry in catalogue["blocks"]:
            self.assertEqual(
                set(entry), {"block_id", "lang", "hash", "chars", "duration_ms", "path"}
            )
        # the flag's hash is the catalogue's content hash (cache-bust key)
        self.assertEqual(
            flag["hash"],
            manifest_hash(
                json.loads((self.topic / "narration-manifest.json").read_text())
            ),
        )

    def test_no_assets_means_available_false_honestly(self):
        from factory.narration.publish import update_manifests

        summary = update_manifests(
            self.topic, "en", "mock", [], ["b-00-meta", "b-01"], voice=""
        )
        self.assertFalse(summary["available"])
        manifest = json.loads((self.topic / "manifest.json").read_text())
        self.assertFalse(manifest["narration"]["available"])
        self.assertFalse(manifest["narration"]["blocks"]["b-01"]["available"])

    def test_idempotent_same_state_same_hash(self):
        from factory.narration.publish import update_manifests

        args = (self.topic, "en", "mock", _assets(1), ["b-01"])
        first = update_manifests(*args)
        second = update_manifests(*args)
        self.assertEqual(first["hash"], second["hash"])

    def test_missing_topic_manifest_raises(self):
        from factory.narration.errors import NarrationError
        from factory.narration.publish import update_manifests

        (self.topic / "manifest.json").unlink()
        with self.assertRaises(NarrationError):
            update_manifests(self.topic, "en", "mock", _assets(1), ["b-01"])


class TestColdUploadVerify(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="zivon-cold-"))
        self.audio = self.tmp / "audio"
        self.class_dir = self.audio / "class-9-physics"
        self.class_dir.mkdir(parents=True)
        self.cold = self.tmp / "cold"
        (self.class_dir / "b-01.en.aaaa.opus").write_bytes(b"opus-bytes-1")
        (self.class_dir / "b-02.en.bbbb.opus").write_bytes(b"opus-bytes-2")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _env(self, **kw) -> NarrationEnv:
        return _env(
            # the fake provider CLI stores under the sandbox cold root and
            # creates parents the way rclone copyto does ({dst} stays a
            # provider-relative key, exactly like the real template)
            coldstore_upload_cmd=(
                f"mkdir -p $(dirname {self.cold}/{{dst}}) "
                f"&& cp {{src}} {self.cold}/{{dst}}"
            ),
            coldstore_readback_cmd=f"cat {self.cold}/{{dst}}",
            **kw,
        )

    def test_unconfigured_is_a_loud_skip_not_a_silent_pass(self):
        report = cold_upload_and_verify(self.audio, _env())
        self.assertTrue(report["skipped"])
        self.assertIn("NOT verified", report["reason"])
        self.assertFalse((self.audio / "cold-verify.json").exists())

    def test_upload_and_readback_verify_all(self):
        report = cold_upload_and_verify(self.audio, self._env())
        self.assertFalse(report["skipped"])
        self.assertEqual(report["verified_count"], 2)
        self.assertEqual(report["failed_count"], 0)
        uploaded = list((self.cold / "narration" / "class-9-physics").glob("*.opus"))
        self.assertEqual(len(uploaded), 2)
        # read-back bytes match the source exactly
        self.assertEqual(
            (
                self.cold / "narration" / "class-9-physics" / "b-01.en.aaaa.opus"
            ).read_bytes(),
            b"opus-bytes-1",
        )
        state = json.loads((self.audio / "cold-verify.json").read_text())
        self.assertEqual(
            state["files"]["class-9-physics/b-01.en.aaaa.opus"],
            sha256_bytes(b"opus-bytes-1"),
        )

    def test_corrupt_readback_fails_the_gate(self):
        env = _env(
            coldstore_upload_cmd=(
                f"mkdir -p $(dirname {self.cold}/{{dst}}) "
                f"&& cp {{src}} {self.cold}/{{dst}}"
            ),
            coldstore_readback_cmd="echo corrupted-bytes",
        )
        report = cold_upload_and_verify(self.audio, env)
        self.assertEqual(report["failed_count"], 2)
        self.assertIn("mismatch", report["failed"][0]["detail"])

    def test_upload_failure_recorded_not_raised(self):
        env = _env(
            coldstore_upload_cmd="false {src} {dst}",
            coldstore_readback_cmd="cat {dst}",
        )
        report = cold_upload_and_verify(self.audio, env)
        self.assertEqual(report["failed_count"], 2)
        self.assertEqual(report["failed"][0]["stage"], "upload")

    def test_second_run_skips_already_verified_files(self):
        first = cold_upload_and_verify(self.audio, self._env())
        second = cold_upload_and_verify(self.audio, self._env())
        self.assertEqual(first["verified_count"], 2)
        self.assertEqual(second["verified_count"], 2)
        self.assertTrue(all(v.get("cached") for v in second["verified"]))

    def test_missing_audio_root_skips(self):
        report = cold_upload_and_verify(self.tmp / "nope", self._env())
        self.assertTrue(report["skipped"])


class TestCLI(unittest.TestCase):
    def test_cli_reports_and_exits_2_on_verify_failure(self):
        tmp = Path(tempfile.mkdtemp(prefix="zivon-clicold-"))
        try:
            audio = tmp / "audio"
            audio.mkdir()
            (audio / "a.opus").write_bytes(b"x")
            env = _env(
                coldstore_upload_cmd=f"cp {{src}} {tmp}/cold/{{dst}}",
                coldstore_readback_cmd="echo wrong",
            )
            import os

            for key, value in {
                "ZIVON_COLDSTORE_UPLOAD_CMD": env.coldstore_upload_cmd,
                "ZIVON_COLDSTORE_READBACK_CMD": env.coldstore_readback_cmd,
            }.items():
                os.environ[key] = value
            try:
                proc = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "factory.narration.publish",
                        "--root",
                        str(audio),
                        "--cold",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    cwd=Path(__file__).resolve().parents[2],
                    timeout=120,
                )
            finally:
                for key in (
                    "ZIVON_COLDSTORE_UPLOAD_CMD",
                    "ZIVON_COLDSTORE_READBACK_CMD",
                ):
                    os.environ.pop(key, None)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("COLD VERIFY FAILED", proc.stderr)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
