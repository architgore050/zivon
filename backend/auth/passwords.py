"""Password hashing and password policy for account identities (ADR-0029).

Argon2id is the only scheme this module produces. Parameters are the OWASP
baseline (m=64 MiB, t=3, p=4) and are constants, not env knobs: a runtime knob
invites a weaker deployment. The parameters travel inside the encoded hash, so
raising them later keeps every existing hash verifiable.
"""

from __future__ import annotations

import hmac
from typing import Final

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

PASSWORD_MIN_LENGTH: Final[int] = 10
PASSWORD_MAX_LENGTH: Final[int] = 128

# The one hasher. `argon2-cffi` re-hashes on `check_needs_rehash` if the
# parameters ever change; the auth service does that opportunistically.
HASHER: Final[PasswordHasher] = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)

# A real Argon2id hash of a throwaway string. Login verifies an unknown email
# against this so an attacker cannot tell "no such account" from "wrong
# password" by response time (no account enumeration, REQUIREMENTS §6.3).
_DUMMY_HASH: Final[str] = (
    "$argon2id$v=19$m=65536,t=3,p=4$Byfix86eL6UmSxO8iM0SFg$"
    "sEoQCh5bh+cHvR0MQmp4mTrllU/JTvXFBmClKWtQFto"
)

# Deliberately small, static list of the passwords that dominate credential
# stuffing. It is not a full breach corpus (that needs a service); it blocks the
# free hits without shipping a multi-megabyte file.
COMMON_PASSWORDS: Final[frozenset[str]] = frozenset(
    {
        "1234567890",
        "123456789",
        "12345678",
        "1111111111",
        "0000000000",
        "password1",
        "password12",
        "password123",
        "passw0rd",
        "p@ssw0rd",
        "qwertyuiop",
        "qwerty123",
        "1q2w3e4r5t",
        "abc123456",
        "iloveyou1",
        "letmein123",
        "welcome123",
        "admin12345",
        "administrator",
        "changeme123",
        "football123",
        "sunshine123",
        "princess123",
        "dragon123",
        "monkey123",
        "trustno1",
        "starwars123",
        "whatever123",
        "zaq12wsx",
        "asdfghjkl",
        "physics123",
        "zivon12345",
        "student123",
        "india12345",
        "maharashtra",
    }
)


def hash_password(password: str) -> str:
    """Return a fresh Argon2id hash (unique salt per call)."""
    return HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Constant-time-ish verification; never raises on a bad hash or mismatch."""
    try:
        return HASHER.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def burn_password_check(password: str) -> None:
    """Perform a verification against the dummy hash (timing equalization)."""
    verify_password(_DUMMY_HASH, password)


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return HASHER.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def password_problem(password: str, *, email: str | None = None) -> str | None:
    """Return a stable reason code for a rejected password, or None if valid.

    Codes are contract (the frontend maps them to localized copy): ``too_short``,
    ``too_long``, ``too_common``, ``too_simple``, ``too_predictable``.
    """
    if len(password) < PASSWORD_MIN_LENGTH:
        return "too_short"
    if len(password) > PASSWORD_MAX_LENGTH:
        return "too_long"
    folded = password.casefold()
    if folded in COMMON_PASSWORDS:
        return "too_common"
    if len(set(password)) == 1:
        return "too_simple"
    if email:
        local = email.split("@", 1)[0].strip().casefold()
        if len(local) >= 3 and (folded == local or folded == email.casefold()):
            return "too_predictable"
    return None


def same_secret(left: str, right: str) -> bool:
    """Constant-time comparison for short secrets (CSRF/token equality)."""
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
