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
    SmtpEmailSender,
    build_email_sender,
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


if __name__ == "__main__":
    unittest.main()
