"""voice — the Zivon vocal tutor agent backend.

The product-runtime conversation loop: student speech (PTT audio frames) →
Prisma v3.0 STT (streaming) → Gemma 4 26B A4B brain via the Gemini API
(streaming) → sentence chunker → Timbre v3.0 TTS (streaming), with the tutor
speaking while the brain is still generating (the one-stream law, Gate C).

Spec: docs/specs/voice-agent/ (spec.md, ws-contract.md, latency-budget.md).
Module layout is binding (spec.md §3 / backend-spec §4.3): this package is the
sibling of factory/ and mounts into the core-backend monolith via
``mount_voice(app)`` — no separate image or k8s manifests in P0 (ADR-0020).

The only symbol the core backend imports is ``mount_voice``:

    from voice import mount_voice
    mount_voice(app)                     # defaults (in-memory session store)
    mount_voice(app, sessions=my_store)  # core-backend-owned store adapter

``mount_voice`` resolves lazily (PEP 562) so the package imports cleanly
before the WS layer is wired.
"""

from __future__ import annotations

from typing import Any

__all__ = ["mount_voice"]
__version__ = "0.1.0"


def __getattr__(name: str) -> Any:
    if name == "mount_voice":
        from .ws_api import mount_voice

        return mount_voice
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
