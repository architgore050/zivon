"""Narration stage errors.

The narration stage follows the factory's no-silent-failure rule: every
deliberate failure is a NarrationError saying what broke and how to fix it.
Per-block synthesis failures are NOT errors - they are recorded outcomes
(read-aloud degrades to the INF-089 disabled copy); only configuration and
wiring problems raise.
"""

from __future__ import annotations

from ..errors import StageError


class NarrationError(StageError):
    """The narration stage cannot proceed (config, wiring, or total failure).

    Per-block outcomes (TTS failure, encode failure, budget refusal) are
    recorded in the stage output instead - a missing narration asset is a
    designed product state (read-aloud disabled for that block), never a
    reason to re-run the pipeline.
    """
