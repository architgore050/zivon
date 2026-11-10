"""Tests for the ST-04 nginx route in docker/nginx.conf.

Contract-level assertions (the testing/frontend harness pattern for config
files): the route exists, is immutable-cached, is rate-limited per IP, and
serves opus with the right content type. Behavioural serving is verified in
compose (`docker compose up web` + a HEAD /audio/... - runbook), not here:
no nginx binary in CI, and the conf's structure is what this repo owns.
"""

from __future__ import annotations

import unittest
from pathlib import Path

CONF = Path(__file__).resolve().parents[2] / "docker" / "nginx.conf"


def _block(text: str, header: str) -> str:
    """Return the {...} body of the first block whose header precedes it."""
    start = text.find(header)
    if start == -1:
        return ""
    open_brace = text.find("{", start)
    depth = 0
    for i in range(open_brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace + 1 : i]
    return ""


class TestNginxSt04Route(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conf = CONF.read_text(encoding="utf-8")

    def test_audio_location_exists(self):
        self.assertIn("location /audio/", self.conf)

    def test_immutable_cache_policy_for_audio_uris(self):
        # ST-04: immutable, max-age=31536000 - the content-hash path is the
        # cache key, so a year-long immutable store is correct by design.
        self.assertRegex(
            self.conf,
            r'"~\^/audio/"\s+"public, max-age=31536000, immutable"',
        )

    def test_per_ip_rate_limit_zone_and_use(self):
        self.assertRegex(
            self.conf,
            r"limit_req_zone \$binary_remote_addr zone=zivon_audio:\d+m rate=\d+r/m;",
        )
        body = _block(self.conf, "location /audio/")
        self.assertRegex(body, r"limit_req\s+zone=zivon_audio\s+burst=\d+\s+nodelay;")

    def test_opus_content_type(self):
        body = _block(self.conf, "location /audio/")
        self.assertIn("audio/opus opus;", body)
        self.assertIn("default_type audio/opus;", body)

    def test_location_inherits_server_headers_no_add_header(self):
        # nginx stops inheriting the server-level add_header set the moment a
        # location declares its own: the audio location must declare NONE so
        # CSP/nosniff/referrer/Cache-Control keep applying.
        body = _block(self.conf, "location /audio/")
        self.assertNotIn("add_header", body)

    def test_route_is_matched_before_directory_fallback(self):
        audio = self.conf.find("location /audio/")
        generic = self.conf.find("location / {")
        self.assertGreater(audio, 0)
        self.assertGreater(generic, audio)

    def test_st04_path_shape_documented_in_conf(self):
        # Keep the served contract visible where operators edit it.
        self.assertIn("{block_id}.{lang}.{content-hash}.opus", self.conf)


class TestNginxConfStillServesTheShell(unittest.TestCase):
    """Guard the pre-existing contracts while touching the shared file."""

    @classmethod
    def setUpClass(cls):
        cls.conf = CONF.read_text(encoding="utf-8")

    def test_html_and_courses_js_stay_uncached(self):
        self.assertIn('"~*\\.html$"', self.conf)
        self.assertIn('"= /courses.js"', self.conf)

    def test_healthz_probe_survives(self):
        self.assertIn("location = /healthz", self.conf)

    def test_balanced_braces(self):
        self.assertEqual(self.conf.count("{"), self.conf.count("}"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
