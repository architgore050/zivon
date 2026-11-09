"""Tests for the Timbre v3.0 clients (mock + live retry discipline).

The live client is exercised against httpx.MockTransport - no network, no
keys; the retry/backoff discipline mirrors llm_manager's contract.
"""

from __future__ import annotations

import dataclasses
import io
import os
import unittest
import wave
from typing import Any

import httpx

from factory.narration.env import NarrationEnv
from factory.narration.errors import NarrationError
from factory.narration.timbre import (
    MOCK_CHARS_PER_SEC,
    MOCK_SAMPLE_RATE,
    LiveTimbreClient,
    MockTimbreClient,
    _silence_wav,
)


def _env(extra: dict[str, Any] | None = None) -> NarrationEnv:
    """A NarrationEnv built directly (bypassing os.environ) for client tests."""
    base = NarrationEnv(
        enabled=True,
        mode="live",
        langs=("en",),
        budget_credits=1500.0,
        repair_rounds=2,
        timbre_base_url="https://timbre.example.test",
        timbre_api_key="secret-key-do-not-leak",
        timbre_tts_path="/v1/tts",
        timbre_voice="",
        credits_per_char=1500.0 / 90000.0,
        timbre_timeout_s=30.0,
        timbre_connect_timeout_s=5.0,
        timbre_max_attempts=3,
        timbre_backoff_base_s=0.0,
        coldstore_upload_cmd=None,
        coldstore_readback_cmd=None,
        coldstore_prefix="narration",
        coldstore_timeout_s=60.0,
    )
    if extra:
        return dataclasses.replace(base, **extra)
    return base


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


class TestMockTimbreClient(unittest.TestCase):
    def test_deterministic_and_sized_by_chars(self):
        client = MockTimbreClient()
        first = client.synthesize("a" * 140, "en-IN")  # 140/14 = 10 s
        second = client.synthesize("a" * 140, "en-IN")
        self.assertEqual(first.audio, second.audio)
        with wave.open(io.BytesIO(first.audio), "rb") as wav:
            self.assertEqual(wav.getframerate(), MOCK_SAMPLE_RATE)
            self.assertEqual(wav.getnchannels(), 1)
            self.assertAlmostEqual(
                wav.getnframes() / wav.getframerate(), 10.0, delta=0.01
            )

    def test_short_text_still_one_second_long(self):
        with wave.open(
            io.BytesIO(MockTimbreClient().synthesize("hi", "en-IN").audio), "rb"
        ) as wav:
            self.assertGreaterEqual(wav.getnframes() / wav.getframerate(), 1.0)

    def test_long_text_capped(self):
        with wave.open(
            io.BytesIO(MockTimbreClient().synthesize("a" * 100000, "en-IN").audio), "rb"
        ) as wav:
            self.assertLessEqual(wav.getnframes() / wav.getframerate(), 45.5)

    def test_silence_helper_is_valid_wav(self):
        raw = _silence_wav(2.0)
        with wave.open(io.BytesIO(raw), "rb") as wav:
            self.assertEqual(wav.getnframes(), 2 * MOCK_SAMPLE_RATE)
        self.assertGreater(len(raw), 0)  # non-empty


