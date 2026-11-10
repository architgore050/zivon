"""Time-ordered UUIDv7 generator per RFC 9562 and db-spec.md §4."""

from __future__ import annotations

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    """Generate a time-ordered UUIDv7 (48-bit Unix epoch ms + 74 random bits)."""
    unix_ts_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand_bytes = int.from_bytes(os.urandom(10), "big")
    rand_a = (rand_bytes >> 62) & 0x0FFF
    rand_b = rand_bytes & ((1 << 62) - 1)

    uuid_int = (unix_ts_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0x2 << 62) | rand_b
    return uuid.UUID(int=uuid_int)


def uuid7_str() -> str:
    """Return a canonical lowercase string representation of a new UUIDv7."""
    return str(uuid7())
