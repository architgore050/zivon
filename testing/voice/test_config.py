"""Unit tests for voice.config — env parsing, secret fallbacks, honest flags."""

from __future__ import annotations

import unittest

from voice.config import VoiceSettings


class VoiceSettingsTest(unittest.TestCase):
    def test_defaults_are_spec_defaults(self) -> None:
        s = VoiceSettings()
        self.assertEqual(s.brain_model, "gemma-4-26b-a4b-it")
        self.assertEqual(s.brain_transport, "gemini-direct")
        self.assertEqual(s.brain_inactivity_s, 4.0)
        self.assertEqual(s.brain_first_event_s, 3.0)
        self.assertEqual(s.brain_turn_deadline_s, 45.0)
        self.assertEqual(s.brain_max_retries, 2)
        self.assertFalse(s.thinking_summaries)  # ADR-0018: off until falsification
        self.assertEqual(s.filler_silence_ms, 2000)
        self.assertEqual(s.credit_daily_tranche, 1000)  # founder config
        self.assertEqual(s.credit_per_user_cap, 30)
        # OQ-06 placeholder unit: 1 point = 30 s STT = 300 TTS chars
        self.assertEqual(s.credit_stt_seconds_per_point, 30)
        self.assertEqual(s.credit_tts_chars_per_point, 300)
        self.assertEqual(s.ws_allowed_origins, ())  # same-origin default
        self.assertEqual(s.ws_trusted_proxies, ())
        self.assertEqual(s.tts_char_cap_turn, 1200)
        self.assertEqual(s.ws_path, "/voice/ws")

    def test_from_env_reads_knobs(self) -> None:
        s = VoiceSettings.from_env(
            {
                "ZIVON_VOICE_BRAIN_MODEL": "other-model",
                "ZIVON_VOICE_BRAIN_TRANSPORT": "openrouter",
                "ZIVON_VOICE_BRAIN_INACTIVITY_S": "2.5",
                "ZIVON_VOICE_THINKING_SUMMARIES": "on",
                "ZIVON_VOICE_STT_URL": "wss://prisma.example/stream",
                "ZIVON_VOICE_CREDIT_PER_USER_CAP": "12",
                "ZIVON_VOICE_MOCK": "1",
            }
        )
        self.assertEqual(s.brain_model, "other-model")
        self.assertEqual(s.brain_transport, "openrouter")
        self.assertEqual(s.brain_inactivity_s, 2.5)
        self.assertTrue(s.thinking_summaries)
        self.assertEqual(s.credit_per_user_cap, 12)
        self.assertTrue(s.mock_mode)

    def test_env_parses_origin_and_proxy_lists(self) -> None:
        s = VoiceSettings.from_env(
            {
                "ZIVON_VOICE_WS_ALLOWED_ORIGINS": "https://zivon.example, https://www.zivon.example",
                "ZIVON_VOICE_WS_TRUSTED_PROXIES": "10.0.0.0/8,192.168.0.0/16",
                "ZIVON_VOICE_WS_CONNECTS_PER_MIN": "4",
                "ZIVON_VOICE_CREDIT_TTS_CHARS_PER_POINT": "50",
            }
        )
        self.assertEqual(
            s.ws_allowed_origins,
            ("https://zivon.example", "https://www.zivon.example"),
        )
        self.assertEqual(s.ws_trusted_proxies, ("10.0.0.0/8", "192.168.0.0/16"))
        self.assertEqual(s.ws_connects_per_min, 4)
        self.assertEqual(s.credit_tts_chars_per_point, 50)

    def test_bad_transport_and_numbers_fall_back_to_defaults(self) -> None:
        s = VoiceSettings.from_env(
            {
                "ZIVON_VOICE_BRAIN_TRANSPORT": " carrier-pigeon ",
                "ZIVON_VOICE_BRAIN_INACTIVITY_S": "not-a-number",
            }
        )
        self.assertEqual(s.brain_transport, "gemini-direct")
        self.assertEqual(s.brain_inactivity_s, 4.0)

    def test_secret_fallback_names_gap_register_first(self) -> None:
        s = VoiceSettings.from_env(
            {
                "ZIVON_VOICE_GEMINI_API_KEY": "gemini-gap-registry",
                "GNANI_PRISMA_API_KEY": "prisma-key",
                "GNANI_TIMBRE_API_KEY": "timbre-key",
            }
        )
        self.assertEqual(s.gemini_api_key, "gemini-gap-registry")
        self.assertEqual(s.gnani_stt_api_key, "prisma-key")
        self.assertEqual(s.gnani_tts_api_key, "timbre-key")

    def test_spec_short_secret_names_accepted_as_fallback(self) -> None:
        s = VoiceSettings.from_env({"GEMINI_API_KEY": "g", "GNANI_API_KEY": "n"})
        self.assertEqual(s.gemini_api_key, "g")
        self.assertEqual(s.gnani_stt_api_key, "n")
        self.assertEqual(s.gnani_tts_api_key, "n")

    def test_configured_flags_require_url_and_key(self) -> None:
        unconfigured = VoiceSettings()
        self.assertFalse(unconfigured.stt_configured)
        self.assertFalse(unconfigured.tts_configured)
        configured = VoiceSettings(
            stt_url="wss://x",
            gnani_stt_api_key="k",
            tts_url="wss://y",
            gnani_tts_api_key="k",
        )
        self.assertTrue(configured.stt_configured)
        self.assertTrue(configured.tts_configured)

    def test_brain_configured_per_transport(self) -> None:
        self.assertFalse(VoiceSettings().brain_configured)
        self.assertTrue(VoiceSettings(mock_mode=True).brain_configured)
        self.assertTrue(
            VoiceSettings(
                brain_transport="openrouter", openrouter_api_key="k"
            ).brain_configured
        )
        self.assertFalse(VoiceSettings(brain_transport="openrouter").brain_configured)

    def test_secrets_do_not_render_in_repr(self) -> None:
        s = VoiceSettings(gemini_api_key="super-secret", session_token_key="tok")
        self.assertNotIn("super-secret", repr(s))
        self.assertNotIn("tok", repr(s))


if __name__ == "__main__":
    unittest.main()
