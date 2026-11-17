"""Account, session, and profile service (ADR-0029, REQUIREMENTS §6, §9).

Security properties this module owns (the routes only translate HTTP):
- Argon2id password hashes with a per-user salt; no plaintext password is ever
  stored, logged, or returned.
- Session tokens are opaque, hashed at rest, expiring, revocable, and rotated on
  password change/reset. The CSRF token is derived from the session token and
  verified against a stored hash.
- Generic auth failures: an unknown email and a wrong password return the same
  error after the same Argon2 work (no account enumeration).
- Email verification and password-reset tokens are single-use, hashed, and
  time-bounded; reset never reveals whether an address exists.
- Google linking is by Google-asserted verified email onto the one account with
  that address; an unverified local account's unproven password identity and
  sessions are discarded (pre-hijack defence), and accounts created by Google
  have no password identity until the student sets one.
- Account deletion revokes sessions, deletes every user-scoped row, unlinks
  devices, and leaves only an anonymised tombstone row (no email/name/class).
"""

from __future__ import annotations

import datetime
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import quote

from db.uuid7 import uuid7_str

from ..config import BackendConfig, BackendConfigError, normalize_locale
from ..errors import APIError
from .email import (
    EmailSender,
    OutboundEmail,
    password_reset_email,
    verification_email,
)
from .google import GoogleIdentity, GoogleOAuthClient
from .passwords import (
    hash_password,
    password_needs_rehash,
    password_problem,
    same_secret,
    verify_password,
)
from .rate_limit import AuthRateLimiter
from .tokens import (
    CSRF_TOKEN_DOMAIN,
    EMAIL_TOKEN_DOMAIN,
    SESSION_TOKEN_DOMAIN,
    derive_csrf,
    keyed_hash,
    new_token,
)

_EMAIL_RE: Final[re.Pattern[str]] = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MAX_EMAIL_LENGTH: Final[int] = 254
_MAX_DISPLAY_NAME: Final[int] = 80
_MAX_BOARD: Final[int] = 40
EXPORT_EVENT_LIMIT: Final[int] = 2000

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthContext:
    """A verified account session resolved from the cookie."""

    user: dict[str, Any]
    session: dict[str, Any]


@dataclass(frozen=True)
class SessionGrant:
    """A freshly minted session: the only time the raw secrets exist in memory."""

    user: dict[str, Any]
    session_id: str
    raw_token: str
    csrf_token: str
    expires_at: str


@dataclass(frozen=True)
class GoogleCallbackResult:
    grant: SessionGrant
    next_path: str


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _iso(value: datetime.datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.UTC)
    value = value.astimezone(datetime.UTC)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + f"{value.microsecond // 1000:03d}Z"


def _parse_iso(value: object) -> datetime.datetime | None:
    if value is None:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.UTC)
    return parsed.astimezone(datetime.UTC)


def _is_unique_violation(exc: Exception) -> bool:
    name = type(exc).__name__.casefold()
    if "integrity" in name or "unique" in name:
        return True
    text = str(exc).casefold()
    return "unique" in text or "duplicate" in text


def normalize_email(raw: str) -> str:
    """Case-fold and validate an email address (DB stores the normalised form)."""
    email = (raw or "").strip().lower()
    if len(email) > _MAX_EMAIL_LENGTH or not _EMAIL_RE.match(email):
        raise APIError(
            "E-VALIDATION", status_code=422, extra={"reason": "invalid_email"}
        )
    return email


def safe_next_path(value: object, default: str = "/app") -> str:
    """Return a same-origin post-auth path, or `default`.

    A leading single `/` is required and `//host` (protocol-relative) plus any
    backslash/control character is rejected, so `next` can never turn the
    Google callback into an open redirect.
    """
    candidate = str(value or "").strip()
    if not candidate.startswith("/") or candidate.startswith("//"):
        return default
    if any(ch in candidate for ch in ("\\", "\r", "\n", "\t", "\x00")):
        return default
    return candidate


