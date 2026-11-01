"""Shared test helper: install minimal server env so load_config succeeds.

Unit tests that build a Config (but do not test config itself) call
install_server_env() in setUpClass and release_server_env(saved) in
tearDownClass. The values are dummies - these tests never make model calls.
"""

from __future__ import annotations

import os

_VARS = {
    "ZIVON_BASE_URL": "http://127.0.0.1:1/v1",
    "ZIVON_MODEL": "test-model",
}


def install_server_env() -> dict[str, str | None]:
    """Set the required server env; return the previous values for restore."""
    saved: dict[str, str | None] = {}
    for key, value in _VARS.items():
        saved[key] = os.environ.get(key)
        os.environ[key] = value
    return saved


def release_server_env(saved: dict[str, str | None]) -> None:
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
