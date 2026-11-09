"""Stage 12-narration: pre-generate per-block lesson narration audio.

Decision C-051 (founder, 2026-11-07, ADOPTED): lesson narration is
PRE-GENERATED at build time with Gnani Timbre v3.0 and served statically -
read-aloud (F-WRP-TTS-01) consumes ZERO runtime credits and never meters a
student. This stage is the product's TTS wrapper for lesson content.

Placement: AFTER the review gates (03/04 content gate, 07/08 perf gate,
09/10 code gate) and after 11-link, so narration only ever spends credits on
a page that already passed every gate, and the audio lands directly in the
served tree.

Contracts this stage implements (gap-register.md GAP-015 - the binding
mini-spec):
- speakable-block rules per type (select.py),
- availability flag in the topic manifest.json + a per-topic
  narration-manifest.json {block_id, lang, hash, chars, duration_ms},
- ST-04 content-addressed assets: audio/{course_id}/{block_id}.{lang}.{hash}.opus
  with a text-hash key (immutable cache key; republish bumps the hash),
- the A-15 bounded build tranche (<= 1,500 credits [ASSUMPTION], separate
  from the voice-agent daily tranche) enforced refuse-before-exceed,
- per-block resumability like every factory stage: a re-triggered run skips
  blocks whose audio already exists (content addressing makes that exact),
- failures route to a bounded repair catcher (founder rule): failed blocks
  are re-attempted up to ZIVON_NARRATION_REPAIR_ROUNDS, never re-running the
  pipeline; residual failures degrade read-aloud to the INF-089 disabled
  copy for those blocks instead of failing the run.

Mock mode (no ZIVON_TIMBRE_BASE_URL, or mode=mock) produces REAL opus assets
whose audio is silence - the full pipeline path is exercised without
spending credits. Mock assets are loudly labelled in the manifests; never
publish them to the live site.
"""

from __future__ import annotations

from typing import Any

from ..artifacts import RunContext
from ..config import Config
from .env import STAGE_ID, NarrationEnv
from .errors import NarrationError


def run(cfg: Config, run_ctx: RunContext) -> dict[str, Any]:
    """One narration pass over the just-published topic.

    Reads this run's 02-generate (lesson + blocks), 05-interactive (simulation
    readout strings) and 06-render (topic dirs) artifacts; writes opus assets
    under <frontend>/audio/, updates the published topic's manifest.json and
    writes narration-manifest.json next to it. Per-block outcomes land in the
    returned output + the run's narration_usage ledger.
    """
    env = NarrationEnv.from_env()
    if not env.enabled:
        print(
            f"[{STAGE_ID}] disabled (ZIVON_NARRATION_ENABLED != true) - "
            "skipping; read-aloud stays unbuilt for this topic"
        )
        return {
            "enabled": False,
            "stage": STAGE_ID,
            "detail": "narration disabled by environment",
        }
    raise NarrationError(
        STAGE_ID,
        "narration skeleton: selection/synthesis/publish modules land in the "
        "next commits of feature/narration-stage; leave ZIVON_NARRATION_"
        "ENABLED unset until then",
    )
