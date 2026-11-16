"""Outbound transactional email: dev sink, SMTP, and Resend adapters (ADR-0029).

Tests and local dev use `DevEmailSink` — it never touches the network, keeps the
messages in memory for the test suite, and can mirror them to a local directory.
Production picks SMTP or Resend from configuration. Tokens are intentionally
never logged; the sink exposes them only to in-process code (tests).
"""

from __future__ import annotations

import dataclasses
import datetime
import logging
import os
import smtplib
import ssl
import threading
from pathlib import Path
from typing import Any, Final, Protocol

from ..config import BackendConfig, BackendConfigError

logger = logging.getLogger(__name__)

SUPPORTED_BACKENDS: Final[frozenset[str]] = frozenset({"dev", "smtp", "resend"})


@dataclasses.dataclass(frozen=True)
class OutboundEmail:
    """One queued/sent message. `kind` is `verify` or `reset`."""

    to: str
    subject: str
    body: str
    kind: str
    created_at: str


class EmailSender(Protocol):
    def send(self, message: OutboundEmail) -> None: ...


def _utc_now_iso() -> str:
    now = datetime.datetime.now(datetime.UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class DevEmailSink:
    """In-memory outbox for dev/test. Optionally mirrors messages to disk."""

    MAX_MESSAGES: Final[int] = 200

    def __init__(self, directory: str | None = None) -> None:
        self._lock = threading.Lock()
        self._messages: list[OutboundEmail] = []
        self._directory = Path(directory) if directory else None
        if self._directory is not None:
            self._directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def send(self, message: OutboundEmail) -> None:
        with self._lock:
            self._messages.append(message)
            if len(self._messages) > self.MAX_MESSAGES:
                del self._messages[: len(self._messages) - self.MAX_MESSAGES]
            if self._directory is not None:
                path = self._directory / f"{message.kind}-{len(self._messages)}.txt"
                path.write_text(
                    f"To: {message.to}\nSubject: {message.subject}\n\n{message.body}\n",
                    encoding="utf-8",
                )
                os.chmod(path, 0o600)
        logger.info("dev email sink: queued %s message", message.kind)

    def messages(self, kind: str | None = None) -> list[OutboundEmail]:
        with self._lock:
            if kind is None:
                return list(self._messages)
            return [m for m in self._messages if m.kind == kind]

    def last(self, kind: str) -> OutboundEmail | None:
        found = self.messages(kind)
        return found[-1] if found else None

    def clear(self) -> None:
        with self._lock:
            self._messages.clear()


class SmtpEmailSender:
    """STARTTLS SMTP sender. Configuration is env-only (secrets runtime-only)."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        sender: str,
        starttls: bool = True,
        timeout_s: float = 10.0,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.sender = sender
        self.starttls = starttls
        self.timeout_s = timeout_s

    def send(self, message: OutboundEmail) -> None:
        raw = (
            f"From: {self.sender}\r\n"
            f"To: {message.to}\r\n"
            f"Subject: {message.subject}\r\n"
            "MIME-Version: 1.0\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            "\r\n"
            f"{message.body}\r\n"
        )
        with smtplib.SMTP(self.host, self.port, timeout=self.timeout_s) as smtp:
            if self.starttls:
                # smtplib's default context is `_create_stdlib_context()`
                # (CERT_NONE, no hostname check), which would hand SMTP
                # credentials and reset/verification links to any MITM.
                smtp.starttls(context=ssl.create_default_context())
            if self.username and self.password:
                smtp.login(self.username, self.password)
            smtp.sendmail(self.sender, [message.to], raw.encode("utf-8"))
        logger.info("smtp email sent (%s)", message.kind)


class ResendEmailSender:
    """Resend HTTP API adapter (HTTPS, bearer token, 10 s timeout)."""

    ENDPOINT: Final[str] = "https://api.resend.com/emails"

    def __init__(
        self,
        *,
        api_key: str,
        sender: str,
        http_post: Any | None = None,
        timeout_s: float = 10.0,
    ) -> None:
        self.api_key = api_key
        self.sender = sender
        self.timeout_s = timeout_s
        self._http_post = http_post or self._post

    @staticmethod
    def _post(
        url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: float
    ) -> Any:
        import httpx  # local import: the dev path never needs the HTTP stack

        return httpx.post(url, headers=headers, json=json, timeout=timeout)

    def send(self, message: OutboundEmail) -> None:
        response = self._http_post(
            self.ENDPOINT,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": self.sender,
                "to": [message.to],
                "subject": message.subject,
                "text": message.body,
            },
            timeout=self.timeout_s,
        )
        status = getattr(response, "status_code", 200)
        if status >= 400:
            raise RuntimeError(f"resend rejected the message (status {status})")
        logger.info("resend email sent (%s)", message.kind)


def build_email_sender(config: BackendConfig) -> EmailSender:
    """Select the configured adapter. Fails loud instead of silently dropping mail."""
    backend = config.email_backend.strip().lower()
    if backend not in SUPPORTED_BACKENDS:
        raise BackendConfigError(f"unsupported ZIVON_EMAIL_BACKEND '{backend}'")
    if backend == "dev" and config.env.strip().lower() in ("cluster", "prod"):
        # The in-memory sink would accept and discard verification/reset mail;
        # fail loud (auth then answers 503) instead of a silent mail black hole.
        raise BackendConfigError(
            "ZIVON_EMAIL_BACKEND=dev is not allowed in cluster/prod; "
            "configure smtp or resend"
        )
    if backend == "dev":
        return DevEmailSink(config.dev_email_dir)
    if backend == "smtp":
        if not config.smtp_host:
            raise BackendConfigError("ZIVON_SMTP_HOST is required for the smtp backend")
        return SmtpEmailSender(
            host=config.smtp_host,
            port=config.smtp_port,
            username=config.smtp_user,
            password=config.smtp_password,
            sender=config.email_from,
            starttls=config.smtp_starttls,
        )
    if not config.resend_api_key:
        raise BackendConfigError(
            "ZIVON_RESEND_API_KEY is required for the resend backend"
        )
    return ResendEmailSender(api_key=config.resend_api_key, sender=config.email_from)


def verification_email(*, to: str, link: str, expires_hours: int) -> OutboundEmail:
    return OutboundEmail(
        to=to,
        subject="Verify your Zivon email",
        body=(
            "Welcome to Zivon.\n\n"
            f"Confirm your email address: {link}\n\n"
            f"This link expires in {expires_hours} hours. If you did not create "
            "a Zivon account, you can ignore this message."
        ),
        kind="verify",
        created_at=_utc_now_iso(),
    )


def password_reset_email(*, to: str, link: str, expires_minutes: int) -> OutboundEmail:
    return OutboundEmail(
        to=to,
        subject="Reset your Zivon password",
        body=(
            "We received a request to reset your Zivon password.\n\n"
            f"Choose a new password: {link}\n\n"
            f"This link expires in {expires_minutes} minutes and works once. "
            "If you did not ask for a reset, no action is needed."
        ),
        kind="reset",
        created_at=_utc_now_iso(),
    )
