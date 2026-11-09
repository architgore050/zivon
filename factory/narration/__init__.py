"""Zivon content factory - build-time narration stage (EX8-NARRATION).

Pre-generates per-block lesson narration audio with Gnani Timbre v3.0 at
build time (decision C-051): read-aloud never spends a runtime credit.
Implemented per gap-register.md GAP-015; serving contract backend-spec
ST-04; budget backend-spec A-15.
"""

from .stage import run

__all__ = ["run"]
