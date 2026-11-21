"""HttpxGoogleTransport contract tests (ADR-0029, mocked httpx — no network).

The production transport is the only Google seam without a fake in
`test_auth.py` (that suite injects `FakeGoogleTransport` at the client). Here
the real transport runs against a mocked `httpx.post`/`httpx.get`, pinning the
error mapping the callback route relies on: a network failure is
`E-SERVICE-UNAVAILABLE` (503), a Google rejection is `E-AUTH-INVALID` (400),
and an unparseable payload is never trusted.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest import mock

import httpx

from backend.auth.google import GoogleAuthError, HttpxGoogleTransport


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: Any = None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        if self._payload is ...:
            raise ValueError("not JSON")
        return self._payload


class TestHttpxGoogleTransport(unittest.TestCase):
    def setUp(self) -> None:
        self.transport = HttpxGoogleTransport()

    def test_post_form_returns_the_token_payload(self) -> None:
        captured: dict[str, Any] = {}

        def fake_post(url: str, **kwargs: Any) -> FakeResponse:
            captured["url"] = url
            captured["kwargs"] = kwargs
            return FakeResponse(200, {"access_token": "t", "token_type": "Bearer"})

        with mock.patch("httpx.post", fake_post):
            payload = self.transport.post_form(
                "https://oauth2.googleapis.com/token",
                {"code": "c", "code_verifier": "v"},
                timeout_s=10.0,
            )
        self.assertEqual(payload["access_token"], "t")
        self.assertEqual(captured["url"], "https://oauth2.googleapis.com/token")
        self.assertEqual(
            captured["kwargs"]["data"], {"code": "c", "code_verifier": "v"}
        )
        self.assertEqual(captured["kwargs"]["timeout"], 10.0)

    def test_post_form_maps_a_transport_failure_to_service_unavailable(self) -> None:
        with (
            mock.patch("httpx.post", side_effect=httpx.ConnectError("down")),
            self.assertRaises(GoogleAuthError) as raised,
        ):
            self.transport.post_form(
                "https://oauth2.googleapis.com/token", {}, timeout_s=1.0
            )
        self.assertEqual(raised.exception.code, "E-SERVICE-UNAVAILABLE")

    def test_post_form_maps_a_google_rejection_to_auth_invalid(self) -> None:
        with (
            mock.patch("httpx.post", return_value=FakeResponse(400, {"error": "x"})),
            self.assertRaises(GoogleAuthError) as raised,
        ):
            self.transport.post_form(
                "https://oauth2.googleapis.com/token", {}, timeout_s=1.0
            )
        self.assertEqual(raised.exception.code, "E-AUTH-INVALID")

    def test_post_form_refuses_an_unparseable_or_non_object_payload(self) -> None:
        for payload in (..., ["not", "an", "object"], "string"):
            with (
                self.subTest(payload="unparseable" if payload is ... else payload),
                mock.patch("httpx.post", return_value=FakeResponse(200, payload)),
                self.assertRaises(GoogleAuthError) as raised,
            ):
                self.transport.post_form(
                    "https://oauth2.googleapis.com/token", {}, timeout_s=1.0
                )
            self.assertEqual(raised.exception.code, "E-SERVICE-UNAVAILABLE")

    def test_get_json_sends_the_bearer_header_and_returns_the_profile(self) -> None:
        captured: dict[str, Any] = {}

        def fake_get(url: str, **kwargs: Any) -> FakeResponse:
            captured["url"] = url
            captured["kwargs"] = kwargs
            return FakeResponse(200, {"sub": "s", "email": "kid@example.com"})

        with mock.patch("httpx.get", fake_get):
            profile = self.transport.get_json(
                "https://openidconnect.googleapis.com/v1/userinfo",
                {"Authorization": "Bearer t"},
                timeout_s=10.0,
            )
        self.assertEqual(profile["sub"], "s")
        self.assertEqual(captured["kwargs"]["headers"], {"Authorization": "Bearer t"})
        self.assertEqual(captured["kwargs"]["timeout"], 10.0)

    def test_get_json_maps_failures_like_post_form(self) -> None:
        def http_401(*_args: Any, **_kwargs: Any) -> FakeResponse:
            return FakeResponse(401, {})

        def bad_json(*_args: Any, **_kwargs: Any) -> FakeResponse:
            return FakeResponse(200, ...)

        cases: tuple[tuple[str, Any, str], ...] = (
            ("transport-error", httpx.ConnectError("down"), "E-SERVICE-UNAVAILABLE"),
            ("http-401", http_401, "E-AUTH-INVALID"),
            ("bad-json", bad_json, "E-SERVICE-UNAVAILABLE"),
        )
        for name, side_effect, expected_code in cases:
            with (
                self.subTest(case=name),
                mock.patch("httpx.get", side_effect=side_effect),
                self.assertRaises(GoogleAuthError) as raised,
            ):
                self.transport.get_json(
                    "https://openidconnect.googleapis.com/v1/userinfo",
                    {},
                    timeout_s=1.0,
                )
            self.assertEqual(raised.exception.code, expected_code)


if __name__ == "__main__":
    unittest.main()
