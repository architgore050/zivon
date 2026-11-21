"""Transactional-email contract tests (ADR-0029).

Covers the two failure modes that matter operationally: TLS that does not
authenticate the mail server, and a dev-only sink silently selected in a
real deployment (verification/reset mail would vanish).
"""

from __future__ import annotations

import ssl
import unittest
from typing import Any, Self
from unittest import mock

from backend.auth.email import (
    DevEmailSink,
    ResendEmailSender,
    SmtpEmailSender,
    build_email_sender,
    password_reset_email,
    verification_email,
)
from backend.config import BackendConfig, BackendConfigError


class TestSmtpSender(unittest.TestCase):
    def test_starttls_verifies_the_server_certificate(self) -> None:
        captured: dict[str, Any] = {}

        class FakeSmtp:
            def __init__(self, host: str, port: int, timeout: float = 0) -> None:
                captured["endpoint"] = f"{host}:{port}"

            def __enter__(self) -> Self:
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

            def starttls(self, *, context: ssl.SSLContext | None = None) -> None:
                captured["context"] = context

            def login(self, user: str, password: str) -> None:
                captured["login"] = (user, password)

            def sendmail(self, sender: str, recipients: list[str], raw: bytes) -> None:
                captured["sender"] = sender
                captured["recipients"] = recipients
                captured["raw"] = raw

        sender = SmtpEmailSender(
            host="smtp.example.com",
            port=587,
            username="mailer",
            password="mailer-secret",
            sender="no-reply@zivon.test",
        )
        message = verification_email(
            to="kid@example.com",
            link="https://app.test/verify-email?token=abc",
            expires_hours=48,
        )
        with mock.patch("backend.auth.email.smtplib.SMTP", FakeSmtp):
            sender.send(message)

        context = captured["context"]
        self.assertIsInstance(context, ssl.SSLContext)
        if not isinstance(context, ssl.SSLContext):
            self.fail("starttls must receive an explicit verification context")
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertEqual(captured["endpoint"], "smtp.example.com:587")
        self.assertEqual(captured["recipients"], ["kid@example.com"])
        self.assertEqual(captured["sender"], "no-reply@zivon.test")


class TestResendSender(unittest.TestCase):
    """Resend HTTP adapter against a mocked http client (no network)."""

    def test_send_posts_the_bearer_token_and_message_payload(self) -> None:
        captured: dict[str, Any] = {}

        def fake_post(url: str, **kwargs: Any) -> Any:
            captured["url"] = url
            captured.update(kwargs)
            return mock.Mock(status_code=200)

        sender = ResendEmailSender(
            api_key="test-resend-key", sender="no-reply@zivon.test", http_post=fake_post
        )
        sender.send(
            password_reset_email(
                to="kid@example.com",
                link="https://app.test/reset-password?token=abc",
                expires_minutes=60,
            )
        )
        self.assertEqual(captured["url"], ResendEmailSender.ENDPOINT)
        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-resend-key")
        self.assertEqual(captured["json"]["from"], "no-reply@zivon.test")
        self.assertEqual(captured["json"]["to"], ["kid@example.com"])
        self.assertEqual(captured["json"]["subject"], "Reset your Zivon password")
        self.assertIn("reset-password?token=abc", captured["json"]["text"])
        self.assertEqual(captured["timeout"], 10.0)

    def test_send_raises_when_resend_rejects_the_message(self) -> None:
        for status in (401, 429, 500):
            with (
                self.subTest(status=status),
                self.assertRaises(RuntimeError),
            ):
                sender = ResendEmailSender(
                    api_key="test-resend-key",
                    sender="no-reply@zivon.test",
                    http_post=mock.Mock(return_value=mock.Mock(status_code=status)),
                )
                sender.send(
                    verification_email(to="kid@example.com", link="l", expires_hours=48)
                )


class TestSenderSelection(unittest.TestCase):
    def test_dev_sink_is_refused_in_cluster_and_prod(self) -> None:
        for env in ("cluster", "prod"):
            with (
                self.subTest(env=env),
                self.assertRaises(BackendConfigError),
            ):
                build_email_sender(BackendConfig(db_url="sqlite:///:memory:", env=env))

    def test_dev_sink_is_allowed_in_dev_and_test(self) -> None:
        for env in ("dev", "test"):
            with self.subTest(env=env):
                sender = build_email_sender(
                    BackendConfig(db_url="sqlite:///:memory:", env=env)
                )
                self.assertIsInstance(sender, DevEmailSink)

    def test_unknown_backend_fails_loud(self) -> None:
        config = BackendConfig(
            db_url="sqlite:///:memory:", env="dev", email_backend="carrier-pigeon"
        )
        with self.assertRaises(BackendConfigError):
            build_email_sender(config)

    def test_smtp_requires_a_host(self) -> None:
        config = BackendConfig(
            db_url="sqlite:///:memory:", env="test", email_backend="smtp"
        )
        with self.assertRaises(BackendConfigError):
            build_email_sender(config)

    def test_smtp_selection_returns_the_smtp_adapter(self) -> None:
        config = BackendConfig(
            db_url="sqlite:///:memory:",
            env="test",
            email_backend="smtp",
            smtp_host="smtp.example.com",
        )
        sender = build_email_sender(config)
        self.assertIsInstance(sender, SmtpEmailSender)

    def test_resend_requires_an_api_key(self) -> None:
        config = BackendConfig(
            db_url="sqlite:///:memory:", env="test", email_backend="resend"
        )
        with self.assertRaises(BackendConfigError):
            build_email_sender(config)

    def test_resend_selection_returns_the_resend_adapter(self) -> None:
        config = BackendConfig(
            db_url="sqlite:///:memory:",
            env="test",
            email_backend="resend",
            resend_api_key="test-resend-key",
        )
        sender = build_email_sender(config)
        self.assertIsInstance(sender, ResendEmailSender)


if __name__ == "__main__":
    unittest.main()
