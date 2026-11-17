"""Explain-back API and app pages (F6, REQUIREMENTS §9.5/§10.9/§10.10).

Hermetic: SQLite in memory, the tracked assessment packs through the real
importer, a fake speaking pipeline at the vendor seam (no network, no key).
Covers prompt withholding, the consent and quota gates, the transient upload
bounds, rubric mapping, text-only persistence, self-check, owner-scoped
delete, and the three server-rendered pages.
"""

from __future__ import annotations

import importlib.util
import json
import struct
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from backend import BackendConfig, create_app
from backend.speaking import (
    SpeakingEvaluationError,
    Transcript,
    key_ideas,
    parse_evaluation,
)

PASSWORD = "correct-horse-battery-staple"
CONSENT_VERSION = "v1"
CHAPTER = "class-9-describing-motion-around-us"
PROMPT_ID = "spk-c9-motion-001"
REPO_ROOT = Path(__file__).resolve().parents[2]
PACKS_DIR = REPO_ROOT / "sources" / "assessment" / "packs"


def _load_importer() -> ModuleType:
    path = REPO_ROOT / "scripts" / "import_assessment_packs.py"
    spec = importlib.util.spec_from_file_location(
        "import_assessment_packs_speaking", path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


importer = _load_importer()


def wav_bytes(seconds: float = 2.0, *, sample_rate: int = 16000) -> bytes:
    """A canonical 16 kHz mono PCM16 WAV with a quiet alternating pattern."""
    frames = int(sample_rate * seconds)
    data = b"\x00\x01" * frames
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + len(data))
        + b"WAVE"
        + b"fmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
        + b"data"
        + struct.pack("<I", len(data))
    )
    return header + data


class FakePipeline:
    """Stands in for Prisma STT + the tutor model at the route seam."""

    def __init__(
        self,
        *,
        transcript: str = "Distance is the whole path and displacement is the net change.",
        present: int = 3,
        fail_evaluation: bool = False,
        mock: bool = False,
        available: bool = True,
    ) -> None:
        self.settings = SimpleNamespace(credit_stt_seconds_per_point=30)
        self.mock_mode = mock
        self.available = available
        self.transcript = transcript
        self.present = present
        self.fail_evaluation = fail_evaluation
        self.calls: list[tuple[str, Any]] = []

    async def transcribe(self, pcm: bytes, *, language: str) -> Transcript:
        self.calls.append(("transcribe", len(pcm)))
        return Transcript(
            text=self.transcript,
            language=language,
            duration_ms=round(len(pcm) / 2 / 16000 * 1000),
            stt_ms=12,
            mock=self.mock_mode,
        )

    async def evaluate(self, prompt: dict[str, Any], transcript: str) -> Any:
        self.calls.append(("evaluate", transcript))
        if self.fail_evaluation:
            raise SpeakingEvaluationError("test model down")
        ideas = key_ideas(prompt)
        payload = {
            "ideas": [
                {
                    "idea_id": idea["idea_id"],
                    "present": index < self.present,
                    "evidence": "distance is the whole path"
                    if index < self.present
                    else "",
                }
                for index, idea in enumerate(ideas)
            ],
            "feedback": {
                "what_went_well": "You named distance clearly.",
                "next_step": "Add why a round trip has zero displacement.",
            },
        }
        return parse_evaluation(
            json.dumps(payload), prompt=prompt, model="test-model", mock=self.mock_mode
        )


class SpeakingBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.cfg = BackendConfig(
            db_url="sqlite:///:memory:",
            env="test",
            runs_dir=str(Path(self._tmp.name) / "runs"),
            cold_staging_dir=str(Path(self._tmp.name) / "cold"),
            auth_cookie_secure=True,
            auth_login_per_min=20,
            auth_register_per_min=20,
            rate_limit_api_per_min=200,
        )
        self.app = create_app(self.cfg)
        self.client = TestClient(self.app, base_url="https://testserver")
        self.db = self.app.state.db
        importer.import_packs(self.db, PACKS_DIR)
        self.session = self.register()
        self.csrf = str(self.session["csrf_token"])
        self.device = str(uuid.uuid4())
        self.pipeline = FakePipeline()
        self.app.state.speaking = self.pipeline
        self.grant_consent(self.device)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- helpers ------------------------------------------------------------

    def register(
        self, email: str = "kid@example.com", client: TestClient | None = None
    ) -> dict[str, Any]:
        target = client or self.client
        response = target.post(
            "/v1/auth/register",
            json={
                "email": email,
                "password": PASSWORD,
                "display_name": "Asha",
                "class_level": 9,
                "language": "en-IN",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return target.get("/v1/auth/session").json()

    def grant_consent(self, device: str) -> None:
        response = self.client.put(
            "/v1/consent",
            json={
                "device_pseudo_id": device,
                "consent_version": CONSENT_VERSION,
                "notice_version": self.cfg.current_notice_version,
                "guardian_flag": True,
                "action": "granted",
                "source": "overlay",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)

    def post_attempt(
        self,
        *,
        prompt_id: str = PROMPT_ID,
        language: str = "en",
        audio: bytes | None = None,
        device: str | None = None,
        headers: dict[str, str] | None = None,
        client: TestClient | None = None,
    ):
        target = client or self.client
        merged = {
            "Content-Type": "audio/wav",
            "X-CSRF-Token": self.csrf,
            "X-Device-Id": device or self.device,
        }
        if headers:
            merged.update(headers)
        return target.post(
            "/v1/speaking/attempts",
            params={"prompt_id": prompt_id, "language": language},
            content=wav_bytes() if audio is None else audio,
            headers=merged,
        )

    def page(self, path: str, client: TestClient | None = None) -> str:
        response = (client or self.client).get(path)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("text/html", response.headers["content-type"])
        return response.text


class SpeakingPromptApiTests(SpeakingBase):
    def test_prompts_require_a_signed_in_student(self) -> None:
        guest = TestClient(self.app, base_url="https://testserver")
        response = guest.get("/v1/speaking/prompts", params={"language": "en"})
        self.assertEqual(response.status_code, 401)

    def test_prompts_are_served_without_answer_material(self) -> None:
        response = self.client.get(
            "/v1/speaking/prompts", params={"chapter": CHAPTER, "language": "en"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["count"], 3)
        for item in payload["items"]:
            self.assertNotIn("key_ideas", item)
            self.assertNotIn("model_answer", item)
            self.assertGreaterEqual(item["key_idea_count"], 3)
            self.assertTrue(item["rubric"])

    def test_invalid_language_is_a_coded_422(self) -> None:
        response = self.client.get("/v1/speaking/prompts", params={"language": "fr"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "E-LANGUAGE-INVALID")


class SpeakingAttemptApiTests(SpeakingBase):
    def test_attempt_requires_consent_before_any_audio_moves(self) -> None:
        response = self.post_attempt(device=str(uuid.uuid4()))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "E-CONSENT-REQUIRED")
        self.assertEqual(self.pipeline.calls, [])

    def test_stale_consent_is_rejected(self) -> None:
        stale_device = str(uuid.uuid4())
        self.client.put(
            "/v1/consent",
            json={
                "device_pseudo_id": stale_device,
                "consent_version": CONSENT_VERSION,
                "notice_version": "zivon-voice-notice-v0-old",
                "guardian_flag": True,
                "action": "granted",
                "source": "overlay",
            },
        )
        response = self.post_attempt(device=stale_device)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "E-CONSENT-STALE")

    def test_a_device_header_is_required(self) -> None:
        response = self.client.post(
            "/v1/speaking/attempts",
            params={"prompt_id": PROMPT_ID, "language": "en"},
            content=wav_bytes(),
            headers={"Content-Type": "audio/wav", "X-CSRF-Token": self.csrf},
        )
        self.assertEqual(response.status_code, 422)

    def test_csrf_is_required_for_an_attempt(self) -> None:
        response = self.client.post(
            "/v1/speaking/attempts",
            params={"prompt_id": PROMPT_ID, "language": "en"},
            content=wav_bytes(),
            headers={
                "Content-Type": "audio/wav",
                "X-Device-Id": self.device,
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "E-AUTH-CSRF")

    def test_attempt_saves_text_only_and_returns_rubric(self) -> None:
        response = self.post_attempt()
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertFalse(payload["mock"])
        self.assertIsNone(payload["evaluation_error"])
        attempt = payload["attempt"]
        self.assertEqual(attempt["transcript"], self.pipeline.transcript)
        self.assertEqual(attempt["prompt_id"], PROMPT_ID)
        self.assertEqual(attempt["duration_ms"], 2000)
        self.assertGreater(attempt["score"], 0)
        evaluation = payload["evaluation"]
        self.assertEqual(evaluation["ideas_total"], 4)
        self.assertEqual(evaluation["ideas_present"], 3)
        self.assertEqual(evaluation["band"], "pass")
        self.assertEqual(evaluation["band_label"], "Clear explanation")
        self.assertEqual(len(evaluation["key_ideas"]), 4)
        self.assertTrue(any(row["present"] for row in evaluation["key_ideas"]))
        self.assertTrue(payload["prompt"]["model_answer"])
        # The persisted row is text + bounded JSON; the schema has no audio
        # column at all (privacy is structural, not a promise).
        columns = {
            str(row["name"])
            for row in self.db.fetchall("PRAGMA table_info(speaking_attempt)")
        }
        self.assertNotIn("audio", columns)
        self.assertNotIn("audio_blob", columns)
        self.assertNotIn("audio_path", columns)
        row = self.db.fetchone(
            "SELECT * FROM speaking_attempt WHERE attempt_id = ?",
            (attempt["attempt_id"],),
        )
        assert row is not None
        self.assertEqual(row["transcript"], self.pipeline.transcript)
        self.assertIn("band", row["feedback"])

    def test_no_speech_is_an_honest_retry_not_a_saved_attempt(self) -> None:
        self.app.state.speaking = FakePipeline(transcript="   ")
        response = self.post_attempt()
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "E-SPEAKING-NO-SPEECH")
        listed = self.client.get("/v1/speaking/attempts").json()
        self.assertEqual(listed["count"], 0)

    def test_evaluation_failure_keeps_the_real_transcript(self) -> None:
        self.app.state.speaking = FakePipeline(fail_evaluation=True)
        response = self.post_attempt()
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertIsNone(payload["evaluation"])
        self.assertEqual(payload["evaluation_error"]["code"], "E-SPEAKING-EVALUATION")
        self.assertIn("saved as text", payload["notice"])
        attempt = payload["attempt"]
        self.assertEqual(attempt["transcript"], FakePipeline().transcript)
        self.assertEqual(attempt["feedback"], {})
        self.assertIsNone(attempt["score"])

    def test_mock_mode_is_labelled(self) -> None:
        mock_pipeline = FakePipeline(mock=True)
        self.app.state.speaking = mock_pipeline
        response = self.post_attempt()
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["mock"])
        self.assertTrue(payload["evaluation"]["mock"])

    def test_upload_size_format_and_duration_are_bounded(self) -> None:
        oversized = b"RIFF" + b"\x00" * 3_000_001
        response = self.post_attempt(audio=oversized)
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["code"], "E-SPEAKING-AUDIO-SIZE")

        response = self.post_attempt(audio=b"not a wav")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "E-SPEAKING-AUDIO")

        response = self.post_attempt(audio=wav_bytes(seconds=61))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "E-SPEAKING-AUDIO")

        wrong_rate = wav_bytes(seconds=1, sample_rate=48000)
        response = self.post_attempt(audio=wrong_rate)
        self.assertEqual(response.status_code, 422)

    def test_quota_denial_never_calls_stt(self) -> None:
        class Denied:
            allowed = False
            reason = "global_tranche_exhausted"
            status = SimpleNamespace(global_remaining=0.0)

        class DenyingGuard:
            def check_and_reserve(self, *args: Any, **kwargs: Any) -> Denied:
                return Denied()

            def record_ledger_entry(self, **kwargs: Any) -> str:
                raise AssertionError("must not meter a refused attempt")

        self.app.state.guard = DenyingGuard()
        response = self.post_attempt()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["code"], "E-QUOTA-EXHAUSTED")
        self.assertEqual(self.pipeline.calls, [])

    def test_a_ledger_failure_does_not_lose_the_saved_attempt(self) -> None:
        class FlakyLedgerGuard:
            def check_and_reserve(self, *args: Any, **kwargs: Any) -> Any:
                return SimpleNamespace(
                    allowed=True,
                    reason="ok",
                    status=SimpleNamespace(global_remaining=999.0),
                )

            def record_ledger_entry(self, **kwargs: Any) -> str:
                raise RuntimeError("ledger down")

        self.app.state.guard = FlakyLedgerGuard()
        response = self.post_attempt()
        self.assertEqual(response.status_code, 200, response.text)
        attempt_id = response.json()["attempt"]["attempt_id"]
        self.assertEqual(
            self.client.get(f"/v1/speaking/attempts/{attempt_id}").status_code, 200
        )

    def test_unavailable_pipeline_is_503(self) -> None:
        self.app.state.speaking = FakePipeline(available=False)
        response = self.post_attempt()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "E-SPEAKING-UNAVAILABLE")

    def test_attempt_get_self_check_and_delete_are_owner_scoped(self) -> None:
        created = self.post_attempt().json()
        attempt_id = created["attempt"]["attempt_id"]

        fetched = self.client.get(f"/v1/speaking/attempts/{attempt_id}")
        self.assertEqual(fetched.status_code, 200)
        self.assertTrue(fetched.json()["prompt"]["model_answer"])

        patched = self.client.patch(
            f"/v1/speaking/attempts/{attempt_id}",
            json={"choice": "missed_a_part"},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(patched.status_code, 200, patched.text)
        self.assertEqual(
            patched.json()["attempt"]["self_check"]["choice"], "missed_a_part"
        )

        bad = self.client.patch(
            f"/v1/speaking/attempts/{attempt_id}",
            json={"choice": "free text"},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(bad.status_code, 422)

        other = TestClient(self.app, base_url="https://testserver")
        other_session = self.register("other@example.com", client=other)
        other_csrf = str(other_session["csrf_token"])
        self.assertEqual(
            other.get(f"/v1/speaking/attempts/{attempt_id}").status_code, 404
        )
        self.assertEqual(
            other.patch(
                f"/v1/speaking/attempts/{attempt_id}",
                json={"choice": "explained_fully"},
                headers={"X-CSRF-Token": other_csrf},
            ).status_code,
            404,
        )
        self.assertEqual(
            other.delete(
                f"/v1/speaking/attempts/{attempt_id}",
                headers={"X-CSRF-Token": other_csrf},
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.delete(
                f"/v1/speaking/attempts/{attempt_id}",
                headers={"X-CSRF-Token": self.csrf},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(f"/v1/speaking/attempts/{attempt_id}").status_code, 404
        )
        row = self.db.fetchone(
            "SELECT COUNT(*) AS c FROM speaking_attempt WHERE attempt_id = ?",
            (attempt_id,),
        )
        assert row is not None
        self.assertEqual(int(row["c"]), 0)


class SpeakingProxyTests(unittest.TestCase):
    def test_the_upload_location_allows_a_45_second_wav(self) -> None:
        nginx = (REPO_ROOT / "docker" / "nginx.conf").read_text(encoding="utf-8")
        marker = "location = /v1/speaking/attempts {"
        start = nginx.index(marker)
        block = nginx[start : nginx.index("}", start)]
        self.assertIn("client_max_body_size 4m;", block)
        self.assertIn("proxy_pass http://core-backend:8000;", block)
        self.assertIn("proxy_set_header X-Real-IP $remote_addr;", block)
        self.assertIn("proxy_set_header X-Forwarded-For", block)
        self.assertIn("proxy_read_timeout 90s;", block)
        # The server-level security headers are inherited, never re-declared.
        self.assertNotIn("add_header", block)
        self.assertNotIn("proxy_set_header Cookie", block)


class SpeakingPageTests(SpeakingBase):
    def test_hub_lists_chapter_prompts(self) -> None:
        html = self.page("/app/speaking")
        self.assertIn("Say it in your own words.", html)
        self.assertIn("distance and displacement", html)
        self.assertIn("4 key ideas", html)
        self.assertIn(f'href="/app/speaking/{PROMPT_ID}?language=en"', html)
        self.assertIn("How explain-back works", html)
        self.assertIn("the audio is discarded", html)

    def test_hub_is_an_honest_empty_state_without_prompts(self) -> None:
        self.db.execute("DELETE FROM speaking_prompt")
        html = self.page("/app/speaking")
        self.assertIn("No explain-back prompt is loaded for your class yet.", html)
        self.assertIn("Open the catalogue", html)
        self.assertNotIn("Start explaining", html)

    def test_recorder_withholds_key_ideas_before_an_attempt(self) -> None:
        html = self.page(f"/app/speaking/{PROMPT_ID}")
        self.assertIn("distance and displacement", html)
        self.assertIn("up to 45 seconds", html)
        self.assertIn("Voice tutor: before we start", html)
        self.assertIn("data-speaking-mic", html)
        self.assertIn("data-speaking-consent", html)
        self.assertIn("disabled", html)
        self.assertIn("00:45", html)
        # The expected answer is not in the pre-attempt HTML.
        self.assertNotIn("Distance is the total length of the path travelled.", html)
        self.assertNotIn("Distance counts every metre you actually travel", html)

    def test_recorder_shows_the_saved_result_after_an_attempt(self) -> None:
        self.assertEqual(self.post_attempt().status_code, 200)
        html = self.page(f"/app/speaking/{PROMPT_ID}")
        self.assertIn("Feedback on your explanation", html)
        self.assertIn("AI feedback", html)
        self.assertIn("Clear explanation", html)
        self.assertIn("3 of 4 key ideas covered", html)
        self.assertIn("Covered", html)
        self.assertIn("Missing", html)
        self.assertIn("Distance counts every metre you actually travel", html)
        self.assertIn("data-speaking-delete", html)
        self.assertIn("How did that feel?", html)

    def test_recorder_shows_the_unavailable_recording_state(self) -> None:
        self.app.state.speaking = FakePipeline(available=False)
        html = self.page(f"/app/speaking/{PROMPT_ID}")
        self.assertIn("Recording is not available on this deployment.", html)
        self.assertIn('data-speech-available="false"', html)

    def test_recorder_unknown_prompt_is_404_and_honest(self) -> None:
        response = self.client.get("/app/speaking/spk-missing")
        self.assertEqual(response.status_code, 404)
        self.assertIn("That prompt is not available.", response.text)
        self.assertIn("Nothing was recorded.", response.text)

    def test_history_lists_then_deletes(self) -> None:
        created = self.post_attempt().json()
        attempt_id = created["attempt"]["attempt_id"]
        html = self.page("/app/speaking/history")
        self.assertIn("Every explanation you kept.", html)
        self.assertIn("Distance is the whole path", html)
        self.assertIn("Clear explanation", html)
        self.assertIn(f'data-attempt-id="{attempt_id}"', html)
        self.assertIn("data-speaking-delete", html)

        self.client.delete(
            f"/v1/speaking/attempts/{attempt_id}",
            headers={"X-CSRF-Token": self.csrf},
        )
        empty = self.page("/app/speaking/history")
        self.assertIn("No explain-back attempt saved.", empty)

    def test_recorder_is_a11y_shaped_and_360_safe(self) -> None:
        html = self.page(f"/app/speaking/{PROMPT_ID}")
        self.assertIn('role="status"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn('aria-pressed="false"', html)
        self.assertIn('aria-hidden="true"', html)
        self.assertIn("data-speaking-wave", html)
        self.assertIn("aria-labelledby", html)
        self.assertNotIn("style=", html)
        css = (REPO_ROOT / "frontend" / "assets" / "app-speaking.css").read_text(
            encoding="utf-8"
        )
        self.assertIn("@media (max-width: 480px)", css)
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn("min-height: 44px", css)

    def test_guest_is_redirected_to_login(self) -> None:
        guest = TestClient(self.app, base_url="https://testserver")
        response = guest.get("/app/speaking", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn("/login?next=/app/speaking", response.headers["location"])


__all__ = ["FakePipeline", "SpeakingAttemptApiTests", "SpeakingPageTests", "wav_bytes"]