class AuthService:
    """All account/auth operations. One instance per app, stateless per request."""

    def __init__(
        self,
        config: BackendConfig,
        db: Any,
        *,
        email_sender: EmailSender,
        google_client: GoogleOAuthClient | None = None,
        rate_limiter: AuthRateLimiter | None = None,
        clock: Callable[[], datetime.datetime] = _utcnow,
    ) -> None:
        self.config = config
        self.db = db
        self.email = email_sender
        self.google = google_client or GoogleOAuthClient(config)
        self.rate_limiter = rate_limiter or AuthRateLimiter(config)
        self._clock = clock

    # -- time ---------------------------------------------------------------

    def now(self) -> datetime.datetime:
        return self._clock()

    def _now_iso(self) -> str:
        return _iso(self.now())

    def _expiry(self, seconds: int) -> str:
        return _iso(self.now() + datetime.timedelta(seconds=seconds))

    # -- rate limits --------------------------------------------------------

    def check_rate_limit(self, family: str, ip_hash: str | None) -> None:
        decision = self.rate_limiter.check(family, ip_hash)
        if not decision.allowed:
            raise APIError(
                "E-RATE-LIMIT",
                status_code=429,
                retryable=True,
                retry_after=decision.retry_after,
            )

    # -- lookups ------------------------------------------------------------

    def _user_row(self, user_id: str) -> dict[str, Any] | None:
        return self.db.fetchone(
            "SELECT * FROM users WHERE user_id = ? AND deleted_at IS NULL",
            (user_id,),
        )

    def _user_by_email(self, email: str) -> dict[str, Any] | None:
        return self.db.fetchone(
            "SELECT * FROM users WHERE email = ? AND deleted_at IS NULL",
            (email,),
        )

    def _identities(self, user_id: str) -> list[dict[str, Any]]:
        return self.db.fetchall(
            "SELECT provider FROM auth_identity WHERE user_id = ? ORDER BY provider",
            (user_id,),
        )

    def _has_provider(self, user_id: str, provider: str) -> bool:
        return (
            self.db.fetchone(
                "SELECT identity_id FROM auth_identity WHERE user_id = ? AND provider = ?",
                (user_id, provider),
            )
            is not None
        )

    def user_public(self, user: dict[str, Any]) -> dict[str, Any]:
        user_id = str(user["user_id"])
        return {
            "user_id": user_id,
            "email": str(user["email"]),
            "email_verified": user.get("email_verified_at") is not None,
            "display_name": user.get("display_name"),
            "class_level": (
                int(user["class_level"])
                if user.get("class_level") is not None
                else None
            ),
            "board": str(user.get("board") or "CBSE"),
            "language": str(user.get("language") or "en-IN"),
            "role": str(user.get("role") or "student"),
            "created_at": user.get("created_at"),
        }

    # -- sessions -----------------------------------------------------------

    def _issue_session(
        self,
        tx: Any,
        user: dict[str, Any],
        *,
        ip_hash: str | None,
        user_agent_hash: str | None,
    ) -> SessionGrant:
        session_id = uuid7_str()
        raw_token = new_token()
        csrf_token = self.csrf_for(raw_token)
        expires_at = self._expiry(self.config.auth_session_ttl_seconds)
        tx.execute(
            """
            INSERT INTO auth_session (
                session_id, user_id, token_hash, csrf_token_hash, expires_at,
                created_at, last_seen_at, ip_hash, user_agent_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                str(user["user_id"]),
                keyed_hash(
                    self.config.session_token_key, SESSION_TOKEN_DOMAIN, raw_token
                ),
                keyed_hash(
                    self.config.session_token_key, CSRF_TOKEN_DOMAIN, csrf_token
                ),
                expires_at,
                self._now_iso(),
                self._now_iso(),
                ip_hash,
                user_agent_hash,
            ),
        )
        return SessionGrant(
            user=user,
            session_id=session_id,
            raw_token=raw_token,
            csrf_token=csrf_token,
            expires_at=expires_at,
        )

    def csrf_for(self, raw_token: str) -> str:
        """Derive the CSRF token the client echoes in `X-CSRF-Token`."""
        return derive_csrf(self.config.session_token_key, raw_token)

    def resolve(self, raw_token: str | None) -> AuthContext | None:
        """Resolve a cookie value to an active account session, or None."""
        token = (raw_token or "").strip()
        if not token or self.db is None:
            return None
        row = self.db.fetchone(
            "SELECT * FROM auth_session WHERE token_hash = ?",
            (keyed_hash(self.config.session_token_key, SESSION_TOKEN_DOMAIN, token),),
        )
        if row is None or row.get("revoked_at") is not None:
            return None
        expires = _parse_iso(row.get("expires_at"))
        if expires is None or expires <= self.now():
            return None
        user = self._user_row(str(row["user_id"]))
        if user is None:
            return None
        return AuthContext(user=user, session=row)

    def verify_csrf(self, ctx: AuthContext, raw_csrf: str | None) -> bool:
        token = (raw_csrf or "").strip()
        if not token:
            return False
        expected = str(ctx.session.get("csrf_token_hash") or "")
        actual = keyed_hash(self.config.session_token_key, CSRF_TOKEN_DOMAIN, token)
        return bool(expected) and same_secret(actual, expected)

    def session_payload(
        self, ctx: AuthContext | None, raw_token: str | None = None
    ) -> dict[str, Any]:
        if ctx is None:
            return {"authenticated": False, "user": None, "csrf_token": None}
        user_id = str(ctx.user["user_id"])
        payload = {
            "authenticated": True,
            "user": self.user_public(ctx.user),
            "password_set": self._has_provider(user_id, "password"),
            "google_linked": self._has_provider(user_id, "google"),
            "session_id": str(ctx.session["session_id"]),
            "expires_at": ctx.session.get("expires_at"),
            "csrf_token": self.csrf_for(raw_token) if raw_token else None,
        }
        return payload

    def grant_payload(self, grant: SessionGrant) -> dict[str, Any]:
        user_id = str(grant.user["user_id"])
        return {
            "authenticated": True,
            "user": self.user_public(grant.user),
            "password_set": self._has_provider(user_id, "password"),
            "google_linked": self._has_provider(user_id, "google"),
            "session_id": grant.session_id,
            "expires_at": grant.expires_at,
            "csrf_token": grant.csrf_token,
        }

    def profile_payload_for_user(self, user: dict[str, Any]) -> dict[str, Any]:
        user_id = str(user["user_id"])
        return {
            "user": self.user_public(user),
            "password_set": self._has_provider(user_id, "password"),
            "google_linked": self._has_provider(user_id, "google"),
        }

    def profile_payload(self, ctx: AuthContext) -> dict[str, Any]:
        return self.profile_payload_for_user(ctx.user)

    def revoke_session(self, session_id: str) -> None:
        self.db.execute(
            "UPDATE auth_session SET revoked_at = ? WHERE session_id = ? AND revoked_at IS NULL",
            (self._now_iso(), session_id),
        )

    def revoke_all_sessions(self, user_id: str) -> int:
        row = self.db.fetchone(
            "SELECT COUNT(*) AS cnt FROM auth_session WHERE user_id = ? AND revoked_at IS NULL",
            (user_id,),
        )
        count = int(row["cnt"]) if row else 0
        self.db.execute(
            "UPDATE auth_session SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
            (self._now_iso(), user_id),
        )
        return count

    # -- registration / login ----------------------------------------------

    def register(
        self,
        *,
        email: str,
        password: str,
        display_name: str | None = None,
        class_level: int | None = None,
        board: str = "CBSE",
        language: str = "en-IN",
        device_pseudo_id: str | None = None,
        ip_hash: str | None = None,
        user_agent_hash: str | None = None,
    ) -> SessionGrant:
        normalised = normalize_email(email)
        reason = password_problem(password, email=normalised)
        if reason is not None:
            raise APIError("E-VALIDATION", status_code=422, extra={"reason": reason})
        class_level = _validate_class_level(class_level)
        board = _validate_board(board)
        try:
            locale = normalize_locale(language)
        except ValueError as exc:
            raise APIError(
                "E-VALIDATION", status_code=422, extra={"reason": "invalid_language"}
            ) from exc
        display_name = _clean_display_name(display_name)
        verify_token = new_token()

        now = self._now_iso()
        user_id = uuid7_str()
        with self.db.transaction() as tx:
            if tx.fetchone("SELECT user_id FROM users WHERE email = ?", (normalised,)):
                raise APIError("E-CONFLICT", status_code=409)
            try:
                tx.execute(
                    """
                    INSERT INTO users (
                        user_id, email, display_name, class_level, board, language,
                        role, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'student', ?, ?)
                    """,
                    (
                        user_id,
                        normalised,
                        display_name,
                        class_level,
                        board,
                        locale,
                        now,
                        now,
                    ),
                )
                tx.execute(
                    """
                    INSERT INTO auth_identity (
                        identity_id, user_id, provider, provider_subject,
                        password_hash, created_at, updated_at
                    ) VALUES (?, ?, 'password', ?, ?, ?, ?)
                    """,
                    (
                        uuid7_str(),
                        user_id,
                        normalised,
                        hash_password(password),
                        now,
                        now,
                    ),
                )
            except Exception as exc:
                if _is_unique_violation(exc):
                    raise APIError("E-CONFLICT", status_code=409) from exc
                raise
            new_user = {
                "user_id": user_id,
                "email": normalised,
                "email_verified_at": None,
                "display_name": display_name,
                "class_level": class_level,
                "board": board,
                "language": locale,
                "role": "student",
                "created_at": now,
            }
            grant = self._issue_session(
                tx, new_user, ip_hash=ip_hash, user_agent_hash=user_agent_hash
            )
            self._insert_email_token(tx, user_id, "verify", verify_token)
            if device_pseudo_id:
                self._attach_device_tx(tx, user_id, device_pseudo_id, locale)

        self._send_verification(normalised, verify_token)
        return grant

    def login(
        self,
        *,
        email: str,
        password: str,
        device_pseudo_id: str | None = None,
        ip_hash: str | None = None,
        user_agent_hash: str | None = None,
    ) -> SessionGrant:
        normalised = normalize_email(email)
        row = self.db.fetchone(
            """
            SELECT i.identity_id, i.password_hash, u.*
            FROM auth_identity i
            JOIN users u ON u.user_id = i.user_id
            WHERE i.provider = 'password' AND i.provider_subject = ?
              AND u.deleted_at IS NULL
            """,
            (normalised,),
        )
        if row is None:
            # Same Argon2 cost as a real check (timing-equalised failure).
            from .passwords import burn_password_check

            burn_password_check(password)
            raise APIError("E-AUTH-INVALID", status_code=401)
        stored_hash = str(row.get("password_hash") or "")
        if not stored_hash or not verify_password(stored_hash, password):
            raise APIError("E-AUTH-INVALID", status_code=401)
        user_id = str(row["user_id"])
        if password_needs_rehash(stored_hash):
            self.db.execute(
                "UPDATE auth_identity SET password_hash = ?, updated_at = ? WHERE identity_id = ?",
                (hash_password(password), self._now_iso(), str(row["identity_id"])),
            )
        user = {
            "user_id": user_id,
            "email": str(row["email"]),
            "email_verified_at": row.get("email_verified_at"),
            "display_name": row.get("display_name"),
            "class_level": row.get("class_level"),
            "board": row.get("board"),
            "language": row.get("language"),
            "role": row.get("role"),
            "created_at": row.get("created_at"),
        }
        with self.db.transaction() as tx:
            grant = self._issue_session(
                tx, user, ip_hash=ip_hash, user_agent_hash=user_agent_hash
            )
            if device_pseudo_id:
                locale = str(user.get("language") or "en-IN")
                self._attach_device_tx(tx, user_id, device_pseudo_id, locale)
        return grant

    # -- email verification / password reset --------------------------------

    def _insert_email_token(
        self, tx: Any, user_id: str, kind: str, raw_token: str
    ) -> None:
        now = self._now_iso()
        tx.execute(
            "UPDATE email_token SET used_at = ? WHERE user_id = ? AND kind = ? AND used_at IS NULL",
            (now, user_id, kind),
        )
        ttl = (
            self.config.auth_verify_token_ttl_seconds
            if kind == "verify"
            else self.config.auth_reset_token_ttl_seconds
        )
        tx.execute(
            """
            INSERT INTO email_token (token_id, user_id, kind, token_hash, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                uuid7_str(),
                user_id,
                kind,
                keyed_hash(
                    self.config.session_token_key, EMAIL_TOKEN_DOMAIN, raw_token
                ),
                self._expiry(ttl),
                now,
            ),
        )

    def _safe_send(self, message: OutboundEmail) -> None:
        """Deliver a transactional mail; a delivery failure never undoes the action.

        A signup whose verification mail fails must still exist (the student can
        request a new link once F2 ships the resend action); the failure is
        logged for the operator rather than turned into a 500 after commit.
        """
        try:
            self.email.send(message)
        except Exception:
            logger.exception(
                "transactional email delivery failed (kind=%s)", message.kind
            )

    def _send_verification(self, email: str, token: str) -> None:
        link = (
            f"{self.config.app_base_url.rstrip('/')}/verify-email?token={quote(token)}"
        )
        message: OutboundEmail = verification_email(
            to=email,
            link=link,
            expires_hours=max(1, self.config.auth_verify_token_ttl_seconds // 3600),
        )
        self._safe_send(message)

    def _consume_email_token(self, raw_token: str, kind: str) -> dict[str, Any]:
        token = (raw_token or "").strip()
        if not token:
            raise APIError("E-TOKEN-INVALID", status_code=400)
        row = self.db.fetchone(
            "SELECT * FROM email_token WHERE token_hash = ? AND kind = ?",
            (
                keyed_hash(self.config.session_token_key, EMAIL_TOKEN_DOMAIN, token),
                kind,
            ),
        )
        if row is None or row.get("used_at") is not None:
            raise APIError("E-TOKEN-INVALID", status_code=400)
        expires = _parse_iso(row.get("expires_at"))
        if expires is None or expires <= self.now():
            raise APIError("E-TOKEN-INVALID", status_code=400)
        return row

    def verify_email(self, token: str) -> dict[str, Any]:
        row = self._consume_email_token(token, "verify")
        now = self._now_iso()
        with self.db.transaction() as tx:
            consumed = tx.fetchone(
                "SELECT used_at FROM email_token WHERE token_id = ?", (row["token_id"],)
            )
            if consumed is None or consumed.get("used_at") is not None:
                raise APIError("E-TOKEN-INVALID", status_code=400)
            tx.execute(
                "UPDATE email_token SET used_at = ? WHERE token_id = ?",
                (now, str(row["token_id"])),
            )
            tx.execute(
                """
                UPDATE users
                SET email_verified_at = COALESCE(email_verified_at, ?), updated_at = ?
                WHERE user_id = ?
                """,
                (now, now, str(row["user_id"])),
            )
        return {"ok": True, "email_verified": True}

    def request_password_reset(self, email: str) -> None:
        """Always succeeds from the caller's point of view (no enumeration)."""
        normalised = normalize_email(email)
        row = self.db.fetchone(
            """
            SELECT u.user_id, u.email
            FROM users u
            JOIN auth_identity i ON i.user_id = u.user_id AND i.provider = 'password'
            WHERE u.email = ? AND u.deleted_at IS NULL AND u.email_verified_at IS NOT NULL
            """,
            (normalised,),
        )
        if row is None:
            return
        token = new_token()
        with self.db.transaction() as tx:
            self._insert_email_token(tx, str(row["user_id"]), "reset", token)
        link = f"{self.config.app_base_url.rstrip('/')}/reset-password?token={quote(token)}"
        self._safe_send(
            password_reset_email(
                to=str(row["email"]),
                link=link,
                expires_minutes=max(1, self.config.auth_reset_token_ttl_seconds // 60),
            )
        )

    def reset_password(self, *, token: str, new_password: str) -> dict[str, Any]:
        row = self._consume_email_token(token, "reset")
        user = self._user_row(str(row["user_id"]))
        if user is None:
            raise APIError("E-TOKEN-INVALID", status_code=400)
        reason = password_problem(new_password, email=str(user["email"]))
        if reason is not None:
            raise APIError("E-VALIDATION", status_code=422, extra={"reason": reason})
        now = self._now_iso()
        with self.db.transaction() as tx:
            consumed = tx.fetchone(
                "SELECT used_at FROM email_token WHERE token_id = ?", (row["token_id"],)
            )
            if consumed is None or consumed.get("used_at") is not None:
                raise APIError("E-TOKEN-INVALID", status_code=400)
            tx.execute(
                "UPDATE email_token SET used_at = ? WHERE token_id = ?",
                (now, str(row["token_id"])),
            )
            identity = tx.fetchone(
                "SELECT identity_id FROM auth_identity WHERE user_id = ? AND provider = 'password'",
                (str(user["user_id"]),),
            )
            if identity is None:
                tx.execute(
                    """
                    INSERT INTO auth_identity (
                        identity_id, user_id, provider, provider_subject,
                        password_hash, created_at, updated_at
                    ) VALUES (?, ?, 'password', ?, ?, ?, ?)
                    """,
                    (
                        uuid7_str(),
                        str(user["user_id"]),
                        str(user["email"]),
                        hash_password(new_password),
                        now,
                        now,
                    ),
                )
            else:
                tx.execute(
                    "UPDATE auth_identity SET password_hash = ?, updated_at = ? WHERE identity_id = ?",
                    (hash_password(new_password), now, str(identity["identity_id"])),
                )
            tx.execute(
                "UPDATE auth_session SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                (now, str(user["user_id"])),
            )
        revoked = self.db.fetchone(
            "SELECT COUNT(*) AS cnt FROM auth_session WHERE user_id = ? AND revoked_at = ?",
            (str(user["user_id"]), now),
        )
        return {
            "ok": True,
            "sessions_revoked": int(revoked["cnt"]) if revoked else 0,
        }

    # -- Google -------------------------------------------------------------

    def google_start(
        self,
        *,
        intent: str,
        next_path: str,
        current: AuthContext | None,
    ) -> tuple[str, str]:
        if intent not in ("login", "link"):
            raise APIError(
                "E-VALIDATION", status_code=422, extra={"reason": "invalid_intent"}
            )
        if intent == "link":
            if current is None:
                raise APIError("E-AUTH-REQUIRED", status_code=401)
            if current.user.get("email_verified_at") is None:
                raise APIError("E-EMAIL-UNVERIFIED", status_code=403)
        safe_next = safe_next_path(next_path)
        try:
            return self.google.start(intent=intent, next_path=safe_next)
        except BackendConfigError as exc:
            raise APIError("E-SERVICE-UNAVAILABLE", status_code=503) from exc

    def google_callback(
        self,
        *,
        code: str,
        state: str,
        state_cookie: str | None,
        current: AuthContext | None = None,
        ip_hash: str | None = None,
        user_agent_hash: str | None = None,
    ) -> GoogleCallbackResult:
        from .google import GoogleAuthError, verify_state

        payload = verify_state(self.config, state_cookie)
        if payload is None:
            raise APIError("E-AUTH-INVALID", status_code=400)
        if not same_secret(str(payload.get("state") or ""), (state or "").strip()):
            raise APIError("E-AUTH-INVALID", status_code=400)
        try:
            identity = self.google.exchange(
                code=code, verifier=str(payload["verifier"])
            )
        except GoogleAuthError as exc:
            raise APIError(
                exc.code, status_code=400 if exc.code == "E-AUTH-INVALID" else 503
            ) from exc
        if not identity.email_verified:
            raise APIError("E-EMAIL-UNVERIFIED", status_code=403)
        if payload.get("intent") == "link":
            if current is None:
                raise APIError("E-AUTH-REQUIRED", status_code=401)
            grant = self._google_link_to(current, identity, ip_hash, user_agent_hash)
        else:
            grant = self._google_login_or_create(identity, ip_hash, user_agent_hash)
        next_path = safe_next_path(payload.get("next"))
        return GoogleCallbackResult(grant=grant, next_path=next_path)

    def _google_identity_user(self, subject: str) -> dict[str, Any] | None:
        row = self.db.fetchone(
            """
            SELECT u.* FROM auth_identity i
            JOIN users u ON u.user_id = i.user_id
            WHERE i.provider = 'google' AND i.provider_subject = ?
              AND u.deleted_at IS NULL
            """,
            (subject,),
        )
        return row

    def _google_login_or_create(
        self,
        identity: GoogleIdentity,
        ip_hash: str | None,
        user_agent_hash: str | None,
    ) -> SessionGrant:
        user = self._google_identity_user(identity.subject)
        if user is not None:
            with self.db.transaction() as tx:
                return self._issue_session(
                    tx,
                    user,
                    ip_hash=ip_hash,
                    user_agent_hash=user_agent_hash,
                )

        existing = self._user_by_email(identity.email)
        now = self._now_iso()
        if existing is not None:
            user_id = str(existing["user_id"])
            verified = existing.get("email_verified_at") is not None
            with self.db.transaction() as tx:
                if not verified:
                    # Google just proved ownership of an address this account
                    # never proved. Whoever created the row chose that password
                    # and holds those sessions, so neither may survive: an
                    # attacker who pre-registers a victim's address would
                    # otherwise keep reading the account after the victim signs
                    # in with Google (account pre-hijacking). The student keeps
                    # the row and is prompted to set a password
                    # (`password_set: false`).
                    tx.execute(
                        "DELETE FROM auth_identity WHERE user_id = ? AND provider = 'password'",
                        (user_id,),
                    )
                    tx.execute(
                        """
                        UPDATE auth_session SET revoked_at = ?
                        WHERE user_id = ? AND revoked_at IS NULL
                        """,
                        (now, user_id),
                    )
                try:
                    tx.execute(
                        """
                        INSERT INTO auth_identity (
                            identity_id, user_id, provider, provider_subject,
                            password_hash, created_at, updated_at
                        ) VALUES (?, ?, 'google', ?, NULL, ?, ?)
                        """,
                        (uuid7_str(), user_id, identity.subject, now, now),
                    )
                except Exception as exc:
                    if _is_unique_violation(exc):
                        # A concurrent callback already bound this subject;
                        # never continue as if the link succeeded.
                        raise APIError("E-CONFLICT", status_code=409) from exc
                    raise
                # Google asserted ownership of this address: record the
                # verification the local account was missing.
                tx.execute(
                    """
                    UPDATE users
                    SET email_verified_at = COALESCE(email_verified_at, ?), updated_at = ?
                    WHERE user_id = ?
                    """,
                    (now, now, user_id),
                )
                user = dict(existing)
                if user.get("email_verified_at") is None:
                    user["email_verified_at"] = now
                return self._issue_session(
                    tx,
                    user,
                    ip_hash=ip_hash,
                    user_agent_hash=user_agent_hash,
                )

        user_id = uuid7_str()
        new_user = {
            "user_id": user_id,
            "email": identity.email,
            "email_verified_at": now,
            "display_name": identity.name,
            "class_level": None,
            "board": "CBSE",
            "language": "en-IN",
            "role": "student",
            "created_at": now,
        }
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO users (
                    user_id, email, email_verified_at, display_name, board,
                    language, role, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'CBSE', 'en-IN', 'student', ?, ?)
                """,
                (user_id, identity.email, now, identity.name, now, now),
            )
            tx.execute(
                """
                INSERT INTO auth_identity (
                    identity_id, user_id, provider, provider_subject,
                    password_hash, created_at, updated_at
                ) VALUES (?, ?, 'google', ?, NULL, ?, ?)
                """,
                (uuid7_str(), user_id, identity.subject, now, now),
            )
            return self._issue_session(
                tx,
                new_user,
                ip_hash=ip_hash,
                user_agent_hash=user_agent_hash,
            )

    def _google_link_to(
        self,
        current: AuthContext,
        identity: GoogleIdentity,
        ip_hash: str | None,
        user_agent_hash: str | None,
    ) -> SessionGrant:
        user_id = str(current.user["user_id"])
        by_subject = self._google_identity_user(identity.subject)
        if by_subject is not None and str(by_subject["user_id"]) != user_id:
            raise APIError("E-CONFLICT", status_code=409)
        by_email = self._user_by_email(identity.email)
        if by_email is not None and str(by_email["user_id"]) != user_id:
            # Never merge two accounts because an email matches; the student
            # signs in to the other account instead.
            raise APIError("E-CONFLICT", status_code=409)
        now = self._now_iso()
        with self.db.transaction() as tx:
            try:
                tx.execute(
                    """
                    INSERT INTO auth_identity (
                        identity_id, user_id, provider, provider_subject,
                        password_hash, created_at, updated_at
                    ) VALUES (?, ?, 'google', ?, NULL, ?, ?)
                    """,
                    (uuid7_str(), user_id, identity.subject, now, now),
                )
            except Exception as exc:
                if _is_unique_violation(exc):
                    # The subject is already bound elsewhere (concurrent
                    # callback): fail closed instead of pretending to link.
                    raise APIError("E-CONFLICT", status_code=409) from exc
                raise
            tx.execute(
                """
                UPDATE users
                SET email_verified_at = COALESCE(email_verified_at, ?), updated_at = ?
                WHERE user_id = ?
                """,
                (now, now, user_id),
            )
            # Rotate: the Google round-trip re-authenticated the student.
            tx.execute(
                "UPDATE auth_session SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                (now, user_id),
            )
            current_user = dict(current.user)
            if current_user.get("email_verified_at") is None:
                current_user["email_verified_at"] = now
            return self._issue_session(
                tx,
                current_user,
                ip_hash=ip_hash,
                user_agent_hash=user_agent_hash,
            )

    # -- profile / password / devices --------------------------------------

    def update_profile(self, *, user_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        updates: list[str] = []
        params: list[Any] = []
        if "display_name" in patch:
            updates.append("display_name = ?")
            params.append(_clean_display_name(patch.get("display_name")))
        if "class_level" in patch:
            updates.append("class_level = ?")
            params.append(_validate_class_level(patch.get("class_level")))
        if "board" in patch:
            updates.append("board = ?")
            params.append(_validate_board(str(patch.get("board") or "CBSE")))
        if "language" in patch:
            try:
                locale = normalize_locale(str(patch.get("language") or ""))
            except ValueError as exc:
                raise APIError(
                    "E-VALIDATION",
                    status_code=422,
                    extra={"reason": "invalid_language"},
                ) from exc
            updates.append("language = ?")
            params.append(locale)
        if not updates:
            raise APIError(
                "E-VALIDATION", status_code=422, extra={"reason": "no_fields"}
            )
        updates.append("updated_at = ?")
        params.append(self._now_iso())
        params.append(user_id)
        with self.db.transaction() as tx:
            tx.execute(
                f"UPDATE users SET {', '.join(updates)} WHERE user_id = ? AND deleted_at IS NULL",
                tuple(params),
            )
            user = tx.fetchone(
                "SELECT * FROM users WHERE user_id = ? AND deleted_at IS NULL",
                (user_id,),
            )
        if user is None:
            raise APIError("E-AUTH-REQUIRED", status_code=401)
        return user

    def set_or_change_password(
        self,
        *,
        ctx: AuthContext,
        current_password: str | None,
        new_password: str,
        ip_hash: str | None = None,
        user_agent_hash: str | None = None,
    ) -> SessionGrant:
        user_id = str(ctx.user["user_id"])
        identity = self.db.fetchone(
            "SELECT identity_id, password_hash FROM auth_identity WHERE user_id = ? AND provider = 'password'",
            (user_id,),
        )
        if identity is not None and (
            not current_password
            or not verify_password(
                str(identity.get("password_hash") or ""), current_password
            )
        ):
            raise APIError("E-AUTH-INVALID", status_code=401)
        reason = password_problem(new_password, email=str(ctx.user["email"]))
        if reason is not None:
            raise APIError("E-VALIDATION", status_code=422, extra={"reason": reason})
        now = self._now_iso()
        with self.db.transaction() as tx:
            if identity is None:
                tx.execute(
                    """
                    INSERT INTO auth_identity (
                        identity_id, user_id, provider, provider_subject,
                        password_hash, created_at, updated_at
                    ) VALUES (?, ?, 'password', ?, ?, ?, ?)
                    """,
                    (
                        uuid7_str(),
                        user_id,
                        str(ctx.user["email"]),
                        hash_password(new_password),
                        now,
                        now,
                    ),
                )
            else:
                tx.execute(
                    "UPDATE auth_identity SET password_hash = ?, updated_at = ? WHERE identity_id = ?",
                    (hash_password(new_password), now, str(identity["identity_id"])),
                )
            tx.execute(
                "UPDATE auth_session SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                (now, user_id),
            )
            current_user = dict(ctx.user)
            return self._issue_session(
                tx,
                current_user,
                ip_hash=ip_hash,
                user_agent_hash=user_agent_hash,
            )

    def attach_device(self, *, user_id: str, device_pseudo_id: str) -> None:
        user = self._user_row(user_id)
        if user is None:
            raise APIError("E-AUTH-REQUIRED", status_code=401)
        locale = str(user.get("language") or "en-IN")
        with self.db.transaction() as tx:
            self._attach_device_tx(tx, user_id, device_pseudo_id, locale)

    def _attach_device_tx(
        self, tx: Any, user_id: str, device_pseudo_id: str, locale: str
    ) -> None:
        from ..identity import validate_device_pseudo_id

        device_id = validate_device_pseudo_id(device_pseudo_id)
        now = self._now_iso()
        tx.execute(
            """
            INSERT INTO device (device_pseudo_id, first_seen_at, last_seen_at, locale, user_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (device_pseudo_id) DO UPDATE SET
                last_seen_at = excluded.last_seen_at, user_id = excluded.user_id
            """,
            (device_id, now, now, locale, user_id),
        )

    # -- delete / export ----------------------------------------------------

    def delete_account(
        self,
        *,
        ctx: AuthContext,
        confirm: str,
        password: str | None,
        ip_hash: str | None = None,
    ) -> dict[str, int]:
        del ip_hash
        if (confirm or "").strip() != "DELETE":
            raise APIError("E-CONFIRM-REQUIRED", status_code=400)
        user_id = str(ctx.user["user_id"])
        identity = self.db.fetchone(
            "SELECT password_hash FROM auth_identity WHERE user_id = ? AND provider = 'password'",
            (user_id,),
        )
        if identity is not None and (
            not password
            or not verify_password(str(identity.get("password_hash") or ""), password)
        ):
            raise APIError("E-AUTH-INVALID", status_code=401)

        deleted: dict[str, int] = {}
        now = self._now_iso()
        with self.db.transaction() as tx:
            # Personalized learning (data-and-api.md §2.7): the child free-text
            # store dies with the account — messages first (they cascade, but
            # the explicit fan-out keeps the delete honest with FKs off), then
            # sessions, usage (counts survive, subject link dropped), quota
            # rows, and the preferences row. Only the users tombstone remains.
            tx.execute(
                """
                DELETE FROM personalized_message WHERE session_id IN (
                    SELECT session_id FROM personalized_session WHERE user_id = ?
                )
                """,
                (user_id,),
            )
            for label, table in (
                ("preferences", "user_preferences"),
                ("personalized_sessions", "personalized_session"),
                ("personalized_usage", "personalized_usage"),
            ):
                row = tx.fetchone(
                    f"SELECT COUNT(*) AS cnt FROM {table} WHERE user_id = ?", (user_id,)
                )
                deleted[label] = int(row["cnt"]) if row else 0
                tx.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
            # personalized_quota keys the user by scope_key (data-and-api.md §2.6).
            quota_row = tx.fetchone(
                "SELECT COUNT(*) AS cnt FROM personalized_quota WHERE scope = 'user' AND scope_key = ?",
                (user_id,),
            )
            deleted["personalized_quota"] = int(quota_row["cnt"]) if quota_row else 0
            tx.execute(
                "DELETE FROM personalized_quota WHERE scope = 'user' AND scope_key = ?",
                (user_id,),
            )
            for label, table in (
                ("sessions", "auth_session"),
                ("identities", "auth_identity"),
                ("email_tokens", "email_token"),
                ("lesson_progress", "lesson_progress"),
                ("progress_events", "progress_event"),
                ("bookmarks", "bookmark"),
            ):
                row = tx.fetchone(
                    f"SELECT COUNT(*) AS cnt FROM {table} WHERE user_id = ?", (user_id,)
                )
                deleted[label] = int(row["cnt"]) if row else 0
                tx.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
            devices = tx.fetchone(
                "SELECT COUNT(*) AS cnt FROM device WHERE user_id = ?", (user_id,)
            )
            deleted["devices_unlinked"] = int(devices["cnt"]) if devices else 0
            tx.execute("UPDATE device SET user_id = NULL WHERE user_id = ?", (user_id,))
            tombstone_email = f"deleted+{user_id}@invalid"
            tx.execute(
                """
                UPDATE users
                SET email = ?, email_verified_at = NULL, display_name = NULL,
                    class_level = NULL, deleted_at = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (tombstone_email, now, now, user_id),
            )
            tx.execute(
                """
                INSERT INTO audit_log (audit_id, actor, action, target, before_hash, after_hash, at)
                VALUES (?, ?, 'account_deleted', ?, NULL, NULL, ?)
                """,
                (uuid7_str(), f"user:{user_id}", user_id, now),
            )
        return deleted

    def export_account(self, *, user_id: str) -> dict[str, Any]:
        user = self._user_row(user_id)
        if user is None:
            raise APIError("E-AUTH-REQUIRED", status_code=401)
        identities = self.db.fetchall(
            "SELECT provider, provider_subject, created_at FROM auth_identity WHERE user_id = ? ORDER BY provider",
            (user_id,),
        )
        sessions = self.db.fetchall(
            "SELECT session_id, created_at, expires_at, revoked_at FROM auth_session WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )
        progress = self.db.fetchall(
            "SELECT chapter_id, status, last_block_id, blocks_seen, blocks_total, updated_at, completed_at FROM lesson_progress WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        )
        events = self.db.fetchall(
            "SELECT event_id, kind, chapter_id, concept_id, question_id, payload, created_at FROM progress_event WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, EXPORT_EVENT_LIMIT),
        )
        event_total_row = self.db.fetchone(
            "SELECT COUNT(*) AS cnt FROM progress_event WHERE user_id = ?", (user_id,)
        )
        event_total = int(event_total_row["cnt"]) if event_total_row else 0
        bookmarks = self.db.fetchall(
            "SELECT bookmark_id, target_type, target_id, created_at FROM bookmark WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )
        # Personalized learning (data-and-api.md §2.1: the preferences row is
        # included in export; the sessions summary carries no message text —
        # per-session export (API-PL-09) is the transcript's export path).
        prefs_row = self.db.fetchone(
            "SELECT personal_instructions, instructions_version, updated_at "
            "FROM user_preferences WHERE user_id = ?",
            (user_id,),
        )
        pl_sessions = self.db.fetchall(
            "SELECT session_id, title, chapter_id, status, created_at, last_turn_at "
            "FROM personalized_session WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        )
        pl_session_total = len(pl_sessions)
        return {
            "exported_at": self._now_iso(),
            "user": self.user_public(user),
            "preferences": {
                "personal_instructions": (
                    prefs_row.get("personal_instructions") if prefs_row else None
                ),
                "instructions_version": (
                    int(prefs_row["instructions_version"]) if prefs_row else 0
                ),
                "updated_at": prefs_row.get("updated_at") if prefs_row else None,
            },
            "personalized_sessions": [
                {
                    "session_id": str(row["session_id"]),
                    "title": str(row["title"]),
                    "chapter_id": str(row["chapter_id"]),
                    "status": str(row["status"]),
                    "created_at": row.get("created_at"),
                    "last_turn_at": row.get("last_turn_at"),
                }
                for row in pl_sessions
            ],
            "personalized_sessions_total": pl_session_total,
            "identities": [
                {
                    "provider": str(row["provider"]),
                    "created_at": row.get("created_at"),
                }
                for row in identities
            ],
            "sessions": [
                {
                    "session_id": str(row["session_id"]),
                    "created_at": row.get("created_at"),
                    "expires_at": row.get("expires_at"),
                    "revoked_at": row.get("revoked_at"),
                }
                for row in sessions
            ],
            "lesson_progress": [
                {
                    "chapter_id": str(row["chapter_id"]),
                    "status": str(row["status"]),
                    "last_block_id": row.get("last_block_id"),
                    "blocks_seen": int(row.get("blocks_seen") or 0),
                    "blocks_total": (
                        int(row["blocks_total"])
                        if row.get("blocks_total") is not None
                        else None
                    ),
                    "updated_at": row.get("updated_at"),
                    "completed_at": row.get("completed_at"),
                }
                for row in progress
            ],
            "progress_events": [
                {
                    "event_id": str(row["event_id"]),
                    "kind": str(row["kind"]),
                    "chapter_id": row.get("chapter_id"),
                    "concept_id": row.get("concept_id"),
                    "question_id": row.get("question_id"),
                    "payload": _load_json(row.get("payload")),
                    "created_at": row.get("created_at"),
                }
                for row in events
            ],
            "progress_events_total": event_total,
            # An export must say so when it is bounded, never truncate silently.
            "progress_events_truncated": len(events) < event_total,
            "bookmarks": [
                {
                    "bookmark_id": str(row["bookmark_id"]),
                    "target_type": str(row["target_type"]),
                    "target_id": str(row["target_id"]),
                    "created_at": row.get("created_at"),
                }
                for row in bookmarks
            ],
        }


def _load_json(value: object) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return None


def _clean_display_name(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > _MAX_DISPLAY_NAME:
        raise APIError(
            "E-VALIDATION", status_code=422, extra={"reason": "display_name_too_long"}
        )
    return text


def _validate_class_level(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        level = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise APIError(
            "E-VALIDATION", status_code=422, extra={"reason": "invalid_class_level"}
        ) from exc
    if level < 6 or level > 12:
        raise APIError(
            "E-VALIDATION", status_code=422, extra={"reason": "invalid_class_level"}
        )
    return level


def _validate_board(value: str) -> str:
    board = (value or "").strip() or "CBSE"
    if len(board) > _MAX_BOARD:
        raise APIError(
            "E-VALIDATION", status_code=422, extra={"reason": "invalid_board"}
        )
    return board


__all__ = [
    "AuthContext",
    "AuthService",
    "GoogleCallbackResult",
    "SessionGrant",
    "normalize_email",
]
