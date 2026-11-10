"""Shared narration-test helper: install/restore the narration env vars.

Mirrors testing/content_factory/unit/_server_env.py. The narration stage is
opt-in; tests opt in per class and restore the caller's environment on
teardown so suites stay order-independent.
"""

from __future__ import annotations

import os

_BASE = {
    "ZIVON_BASE_URL": "http://127.0.0.1:1/v1",
    "ZIVON_MODEL": "test-model",
}


def install_narration_env(
    enabled: bool = True, extra: dict[str, str] | None = None
) -> dict[str, str | None]:
    """Set the server + narration env; return previous values for restore."""
    saved: dict[str, str | None] = {}
    merged: dict[str, str] = dict(_BASE)
    merged["ZIVON_NARRATION_ENABLED"] = "true" if enabled else "false"
    if extra:
        merged.update(extra)
    for key, value in merged.items():
        saved[key] = os.environ.get(key)
        os.environ[key] = value
    return saved


def release_narration_env(saved: dict[str, str | None]) -> None:
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
