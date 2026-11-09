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
- availability flag + narration-manifest.json (publish.py).

Failure policy: per-block outcomes are recorded, never fatal - the product
has a designed degraded state (INF-089 disabled copy). Only two things raise:
configuration/wiring errors, and a pass where attempts were made but NOTHING
succeeded (a silent all-fail would hide a broken Timbre/ffmpeg config behind
a green run). Budget refusals are a policy outcome, not a failure.

Mock mode (no ZIVON_TIMBRE_BASE_URL, or mode=mock) produces REAL opus assets
whose audio is silence - the full pipeline path is exercised without
spending credits. Mock assets are loudly labelled in the manifests; never
publish them to the live site.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..artifacts import RunContext
from ..config import Config
from ..errors import MissingArtifactError
from . import budget as budget_mod
from .audio import (
    asset_rel_path,
    content_hash,
    encode_opus,
    probe_duration_ms,
    write_asset,
)
from .env import STAGE_ID, NarrationEnv
from .errors import NarrationError
from .select import NarrationUnit, speakable_units, spoken_text
from .timbre import LiveTimbreClient, MockTimbreClient, TimbreClient


def run(
    cfg: Config, run_ctx: RunContext, client: TimbreClient | None = None
) -> dict[str, Any]:
    """One narration pass over the just-published topic.

    Reads this run's 02-generate (lesson + blocks), 05-interactive (simulation
    readout strings) and 06-render (topic dirs) artifacts; writes opus assets
    under <frontend>/audio/ and stamps outcomes into the stage output + the
    run's narration_usage ledger + the cross-run budget file.

    client: injectable synthesis boundary for tests (the counting/mock fakes
    in testing/narration); production builds it from the resolved mode.
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

    mode = env.resolved_mode
    lang = env.langs[0]
    language = env.tts_language(lang)
    if mode == "mock":
        print(
            f"[{STAGE_ID}] MOCK MODE (no Timbre endpoint configured): assets "
            "will be silence placeholders - proof of pipeline, never for the "
            "live site"
        )
    print(
        f"[{STAGE_ID}] enabled: mode={mode} lang={lang} (TTS language "
        f"{language}) tranche={env.budget_credits:.0f} credits"
    )

    topic = _load_topic(cfg, run_ctx)
    if client is None:
        client = MockTimbreClient() if mode == "mock" else LiveTimbreClient(env)
    units = speakable_units(topic["lesson"], topic["blocks"], topic["interactive"])
    out = _narrate(env, run_ctx, client, topic, units, lang, language, mode)
    out["env"] = env.redacted()
    out["stage"] = STAGE_ID
    return out


# ---------------------------------------------------------------- inputs
def _load_topic(cfg: Config, run_ctx: RunContext) -> dict[str, Any]:
    """Load the stage's inputs + verify 11-link actually published the page.

    Narration writes into the SERVED tree, so it refuses to run against a
    topic that was never linked (the runbook path is: full run, or
    --stages 11-link,12-narration).
    """
    render_out = run_ctx.load_stage_output("06-render")
    generated = run_ctx.load_stage_output("02-generate")
    try:
        interactive = run_ctx.load_stage_output("05-interactive")
    except MissingArtifactError:
        # Readout strings are optional context (pre-CP-TRN-003 pages have
        # none); every other missing artifact is a hard stop via
        # MissingArtifactError.
        interactive = {}

    frontend_root = cfg.repo_path(cfg.paths["frontend"])
    topic_src = Path(render_out["topic_dir"])
    site_courses = Path(render_out["site_dir"]) / "courses"
    rel = topic_src.relative_to(site_courses)
    topic_dir = frontend_root / "courses" / rel
    if not (topic_dir / "manifest.json").exists():
        raise NarrationError(
            STAGE_ID,
            f"the published topic {topic_dir} has no manifest.json - stage "
            "11-link must run before 12-narration (full run, or "
            "--stages 11-link,12-narration; see the runbook)",
        )
    return {
        "frontend_root": frontend_root,
        "topic_dir": topic_dir,
        "course_id": render_out["manifest"]["course_id"],
        "lesson": generated["lesson"],
        "blocks": generated["blocks"],
        "interactive": interactive,
    }


# ------------------------------------------------------------- narration
def _narrate(
    env: NarrationEnv,
    run_ctx: RunContext,
    client: TimbreClient,
    topic: dict[str, Any],
    units: list[NarrationUnit],
    lang: str,
    language: str,
    mode: str,
) -> dict[str, Any]:
    """Synthesize every speakable unit with budget + resume + repair.

    Per-block state machine: pending -> narrated | skipped-existing |
    budget-refused | failed; failed -> repair rounds -> narrated | failed.
    """
    frontend_root: Any = topic["frontend_root"]
    course_id: str = topic["course_id"]
    state = budget_mod.load_state(run_ctx.runs_dir, env)

    records: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    refused: list[dict[str, Any]] = []
    repaired: list[str] = []
    status: dict[str, str] = {}
    total_chars = 0
    run_credits = 0.0
    attempts_base = run_ctx.attempts_dir(STAGE_ID)

    def synth(unit: NarrationUnit, pass_dir: Path) -> str:
        """One synthesis attempt. Returns the final status and updates the
        per-block records/errors; every attempt leaves request/meta evidence
        on disk (the llm attempts convention, no secrets in either file)."""
        nonlocal total_chars, run_credits
        text = spoken_text(unit)
        hash_ = content_hash(lang, env.timbre_voice, text)
        rel_path = asset_rel_path(course_id, unit.block_id, lang, hash_)
        target = frontend_root / rel_path
        est = budget_mod.estimate_credits(len(text), env)
        pass_dir.mkdir(parents=True, exist_ok=True)
        _write_json(
            pass_dir / "request.json",
            {
                "block_id": unit.block_id,
                "kind": unit.kind,
                "chars": len(text),
                "language": language,
                "voice": env.timbre_voice or "(provider default)",
                "mode": mode,
                "format": "ogg-opus",
            },
        )

        if target.exists():
            # Content-addressed resume: the exact asset for this spoken form
            # is already published. Zero credits, zero re-encode.
            duration = probe_duration_ms(target.read_bytes())
            records[unit.block_id] = {
                "block_id": unit.block_id,
                "path": rel_path,
                "hash": hash_,
                "chars": len(text),
                "credits": 0.0,
                "duration_ms": duration,
                "bytes": target.stat().st_size,
                "outcome": "skipped-existing",
            }
            _write_json(
                pass_dir / "meta.json",
                {
                    "outcome": "skipped-existing",
                    "rel_path": rel_path,
                    "hash": hash_,
                    "duration_ms": duration,
                },
            )
            return "skipped"

        if budget_mod.would_exceed(state, est):
            refused.append({"block_id": unit.block_id, "est_credits": est})
            _write_json(
                pass_dir / "meta.json",
                {
                    "outcome": "budget-refused",
                    "est_credits": est,
                    "detail": budget_mod.refusal_message(state, est),
                },
            )
            return "refused"

        t0 = time.monotonic()
        try:
            result = client.synthesize(text, language)
            opus = encode_opus(result.audio, result.content_type)
        except NarrationError as exc:
            errors[unit.block_id] = str(exc)[:400]
            _write_json(
                pass_dir / "meta.json",
                {
                    "outcome": "failed",
                    "error": str(exc)[:400],
                    "latency_s": round(time.monotonic() - t0, 2),
                },
            )
            return "failed"

        write_asset(frontend_root, rel_path, opus)
        duration = probe_duration_ms(opus)
        budget_mod.spend(state, est)
        budget_mod.save_state(
            run_ctx.runs_dir, state
        )  # crash-safe: the spend is on the ledger
        total_chars += len(text)
        run_credits += est
        records[unit.block_id] = {
            "block_id": unit.block_id,
            "path": rel_path,
            "hash": hash_,
            "chars": len(text),
            "credits": round(est, 4),
            "duration_ms": duration,
            "bytes": len(opus),
            "outcome": "narrated",
        }
        _write_json(
            pass_dir / "meta.json",
            {
                "outcome": "narrated",
                "rel_path": rel_path,
                "hash": hash_,
                "bytes": len(opus),
                "duration_ms": duration,
                "credits": round(est, 4),
                "tts_latency_s": result.latency_s,
                "tts_attempts": result.attempts,
                "content_type": result.content_type,
                "latency_s": round(time.monotonic() - t0, 2),
            },
        )
        return "narrated"

    # ---- first pass ------------------------------------------------------
    for unit in units:
        status[unit.block_id] = synth(unit, attempts_base / unit.block_id / "pass-00")

    # ---- bounded repair catcher (founder rule: never re-run the pipeline) --
    failed_units = [u for u in units if status[u.block_id] == "failed"]
    round_no = 0
    while failed_units and round_no < env.repair_rounds:
        round_no += 1
        print(
            f"[{STAGE_ID}] repair round {round_no}/{env.repair_rounds}: "
            f"re-attempting {len(failed_units)} failed block(s)"
        )
        still_failed: list[NarrationUnit] = []
        for unit in failed_units:
            outcome = synth(
                unit, attempts_base / unit.block_id / f"repair-{round_no:02d}"
            )
            status[unit.block_id] = outcome
            if outcome == "failed":
                still_failed.append(unit)
            elif outcome == "narrated":
                repaired.append(unit.block_id)
            elif outcome == "refused":
                pass  # the tranche ran out mid-repair: stays refused
        failed_units = still_failed

    # ---- outcome roll-up ---------------------------------------------------
    narrated = [r for r in records.values() if r["outcome"] == "narrated"]
    skipped = [r for r in records.values() if r["outcome"] == "skipped-existing"]
    failed = [
        {"block_id": u.block_id, "error": errors[u.block_id]} for u in failed_units
    ]
    known_durations = [
        r["duration_ms"] for r in records.values() if isinstance(r["duration_ms"], int)
    ]
    if units and not narrated and not skipped and failed:
        raise NarrationError(
            STAGE_ID,
            f"narration attempted {len(units)} block(s) and NONE succeeded "
            f"after {round_no} repair round(s) - first error: "
            f"{failed[0]['error']} This is a total synthesis failure (Timbre "
            "endpoint/ffmpeg), not a block problem: fix the configuration "
            "and re-trigger the run - completed stages resume, narration "
            "re-runs with a fresh budget view.",
            artifacts_dir=str(run_ctx.stage_dir(STAGE_ID)),
        )

    run_ctx.append_ledger(
        "narration_usage",
        [
            {
                "block_id": r["block_id"],
                "outcome": r["outcome"],
                "hash": r["hash"],
                "chars": r["chars"],
                "credits": r["credits"],
                "duration_ms": r["duration_ms"],
                "mode": mode,
            }
            for r in records.values()
        ]
        + [
            {
                "block_id": r["block_id"],
                "outcome": "budget-refused",
                "est_credits": r["est_credits"],
                "mode": mode,
            }
            for r in refused
        ]
        + [
            {
                "block_id": f["block_id"],
                "outcome": "failed",
                "error": f["error"],
                "mode": mode,
            }
            for f in failed
        ],
    )
    budget_mod.record_run_usage(
        state,
        run_ctx.run_id,
        mode=mode,
        chars=total_chars,
        credits=run_credits,
        narrated=len(narrated),
        failed=len(failed),
        refused=len(refused),
    )
    budget_mod.save_state(run_ctx.runs_dir, state)

    print(
        f"[{STAGE_ID}] done: narrated={len(narrated)} skipped={len(skipped)} "
        f"failed={len(failed)} refused={len(refused)} "
        f"credits={run_credits:.2f} chars={total_chars}"
        + (f" (repaired: {', '.join(repaired)})" if repaired else "")
    )
    if refused:
        print(
            f"[{STAGE_ID}] {budget_mod.refusal_message(state, refused[0]['est_credits'])}"
        )
    if failed:
        print(
            f"[{STAGE_ID}] WARNING: {len(failed)} block(s) have no audio - "
            "read-aloud shows the INF-089 disabled copy for them"
        )

    assets = [records[u.block_id] for u in units if u.block_id in records]
    return {
        "enabled": True,
        "mode": mode,
        "langs": list(env.langs),
        "course_id": course_id,
        "narrated": len(narrated),
        "skipped_existing": len(skipped),
        "failed": failed,
        "refused": refused,
        "repaired": repaired,
        "chars": total_chars,
        "credits": round(run_credits, 4),
        "duration_ms_total": sum(known_durations) if known_durations else None,
        "assets": assets,
        "manifest_updated": False,
        "budget_file": str(budget_mod.budget_path(run_ctx.runs_dir)),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
