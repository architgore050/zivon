"""Identity, session token, confirm-challenge token, and consent gate (ADR-0007, §8.1/§8.2).

Implements:
- Client-generated `device_pseudo_id` UUID validation (no fingerprinting, T5/T6)
- HMAC-SHA256 `session_token` (`{session_id, device_pseudo_id, iat, exp}`, 12 h TTL)
- Server-issued one-time confirm challenge token for `DELETE /v1/data` (API-007)
- Server-side consent gate (`E-CONSENT-REQUIRED`, `E-CONSENT-STALE`)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
import uuid
from typing import Any, Final

from .config import BackendConfig
from .errors import APIError

_UUID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def validate_device_pseudo_id(raw_id: str) -> str:
    """Validate and normalize a client-generated pseudonymous UUID."""
    cleaned = (raw_id or "").strip().lower()
    if not _UUID_RE.match(cleaned):
        raise APIError("E-VALIDATION", status_code=422)
    return cleaned


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(text: str) -> bytes:
    pad = "=" * ((4 - len(text) % 4) % 4)
    return base64.urlsafe_b64decode(text + pad)


class IdentityManager:
    """Issues and validates session tokens, confirm challenges, and consent state."""

    def __init__(self, config: BackendConfig, db: Any = None) -> None:
        self.config = config
        self.db = db
        self._consumed_confirm_nonces: set[str] = set()

    def _sign(self, payload_b64: str) -> str:
        return hmac.new(
            self.config.session_token_key.encode("utf-8"),
            payload_b64.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()

    def issue_session_token(
        self,
        session_id: str,
        device_pseudo_id: str,
        *,
        now_ts: int | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
        """Issue an HMAC-signed 12-hour `session_token` (§8.1)."""
        iat = int(now_ts if now_ts is not None else time.time())
        ttl = (
            ttl_seconds
            if ttl_seconds is not None
            else self.config.session_ttl_seconds
        )
        payload = {
            "typ": "session",
            "session_id": session_id,
            "device_pseudo_id": validate_device_pseudo_id(device_pseudo_id),
            "iat": iat,
            "exp": iat + ttl,
        }
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
        b64 = _b64url_encode(raw)
        sig = self._sign(b64)
        return f"{b64}.{sig}"

    def verify_session_token(
        self, token: str, *, now_ts: int | None = None
    ) -> dict[str, Any] | None:
        """Verify HMAC signature and expiry of a `session_token`."""
        if not token or "." not in token:
            return None
        b64, sig = token.rsplit(".", 1)
        expected = self._sign(b64)
        if not hmac.compare_digest(sig, expected):
            return None
        try:
            payload = json.loads(_b64url_decode(b64).decode("utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("typ", "session") != "session":
            return None
        now = int(now_ts if now_ts is not None else time.time())
        if int(payload.get("exp", 0)) < now:
            return None
        if not payload.get("session_id") or not payload.get("device_pseudo_id"):
            return None
        return payload

    def issue_confirm_token(
        self,
        device_pseudo_id: str,
        *,
        now_ts: int | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
        """Issue a server-signed challenge token for `DELETE /v1/data` (API-007)."""
        norm_dev = validate_device_pseudo_id(device_pseudo_id)
        iat = int(now_ts if now_ts is not None else time.time())
        ttl = (
            ttl_seconds
            if ttl_seconds is not None
            else self.config.confirm_token_ttl_seconds
        )
        payload = {
            "typ": "confirm",
            "device_pseudo_id": norm_dev,
            "nonce": uuid.uuid4().hex[:16],
            "iat": iat,
            "exp": iat + ttl,
        }
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
        b64 = _b64url_encode(raw)
        sig = self._sign(b64)
        return f"{b64}.{sig}"

    def verify_confirm_token(
        self,
        device_pseudo_id: str,
        token: str,
        *,
        now_ts: int | None = None,
    ) -> bool:
        """Verify that `token` is a valid, un-expired challenge for `device_pseudo_id`.

        Enforces one-time challenge semantics: once a nonce is consumed to wipe
        live device data, that nonce cannot be replayed if the device later
        registers new data (while still permitting idempotent retries when the
        device remains in the wiped state per API-007).
        """
        if not token or "." not in token:
            return False
        norm_dev = validate_device_pseudo_id(device_pseudo_id)
        b64, sig = token.rsplit(".", 1)
        expected = self._sign(b64)
        if not hmac.compare_digest(sig, expected):
            return False
        try:
            payload = json.loads(_b64url_decode(b64).decode("utf-8"))
        except Exception:
            return False
        if not isinstance(payload, dict) or payload.get("typ") != "confirm":
            return False
        if payload.get("device_pseudo_id") != norm_dev:
            return False
        now = int(now_ts if now_ts is not None else time.time())
        if int(payload.get("exp", 0)) < now:
            return False

        nonce = str(payload.get("nonce") or "")
        if nonce in self._consumed_confirm_nonces:
            # Allow idempotent retry ONLY if the device still has no live row
            if self.db is not None:
                live_dev = self.db.fetchone(
                    "SELECT device_pseudo_id FROM device WHERE device_pseudo_id = ?",
                    (norm_dev,),
                )
                if live_dev is not None:
                    return False
        elif nonce:
            self._consumed_confirm_nonces.add(nonce)
        return True

    def check_consent_gate(self, device_pseudo_id: str) -> dict[str, Any]:
        """Enforce server-side consent gate (§8.2)."""
        norm_dev = validate_device_pseudo_id(device_pseudo_id)
        if self.db is None:
            raise APIError("E-CONSENT-REQUIRED", status_code=403)
        latest = self.db.get_latest_consent(norm_dev)
        if latest is None or latest.get("action") != "granted":
            raise APIError("E-CONSENT-REQUIRED", status_code=403)
        if latest.get("notice_version") != self.config.current_notice_version:
            raise APIError("E-CONSENT-STALE", status_code=403)
        return dict(latest)
