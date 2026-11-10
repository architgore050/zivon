"""Weld test: the backend monolith mounts the real voice WS route (ADR-0020).

GAP-017/EX6 seam: `voice/` has no image of its own — it mounts into the core
backend. This asserts the app factory registers `/voice/ws` from
`voice.ws_api.mount_voice` (not the retired EX0 stub) and wires the
ZIVON_VOICE_* config family, without any live vendor call: mounting only
builds the endpoint + dependency objects; STT/brain/TTS clients are created
per session, never at boot.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient
from starlette.routing import WebSocketRoute

from backend import BackendConfig, create_app
from db.engine import DatabaseEngine
from voice.config import VoiceSettings
from voice.ws_api import VoiceApp


class TestVoiceMount(unittest.TestCase):
    def _app(self, *, session_token_key: str | None = None):
        cfg = BackendConfig(
            db_url="sqlite:///:memory:",
            env="dev",
            session_token_key=session_token_key or "test-session-token-key",
        )
        return create_app(cfg, db_engine=DatabaseEngine.from_url("sqlite:///:memory:"))

    def test_voice_ws_route_is_registered(self) -> None:
        app = self._app()
        paths = [getattr(route, "path", "") for route in app.routes]
        self.assertIn("/voice/ws", paths)

        ws_routes = [
            route
            for route in app.routes
            if isinstance(route, WebSocketRoute) and route.path == "/voice/ws"
        ]
        self.assertEqual(len(ws_routes), 1)
        self.assertIsInstance(app.state.voice, VoiceApp)

    def test_voice_reads_zivon_voice_env_and_backend_auth_secret(self) -> None:
        env = {
            "ZIVON_VOICE_BRAIN_MODEL": "smoke-model",
            "ZIVON_VOICE_TTS_VOICE": "tutor-voice",
            "ZIVON_VOICE_CREDIT_PER_USER_CAP": "7",
            # No ZIVON_SESSION_TOKEN_KEY: the backend's config is the source.
        }
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("ZIVON_SESSION_TOKEN_KEY", None)
            app = self._app(session_token_key="backend-owned-session-key")

        settings = app.state.voice.settings  # type: ignore[attr-defined]
        self.assertIsInstance(settings, VoiceSettings)
        self.assertEqual(settings.brain_model, "smoke-model")
        self.assertEqual(settings.tts_voice, "tutor-voice")
        self.assertEqual(settings.credit_per_user_cap, 7)
        self.assertEqual(settings.session_token_key, "backend-owned-session-key")
        self.assertEqual(settings.ws_path, "/voice/ws")

    def test_healthz_stays_up_when_the_database_is_unreachable(self) -> None:
        """Liveness must not depend on Postgres (CI's dead-DSN smoke contract)."""
        app = create_app(
            BackendConfig(
                db_url="postgresql://zivon:smoke@127.0.0.1:9/zivon", env="dev"
            )
        )
        client = TestClient(app)
        live = client.get("/healthz")
        self.assertEqual(live.status_code, 200)
        self.assertTrue(live.json()["ok"])

        ready = client.get("/readyz")
        self.assertEqual(ready.status_code, 503)
        self.assertEqual(ready.json()["db"], "boot_failed")


if __name__ == "__main__":
    unittest.main()
