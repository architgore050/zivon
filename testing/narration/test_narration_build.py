"""The mock-mode narration build over a golden topic (the GAP-015 done-
criterion): opus assets + availability inputs + resume + budget + repair.

Real RunContext (run artifacts on disk), real ffmpeg encode path, fake
synthesis client (deterministic silence) - the same split the repo's
integration suite uses vs the mock inference server.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from factory.artifacts import RunContext
from factory.config import Config
from factory.narration.audio import content_hash, is_opus
from factory.narration.errors import NarrationError
from factory.narration.select import speakable_units, spoken_text
from factory.narration.timbre import SynthesisResult, TimbreClient, _silence_wav

from .narration_env import install_narration_env, release_narration_env


# ----------------------------------------------------------------- fakes
class FakeTimbreClient(TimbreClient):
    """Deterministic mock with call counting + text-marker failures."""

    def __init__(self, fail_markers: dict[str, int] | None = None):
        self.calls: list[tuple[str, str]] = []
        # marker -> remaining failures (a text containing the marker fails
        # while its counter is > 0, then succeeds)
        self.fail_markers = dict(fail_markers or {})

    def synthesize(self, text: str, language: str) -> SynthesisResult:
        self.calls.append((text, language))
        for marker, remaining in list(self.fail_markers.items()):
            if marker in text and remaining > 0:
                self.fail_markers[marker] = remaining - 1
                raise NarrationError("12-narration", f"injected failure for {marker!r}")
        return SynthesisResult(
            audio=_silence_wav(0.2),
            content_type="audio/wav",
            latency_s=0.01,
            attempts=1,
        )


# --------------------------------------------------------------- fixture
def _lesson() -> dict:
    return {
        "title": "Motion",
        "objectives": ["Describe speed", "Use v = distance / time"],
        "glossary": [{"term": "speed", "definition": "distance per unit time"}],
    }


def _blocks() -> dict:
    return {
        "blocks": [
            {
                "id": "b-01",
                "type": "text",
                "spec": {
                    "paragraphs": [
                        "Speed tells us how fast.",
                        "Velocity adds direction.",
                    ]
                },
                "citations": [],
            },
            {
                "id": "b-02",
                "type": "worked_example",
                "spec": {
                    "problem": "A car covers 100 m in 20 s.",
                    "steps": [
                        {
                            "title": "Apply the formula",
                            "detail": "100 m / 20 s = 5 m/s.",
                        }
                    ],
                    "answer": "5 m/s",
                },
                "citations": [],
            },
            {
                "id": "b-03",
                "type": "check",
                "spec": {
                    "question": "Which has direction?",
                    "format": "mcq",
                    "options": ["Speed", "Velocity"],
                    "answer_index": 1,
                    "answer": "Velocity",
                    "explanation": "Velocity is a vector.",
                },
                "citations": [],
            },
            {
                "id": "b-04",
                "type": "simulation",
                "spec": {
                    "title": "Uniform motion",
                    "description": "Drag the speed slider.",
                    "controls": [
                        {
                            "id": "a",
                            "label": "speed",
                            "min": 0,
                            "max": 5,
                            "step": 1,
                            "initial": 1,
                        }
                    ],
                },
                "citations": [],
            },
            {
                "id": "b-05",
                "type": "reveal",
                "spec": {"title": "Why?", "steps": []},
                "citations": [],
            },
            {
                "id": "b-06",
                "type": "diagram",
                "spec": {"svg": "<svg></svg>", "caption": "graph"},
                "citations": [],
            },
        ]
    }


class NarrationBuildBase(unittest.TestCase):
    """Fixture wiring shared by the build tests."""

    def setUp(self):
        self.saved_env = install_narration_env(
            enabled=True,
            extra={
                "ZIVON_NARRATION_MODE": "mock",
                "ZIVON_TIMBRE_BACKOFF_BASE_S": "0",
            },
        )
        self.tmp = Path(tempfile.mkdtemp(prefix="zivon-narrbuild-"))
        self.runs_dir = self.tmp / "runs"
        self.frontend = self.tmp / "frontend"
        self.run_ctx = RunContext(self.runs_dir, "motion-c9")
        self._seed_run_artifacts()
        self._seed_published_topic()
        self.cfg = self._cfg()

    def tearDown(self):
        release_narration_env(self.saved_env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _cfg(self) -> Config:
        return Config(
            data={
                "learner": {"language": "en"},
                "retrieval": {},
                "limits": {},
                "paths": {"frontend": str(self.frontend), "runs": str(self.runs_dir)},
                "perf": {},
                "repair": {},
                "stage_overrides": {},
            },
            server={},
            root=self.tmp,
        )

    def _seed_run_artifacts(self):
        topic_dir = f"{self.tmp}/staging/courses/class-9-physics/motion"
        self.run_ctx.save_stage_output(
            "06-render",
            {
                "topic_dir": topic_dir,
                "site_dir": f"{self.tmp}/staging",
                "manifest": {"course_id": "class-9-physics"},
            },
        )
        self.run_ctx.save_stage_output(
            "02-generate", {"lesson": _lesson(), "blocks": _blocks()}
        )
        self.run_ctx.save_stage_output(
            "05-interactive",
            {
                "b-04": {
                    "files": {"page.js": 'ctx.t_str("readout", "Position updated");'}
                }
            },
        )

    def _seed_published_topic(self):
        topic = self.frontend / "courses" / "class-9-physics" / "motion"
        topic.mkdir(parents=True, exist_ok=True)
        (topic / "manifest.json").write_text(
            json.dumps({"course_id": "class-9-physics", "title": "Motion"}),
            encoding="utf-8",
        )

    def _expected_units(self) -> list:
        return speakable_units(
            _lesson(),
            _blocks(),
            {
                "b-04": {
                    "files": {"page.js": 'ctx.t_str("readout", "Position updated");'}
                }
            },
        )


class TestMockNarrationBuild(NarrationBuildBase):
    """The done-criterion: a mock-mode narration build over a golden topic
    produces opus assets + per-block records ready for the availability flag."""

    def test_build_produces_valid_opus_assets(self):
        from factory.narration import run as run_narration

        out = run_narration(self.cfg, self.run_ctx)
        self.assertTrue(out["enabled"])
        self.assertEqual(out["mode"], "mock")
        self.assertEqual(out["narrated"], 5)  # meta + 4 speakable blocks
        self.assertEqual(out["skipped_existing"], 0)
        self.assertEqual(out["failed"], [])
        self.assertEqual(out["refused"], [])
        audio_dir = self.frontend / "audio" / "class-9-physics"
        files = sorted(p.name for p in audio_dir.iterdir())
        self.assertEqual(len(files), 5)
        for name in files:
            self.assertRegex(name, r"^b-\d{2}(-meta)?\.en\.[0-9a-f]{16}\.opus$")
            self.assertTrue(is_opus((audio_dir / name).read_bytes()))

    def test_assets_match_content_hashes_and_spoken_text(self):
        from factory.narration import run as run_narration

        out = run_narration(self.cfg, self.run_ctx)
        units = self._expected_units()
        for unit, asset in zip(units, out["assets"]):
            text = spoken_text(unit)
            self.assertEqual(asset["hash"], content_hash("en", "", text))
            self.assertEqual(asset["chars"], len(text))
            expected_name = f"{unit.block_id}.en.{asset['hash']}.opus"
            self.assertTrue((self.frontend / asset["path"]).name == expected_name)
            self.assertGreater(asset["bytes"], 0)
            self.assertTrue(asset["duration_ms"] is None or asset["duration_ms"] > 0)

    def test_check_answers_never_reach_the_tts(self):
        from factory.narration import run as run_narration

        client = FakeTimbreClient()
        run_narration(self.cfg, self.run_ctx, client=client)
        spoken = " ".join(text for text, _ in client.calls)
        self.assertIn("Which has direction?", spoken)
        self.assertNotIn("Velocity is a vector", spoken)  # explanation excluded
        self.assertNotIn(
            "vectors vs scalars", spoken
        )  # expected_understanding excluded
        # The worked example's answer IS speakable teaching content, but the
        # check's own answer never leaves the selection module.
        self.assertNotIn("answer_index", spoken)

    def test_budget_ledger_and_usage_are_recorded(self):
        from factory.narration import run as run_narration

        out = run_narration(self.cfg, self.run_ctx)
        budget_file = self.runs_dir / "narration-budget.json"
        self.assertTrue(budget_file.exists())
        state = json.loads(budget_file.read_text(encoding="utf-8"))
        self.assertAlmostEqual(state["total_credits_used"], out["credits"], places=3)
        self.assertEqual(state["runs"][0]["run_id"], "motion-c9")
        self.assertEqual(state["runs"][0]["narrated"], 5)
        ledger = self.runs_dir / "motion-c9" / "narration_usage.jsonl"
        lines = [json.loads(line) for line in ledger.read_text().splitlines()]
        self.assertEqual(len(lines), 5)
        self.assertTrue(all(entry["outcome"] == "narrated" for entry in lines))
        # credits are per-character estimates over the assembled spoken form
        self.assertAlmostEqual(
            out["credits"], sum(a["credits"] for a in out["assets"]), places=3
        )

    def test_attempt_evidence_on_disk(self):
        from factory.narration import run as run_narration

        run_narration(self.cfg, self.run_ctx)
        base = self.runs_dir / "motion-c9" / "12-narration" / "attempts"
        for unit in self._expected_units():
            request = json.loads(
                (base / unit.block_id / "pass-00" / "request.json").read_text()
            )
            meta = json.loads(
                (base / unit.block_id / "pass-00" / "meta.json").read_text()
            )
            self.assertEqual(request["mode"], "mock")
            self.assertNotIn("api_key", request)
            self.assertEqual(meta["outcome"], "narrated")
            self.assertGreater(meta["bytes"], 0)


class TestPerBlockResume(NarrationBuildBase):
    def test_second_run_skips_every_completed_block(self):
        from factory.narration import run as run_narration

        first = run_narration(self.cfg, self.run_ctx, client=FakeTimbreClient())
        self.assertEqual(first["narrated"], 5)

        client2 = FakeTimbreClient()
        second = run_narration(self.cfg, self.run_ctx, client=client2)
        self.assertEqual(second["narrated"], 0)
        self.assertEqual(second["skipped_existing"], 5)
        self.assertEqual(client2.calls, [])  # zero synthesis, zero credits
        self.assertEqual(second["credits"], 0.0)
        state = json.loads((self.runs_dir / "narration-budget.json").read_text())
        self.assertAlmostEqual(state["total_credits_used"], first["credits"], places=3)

    def test_changed_text_bumps_the_hash_and_renarrates(self):
        from factory.narration import run as run_narration

        run_narration(self.cfg, self.run_ctx, client=FakeTimbreClient())
        # One paragraph changes -> new content hash for b-01 only.
        revised = _blocks()
        revised["blocks"][0]["spec"]["paragraphs"] = [
            "Speed tells us how fast, now revised."
        ]
        self.run_ctx.save_stage_output(
            "02-generate", {"lesson": _lesson(), "blocks": revised}
        )
        second = run_narration(self.cfg, self.run_ctx, client=FakeTimbreClient())
        # b-01 re-narrated; the other four units still resolve to existing assets.
        self.assertEqual(second["narrated"], 1)
        self.assertEqual(second["skipped_existing"], 4)
        names = [
            Path(a["path"]).name for a in second["assets"] if a["outcome"] == "narrated"
        ]
        self.assertTrue(names[0].startswith("b-01.en."))


class TestBudgetGuardInBuild(NarrationBuildBase):
    def test_refusal_stops_before_exceeding_and_is_resumable(self):
        from factory.narration import run as run_narration

        # Budget 2.5 fits exactly the first two units of this fixture at the
        # default 0.0167 credits/char (deterministic spoken-form lengths).
        saved = os.environ.get("ZIVON_NARRATION_BUDGET_CREDITS")
        os.environ["ZIVON_NARRATION_BUDGET_CREDITS"] = "2.5"
        try:
            out = run_narration(self.cfg, self.run_ctx, client=FakeTimbreClient())
        finally:
            if saved is None:
                os.environ.pop("ZIVON_NARRATION_BUDGET_CREDITS", None)
            else:
                os.environ["ZIVON_NARRATION_BUDGET_CREDITS"] = saved
        self.assertEqual(out["narrated"], 2)  # deterministic prefix
        self.assertEqual(len(out["refused"]), 3)
        self.assertLessEqual(out["credits"], 6.0)
        state = json.loads((self.runs_dir / "narration-budget.json").read_text())
        self.assertLessEqual(state["total_credits_used"], 6.0)

        # Raising the tranche + re-trigger: only the remainder synthesizes.
        os.environ["ZIVON_NARRATION_BUDGET_CREDITS"] = "60.0"
        try:
            out2 = run_narration(self.cfg, self.run_ctx, client=FakeTimbreClient())
        finally:
            if saved is None:
                os.environ.pop("ZIVON_NARRATION_BUDGET_CREDITS", None)
            else:
                os.environ["ZIVON_NARRATION_BUDGET_CREDITS"] = saved
        self.assertEqual(out2["narrated"], 3)
        self.assertEqual(out2["skipped_existing"], 2)
        self.assertEqual(out2["refused"], [])

    def test_zero_budget_refuses_everything_without_failing(self):
        from factory.narration import run as run_narration

        saved = os.environ.get("ZIVON_NARRATION_BUDGET_CREDITS")
        os.environ["ZIVON_NARRATION_BUDGET_CREDITS"] = "0"
        try:
            out = run_narration(self.cfg, self.run_ctx, client=FakeTimbreClient())
        finally:
            if saved is None:
                os.environ.pop("ZIVON_NARRATION_BUDGET_CREDITS", None)
            else:
                os.environ["ZIVON_NARRATION_BUDGET_CREDITS"] = saved
        self.assertEqual(out["narrated"], 0)
        self.assertEqual(len(out["refused"]), 5)
        self.assertEqual(out["failed"], [])


class TestRepairCatcher(NarrationBuildBase):
    def test_failed_block_is_repaired_within_the_bound(self):
        from factory.narration import run as run_narration

        # "Velocity adds direction" fails twice (pass-00 + repair-01), then lands.
        client = FakeTimbreClient(fail_markers={"Velocity adds direction": 2})
        out = run_narration(self.cfg, self.run_ctx, client=client)
        self.assertIn("b-01", out["repaired"])
        self.assertEqual(out["narrated"], 5)
        velocity_calls = [t for t, _ in client.calls if "Velocity adds direction" in t]
        self.assertEqual(len(velocity_calls), 3)  # 1 pass + 2 repair rounds

    def test_unrepairable_block_degrades_not_fails(self):
        from factory.narration import run as run_narration

        client = FakeTimbreClient(fail_markers={"Velocity adds direction": 99})
        out = run_narration(self.cfg, self.run_ctx, client=client)
        self.assertEqual(out["narrated"], 4)
        self.assertEqual([f["block_id"] for f in out["failed"]], ["b-01"])
        self.assertIn("injected failure", out["failed"][0]["error"])
        # The missing block is simply absent from the assets: unavailable.
        self.assertNotIn("b-01", [a["block_id"] for a in out["assets"]])

    def test_total_failure_raises_loudly(self):
        from factory.narration import run as run_narration

        class AlwaysFails(TimbreClient):
            def synthesize(self, text: str, language: str) -> SynthesisResult:
                raise NarrationError("12-narration", "Timbre down")

        with self.assertRaises(NarrationError) as ctx:
            run_narration(self.cfg, self.run_ctx, client=AlwaysFails())
        self.assertIn("NONE succeeded", str(ctx.exception))


class TestWiring(NarrationBuildBase):
    def test_missing_published_manifest_raises_with_guidance(self):
        from factory.narration import run as run_narration

        (
            self.frontend / "courses" / "class-9-physics" / "motion" / "manifest.json"
        ).unlink()
        with self.assertRaises(NarrationError) as ctx:
            run_narration(self.cfg, self.run_ctx, client=FakeTimbreClient())
        self.assertIn("11-link", str(ctx.exception))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