class TestLiveTimbreClientRetries(unittest.TestCase):
    def test_success_after_429_then_200(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(429)
            self.assertEqual(request.url, "https://timbre.example.test/v1/tts")
            self.assertEqual(
                request.headers["Authorization"], "Bearer secret-key-do-not-leak"
            )
            return httpx.Response(200, content=b"OggS-audio")

        result = LiveTimbreClient(_env(), transport=_transport(handler)).synthesize(
            "hello", "en-IN"
        )
        self.assertEqual(result.audio, b"OggS-audio")
        self.assertEqual(result.attempts, 2)
        self.assertEqual(calls["n"], 2)

    def test_retryable_5xx_then_success(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] < 3:
                return httpx.Response(503)
            return httpx.Response(200, content=b"audio")

        result = LiveTimbreClient(_env(), transport=_transport(handler)).synthesize(
            "hello", "en-IN"
        )
        self.assertEqual(result.attempts, 3)

    def test_non_retryable_4xx_raises_immediately(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(401)

        with self.assertRaises(NarrationError) as ctx:
            LiveTimbreClient(_env(), transport=_transport(handler)).synthesize(
                "hello", "en-IN"
            )
        self.assertEqual(calls["n"], 1)  # no retry on a permanent rejection
        # The key and body never leak into the error message.
        message = str(ctx.exception)
        self.assertNotIn("secret-key-do-not-leak", message)
        self.assertNotIn("hello", message)

    def test_transport_error_retries_then_raises(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            raise httpx.ConnectTimeout("boom")

        with self.assertRaises(NarrationError) as ctx:
            LiveTimbreClient(_env(), transport=_transport(handler)).synthesize(
                "hello", "en-IN"
            )
        self.assertEqual(calls["n"], _env().timbre_max_attempts)
        self.assertIn("transport error", str(ctx.exception))

    def test_all_attempts_exhausted_on_429(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429)

        with self.assertRaises(NarrationError) as ctx:
            LiveTimbreClient(_env(), transport=_transport(handler)).synthesize(
                "hello", "en-IN"
            )
        self.assertIn("3 attempt(s)", str(ctx.exception))

    def test_request_carries_language_and_format(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["json"] = request.read()
            return httpx.Response(200, content=b"a")

        LiveTimbreClient(
            _env(extra={"timbre_voice": "en-IN-female"}), transport=_transport(handler)
        ).synthesize("hello", "en-IN")
        import json

        body = json.loads(captured["json"])
        self.assertEqual(body["language"], "en-IN")
        self.assertEqual(body["voice"], "en-IN-female")
        self.assertEqual(body["format"], "ogg-opus")
        self.assertNotIn("api_key", body)

    def test_live_mode_without_base_url_is_a_config_error(self):
        from factory.errors import ConfigError

        with self.assertRaises(ConfigError):
            LiveTimbreClient(_env(extra={"timbre_base_url": None}))


class TestEnvParsing(unittest.TestCase):
    def test_from_env_reads_and_restores(self):
        saved = {}
        overrides = {
            "ZIVON_NARRATION_ENABLED": "true",
            "ZIVON_TIMBRE_BASE_URL": "https://timbre.example.test",
            "ZIVON_TIMBRE_API_KEY": "k",
            "ZIVON_TIMBRE_MAX_ATTEMPTS": "2",
            "ZIVON_TIMBRE_BACKOFF_BASE_S": "0",
        }
        for key, value in overrides.items():
            saved[key] = os.environ.get(key)
            os.environ[key] = value
        try:
            env = NarrationEnv.from_env()
            self.assertTrue(env.enabled)
            self.assertEqual(env.resolved_mode, "live")
            self.assertEqual(env.timbre_max_attempts, 2)
            self.assertEqual(env.tts_language("en"), "en-IN")
            self.assertEqual(env.tts_language("hinglish"), "hi-IN")
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_default_mode_is_mock_when_no_endpoint(self):
        saved = {
            k: os.environ.pop(k, None)
            for k in list(os.environ)
            if k.startswith(("ZIVON_TIMBRE", "ZIVON_NARRATION"))
        }
        try:
            env = NarrationEnv.from_env()
            self.assertEqual(env.resolved_mode, "mock")
        finally:
            for key, value in saved.items():
                if value is not None:
                    os.environ[key] = value

    def test_bad_mode_is_a_config_error(self):
        saved = {
            k: os.environ.get(k)
            for k in ("ZIVON_NARRATION_ENABLED", "ZIVON_NARRATION_MODE")
        }
        os.environ["ZIVON_NARRATION_ENABLED"] = "true"
        os.environ["ZIVON_NARRATION_MODE"] = "yolo"
        try:
            from factory.errors import ConfigError

            with self.assertRaises(ConfigError):
                NarrationEnv.from_env()
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_mock_chars_per_sec_is_plausible_speech(self):
        # Guard the mock's realism assumption: 14 chars/s ~ measured
        # narration pace; if someone changes it, change the comment too.
        self.assertTrue(10 <= MOCK_CHARS_PER_SEC <= 20)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
