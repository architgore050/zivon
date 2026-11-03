"""End-to-end integration tests: the FULL pipeline against the mock server.

Graph v2 coverage (the production code path, real orchestrator via
subprocess, real Chromium for the performance gate):

    fixture PDFs (file://) -> ingest -> locate -> 02-generate (ONE giant
    call) -> 03-check -> 05-interactive -> 06-render -> 07-perf -> 08-fixloop
    -> 09-review -> 11-link

plus the graph-v2 guarantees the founder decision demands:
- a gate failure routes to ITS catcher (04-repair / 10-reviewfix), bounded,
  and the run never re-runs upstream stages;
- re-triggering the same run id RESUMES (completed stages are not re-derived);
- the fingerprint guard refuses to mix artifacts from different run shapes.

Run:  python -m unittest testing.content_factory.integration.test_end_to_end
Needs: playwright chromium installed (`python -m playwright install chromium`).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from testing.content_factory.mocks import openai_mock
from testing.content_factory.mocks.openai_mock import start_mock

PDFS = REPO_ROOT / "testing" / "content_factory" / "mocks" / "fixtures" / "pdfs"
DEFAULT_FIXTURES = REPO_ROOT / "testing" / "content_factory" / "mocks" / "fixtures"


def chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            b.close()
        return True
    except Exception:  # noqa: BLE001 — probe: any failure just means "not available"
        return False


def _build_env(tmp: Path) -> tuple[Path, Path]:
    """Stage the fixture world into a tmp dir (production layout) and write
    the test config. Returns (config_path, frontend_dir)."""
    for book, files in (
        ("fixture-ncert-9", ["prelims.pdf", "ch01.pdf", "ch02.pdf"]),
        ("alt-open-physics", ["alt-open-physics.pdf"]),
    ):
        dest = tmp / "pdfs" / book
        dest.mkdir(parents=True, exist_ok=True)
        for f in files:
            shutil.copy(PDFS / f, dest / f)

    # link stage must not touch the real repo
    frontend = tmp / "frontend"
    frontend.mkdir()
    shutil.copytree(REPO_ROOT / "frontend" / "assets", frontend / "assets")
    shutil.copy2(REPO_ROOT / "frontend" / "index.html", frontend / "index.html")
    shutil.copy2(REPO_ROOT / "frontend" / "courses.js", frontend / "courses.js")

    catalog = {
        "version": 1,
        "books": [
            {
                "id": "fixture-ncert-9",
                "class": 9,
                "subject": "science",
                "title": "Fixture Science Class 9",
                "publisher": "fixture",
                "license": "test",
                "is_ncert": True,
                "download": "auto",
                "prelims_url": (
                    tmp / "pdfs" / "fixture-ncert-9" / "prelims.pdf"
                ).as_uri(),
                "chapter_url_template": (
                    tmp / "pdfs" / "fixture-ncert-9" / "ch{nn}.pdf"
                ).as_uri(),
                "chapter_numbers": [1, 2],
                "chapters_verified": True,
                "class_evidence": ["class 9"],
            },
            {
                "id": "alt-open-physics",
                "class": 9,
                "subject": "physics",
                "title": "Open Physics Notes (fixture)",
                "publisher": "fixture",
                "license": "CC-BY (fixture)",
                "is_ncert": False,
                "download": "auto",
                "prelims_url": (
                    tmp / "pdfs" / "alt-open-physics" / "alt-open-physics.pdf"
                ).as_uri(),
                "chapter_url_template": (
                    tmp / "pdfs" / "alt-open-physics" / "alt-open-physics.pdf"
                ).as_uri(),
                "chapter_numbers": [1],
                "chapters_verified": True,
                "class_evidence": [],
            },
        ],
    }
    (tmp / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")

    # design doctrine copy (02/05/09 inject it live at build time)
    doctrine_dir = tmp / "docs" / "frontend"
    doctrine_dir.mkdir(parents=True)
    for p in (REPO_ROOT / "docs" / "frontend").glob("design-doctrine*"):
        shutil.copy2(p, doctrine_dir / p.name)

    base = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
    base["paths"].update(
        {
            "catalog": str(tmp / "catalog.json"),
            "pdf_cache": str(tmp / "pdfs"),
            "text_cache": str(tmp / "cache"),
            "runs": str(tmp / "runs"),
            "frontend": str(frontend),
        }
    )
    base["perf"]["profile"] = str(
        REPO_ROOT
        / "testing"
        / "content_factory"
        / "perf"
        / "profiles"
        / "mid-laptop.json"
    )
    config_path = tmp / "config.json"
    config_path.write_text(json.dumps(base), encoding="utf-8")
    return config_path, frontend


class TestEndToEnd(unittest.TestCase):
    tmp: Path  # set in setUpClass
    server: Any = None  # set in setUpClass
    base_url: str = ""  # set in setUpClass
    state: Any = None  # mock server call record, set in setUpClass

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="zivon-e2e-"))
        cls.server, cls.base_url, cls.state = start_mock()
        cls.config_path, cls.frontend = _build_env(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        if cls.server:
            cls.server.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _pipeline_env(self, **over):
        env = dict(os.environ)
        env["ZIVON_CONFIG"] = str(self.config_path)
        # server settings are env-only now
        env["ZIVON_BASE_URL"] = self.base_url
        env["ZIVON_MODEL"] = "mock-model"
        env["ZIVON_API_KEY"] = "test-key"
        env.update(over)
        return env

    def _run(self, *args: str, env: dict | None = None):
        return subprocess.run(
            [sys.executable, "pipeline.py", *args],
            cwd=REPO_ROOT,
            env=env or self._pipeline_env(),
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )

    @unittest.skipUnless(chromium_available(), "playwright chromium not installed")
    def test_full_run_motion(self):
        result = self._run("Motion", "--run-id", "e2e-motion")
        self.assertEqual(
            result.returncode,
            0,
            f"pipeline failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}",
        )

        runs = self.tmp / "runs" / "e2e-motion"
        status = json.loads((runs / "status.json").read_text(encoding="utf-8"))
        # happy path: every stage ok, catchers 04-repair / 10-reviewfix never ran
        self.assertEqual(
            set(status["stages"]),
            {
                "00-ingest",
                "01-locate",
                "02-generate",
                "03-check",
                "05-interactive",
                "06-render",
                "07-perf",
                "08-fixloop",
                "09-review",
                "11-link",
            },
        )
        for stage, entry in status["stages"].items():
            self.assertEqual(entry["state"], "ok", stage)

        # observability (2026-11-04): the log must show the stage heartbeats and
        # every stage's measured duration; the run report must aggregate them.
        self.assertIn("[02-generate] starting", result.stdout)
        self.assertIn("model call started", result.stdout)
        self.assertIn("model call finished in", result.stdout)
        for stage, entry in status["stages"].items():
            self.assertIn("elapsed_s", entry, stage)
        report = json.loads((runs / "run_report.json").read_text(encoding="utf-8"))
        self.assertIn("02-generate", report["stage_durations_s"])
        self.assertIsNotNone(report.get("started_at"))

        # the page was linked into the frontend and listed in courses.js
        courses_text = (self.frontend / "courses.js").read_text(encoding="utf-8")
        self.assertIn("courses/class-9-physics/", courses_text)
        payload = json.loads(courses_text.split("=", 1)[1].strip().rstrip(";"))
        self.assertTrue(payload, "courses.js is empty")
        href = payload[0]["href"]
        page = self.frontend / href
        self.assertTrue(page.exists(), f"linked page missing: {href}")
        self.assertEqual(payload[0]["chapter"], "Motion")
        html = page.read_text(encoding="utf-8")
        self.assertIn("Content-Security-Policy", html)
        self.assertIn('data-sim-id="b-06"', html)
        self.assertIn("<svg", html)
        manifest = json.loads(
            (page.parent / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["chapter"]["title"], "Motion")
        self.assertEqual(manifest["sources"][0]["title"], "Fixture Science Class 9")

        # generated page makes no external calls (hard guarantee, re-checked here)
        for name in ["index.html", "page.js", "page.css"]:
            f = page.parent / name
            if f.exists():
                content = f.read_text(encoding="utf-8")
                for marker in ("eval(", "fetch(", "new Function"):
                    self.assertNotIn(marker, content)

        # the model calls for the whole graph, counted: one giant generation
        # call (with one scripted schema retry), one check, one sim build,
        # one review - and zero catchers.
        stages_used = [s["stage"] for s in self.state.served]
        self.assertEqual(
            stages_used.count("02-generate"),
            2,
            "expected one schema retry on 02-generate (attempt-1 fixture is invalid)",
        )
        self.assertEqual(stages_used.count("03-check"), 1)
        self.assertEqual(stages_used.count("05-interactive"), 1)
        self.assertEqual(stages_used.count("09-review"), 1)
        self.assertEqual(stages_used.count("04-repair"), 0)
        self.assertEqual(stages_used.count("10-reviewfix"), 0)

        report = json.loads((runs / "run_report.json").read_text(encoding="utf-8"))
        self.assertTrue(report["ok"])

    @unittest.skipUnless(chromium_available(), "playwright chromium not installed")
    def test_resume_reuses_completed_stages(self):
        """Re-triggering the same run id must NOT re-derive completed stages."""
        first = self._run("Motion", "--run-id", "e2e-resume")
        self.assertEqual(first.returncode, 0, first.stderr)

        def served_count(stage: str) -> int:
            return sum(1 for s in self.state.served if s["stage"] == stage)

        before = {
            s: served_count(s)
            for s in ("02-generate", "03-check", "05-interactive", "09-review")
        }

        second = self._run("Motion", "--run-id", "e2e-resume")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("[resume] run 'e2e-resume' found", second.stdout)

        for stage, count in before.items():
            self.assertEqual(
                served_count(stage),
                count,
                f"stage {stage} re-ran its model call after resume",
            )

        status = json.loads(
            (self.tmp / "runs" / "e2e-resume" / "status.json").read_text(
                encoding="utf-8"
            )
        )
        for stage in ("00-ingest", "01-locate", "02-generate", "03-check", "09-review"):
            self.assertEqual(
                status["stages"][stage]["detail"],
                "resumed from previous attempt",
                stage,
            )
        report = json.loads(
            (self.tmp / "runs" / "e2e-resume" / "run_report.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(report["ok"])

    def test_fingerprint_mismatch_refuses_resume(self):
        """A run dir from a different run shape must not be silently reused."""
        first = self._run(
            "Motion", "--run-id", "e2e-fp", "--stages", "00-ingest,01-locate"
        )
        self.assertEqual(first.returncode, 0, first.stderr)

        # same run id, but a different model => different fingerprint
        second = self._run(
            "Motion",
            "--run-id",
            "e2e-fp",
            "--stages",
            "00-ingest,01-locate",
            env=self._pipeline_env(ZIVON_MODEL="some-other-model"),
        )
        self.assertEqual(second.returncode, 1)
        self.assertIn("PIPELINE FAILED", second.stderr)
        self.assertIn("fingerprint", second.stderr)
        self.assertIn("--fresh", second.stderr)

    def test_pipeline_fails_loudly_without_server(self):
        env = self._pipeline_env()
        # break ONLY the server url (env is the single source for server settings)
        env["ZIVON_BASE_URL"] = "http://127.0.0.1:9/v1"
        result = self._run(
            "Motion",
            "--run-id",
            "e2e-broken",
            "--stages",
            "00-ingest,01-locate,02-generate",
            env=env,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("PIPELINE FAILED", result.stderr)
        self.assertIn("stage 02-generate", result.stderr)


CHECK_FAIL = {
    "verdict": "fail",
    "issues": [
        {
            "block_id": "b-04",
            "severity": "major",
            "message": "b-04 tests force and mass, concepts this chapter never "
            "defines (reviewer fixture finding)",
        }
    ],
}
CHECK_PASS = {"verdict": "pass", "issues": []}
REVIEW_FIX_CSS = (
    "/* review-fix fixture: grounded spacing fix; no external references */\n"
    ".zivon-check { padding: 0.75rem 1rem; }\n"
)


class TestCatcherRouting(unittest.TestCase):
    """Gate failures route to their catcher, bounded, inside the same run."""

    def setUp(self):
        self._tmp: Path | None = None
        self._server = None
        self.frontend: Path | None = None
        self.config_path: Path | None = None
        self.base_url = ""
        self.state = None

    def tearDown(self):
        if self._server:
            self._server.shutdown()
        if self._tmp:
            shutil.rmtree(self._tmp, ignore_errors=True)
        openai_mock.FIXTURES_DIR = DEFAULT_FIXTURES

    def _start(self, fixture_overrides: dict[str, Any]):
        self._tmp = Path(tempfile.mkdtemp(prefix="zivon-e2e-route-"))
        fdir = self._tmp / "fixtures"
        shutil.copytree(DEFAULT_FIXTURES, fdir)
        for name, payload in fixture_overrides.items():
            (fdir / name).write_text(json.dumps(payload), encoding="utf-8")
        self._server, self.base_url, self.state = start_mock(fdir)
        self.config_path, self.frontend = _build_env(self._tmp)

    def _run(self, *args: str):
        env = dict(os.environ)
        env["ZIVON_CONFIG"] = str(self.config_path)
        env["ZIVON_BASE_URL"] = self.base_url
        env["ZIVON_MODEL"] = "mock-model"
        env["ZIVON_API_KEY"] = "test-key"
        return subprocess.run(
            [sys.executable, "pipeline.py", *args],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )

    def _served(self, stage: str) -> int:
        return sum(1 for s in self.state.served if s["stage"] == stage)

    @unittest.skipUnless(chromium_available(), "playwright chromium not installed")
    def test_check_fail_repaired_then_recheck_pass(self):
        """03-check fails -> 04-repair fixes the flagged block -> recheck passes
        -> the pipeline CONTINUES (interactive/render/.../link all run)."""
        self._start(
            {
                "03-check__attempt1.json": CHECK_FAIL,  # first check call fails
                "03-check.json": CHECK_PASS,  # every later check call passes
                "04-repair.json": json.loads(
                    (DEFAULT_FIXTURES / "repair_plan.json").read_text(encoding="utf-8")
                ),
            }
        )
        result = self._run("Motion", "--run-id", "route-repair-ok")
        self.assertEqual(result.returncode, 0, result.stderr)

        self.assertEqual(self._served("03-check"), 2, "check must run, then recheck")
        self.assertEqual(self._served("04-repair"), 1)

        runs = self._tmp / "runs" / "route-repair-ok"
        status = json.loads((runs / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(
            status["stages"].get("11-link", {}).get("state"),
            "ok",
            "pipeline must continue after repair",
        )
        repair_out = json.loads(
            (runs / "04-repair" / "output.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(repair_out["history"]), 1)
        self.assertEqual(repair_out["history"][0]["replaced"], ["b-04"])
        self.assertEqual(repair_out["page"]["blocks"][3]["id"], "b-04")
        self.assertEqual(repair_out["page"]["blocks"][3]["spec"]["format"], "numeric")

        # round evidence is separated: first check plain, recheck under round-01
        self.assertTrue((runs / "03-check" / "attempts" / "attempt-01").exists())
        self.assertTrue(
            (runs / "03-check" / "attempts" / "round-01" / "attempt-01").exists()
        )
        combined = json.loads(
            (runs / "03-check" / "combined-round-01.json").read_text(encoding="utf-8")
        )
        self.assertEqual(combined["verdict"], "pass")

        # the repaired block is what actually got linked
        courses_text = (self.frontend / "courses.js").read_text(encoding="utf-8")
        payload = json.loads(courses_text.split("=", 1)[1].strip().rstrip(";"))
        html = (self.frontend / payload[0]["href"]).read_text(encoding="utf-8")
        self.assertIn("runner covers 100 m", html)

    @unittest.skipUnless(chromium_available(), "playwright chromium not installed")
    def test_check_fail_exhausts_repair_rounds_then_stops(self):
        """A reviewer that keeps failing burns AT MOST repair.content_rounds
        repair rounds, then fails the run loudly - no upstream re-run."""
        self._start(
            {
                "03-check.json": CHECK_FAIL,  # every check call fails
                "04-repair.json": json.loads(
                    (DEFAULT_FIXTURES / "repair_plan.json").read_text(encoding="utf-8")
                ),
            }
        )
        result = self._run("Motion", "--run-id", "route-repair-fail")
        self.assertEqual(result.returncode, 1)
        self.assertIn("review still failing after 2 repair round(s)", result.stderr)

        self.assertEqual(self._served("03-check"), 3, "check + two rechecks")
        self.assertEqual(
            self._served("04-repair"), 2, "repair is bounded by repair.content_rounds"
        )
        self.assertEqual(self._served("05-interactive"), 0, "no stage after the gate")

        # upstream model stages ran exactly ONCE (retry only): nothing re-derived
        self.assertEqual(self._served("02-generate"), 2)

        status = json.loads(
            (self._tmp / "runs" / "route-repair-fail" / "status.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(status["stages"]["03-check"]["state"], "failed")
        self.assertNotIn(
            "11-link", status["stages"], "nothing runs past the failed gate"
        )
        report = json.loads(
            (self._tmp / "runs" / "route-repair-fail" / "run_report.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertFalse(report["ok"])

    @unittest.skipUnless(chromium_available(), "playwright chromium not installed")
    def test_review_fail_routes_to_reviewfix_bounded(self):
        """09-review fails -> 10-reviewfix applies file fixes + re-lint + re-perf
        -> 09-review re-reviews; the mock keeps failing it, so the bounded loop
        ends loudly and 11-link never runs."""
        self._start(
            {
                "09-review.json": {
                    "verdict": "fail",
                    "issues": [
                        {
                            "severity": "fatal",
                            "block_id": "b-06",
                            "message": "the simulation's drawn behaviour contradicts "
                            "claim-04 (reviewer fixture finding)",
                        }
                    ],
                },
                "10-reviewfix.json": {
                    "analysis": "reviewer fixture finding addressed by a spacing fix "
                    "in page.css; behaviour left untouched.",
                    "files": {"page.css": REVIEW_FIX_CSS},
                },
            }
        )
        result = self._run("Motion", "--run-id", "route-reviewfix")
        self.assertEqual(result.returncode, 1)
        self.assertIn("code review still failing after 2 fix round(s)", result.stderr)

        self.assertEqual(self._served("09-review"), 3, "review + two re-reviews")
        self.assertEqual(
            self._served("10-reviewfix"), 2, "fix is bounded by repair.code_rounds"
        )

        runs = self._tmp / "runs" / "route-reviewfix"
        status = json.loads((runs / "status.json").read_text(encoding="utf-8"))
        self.assertNotIn(
            "11-link", status["stages"], "nothing links past a failed gate"
        )
        history = json.loads(
            (runs / "10-reviewfix" / "history.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(history), 2)
        self.assertTrue(all(h["perf_after_fix"]["pass"] for h in history))

        # the fix was really applied to the topic page
        render_out = json.loads(
            (runs / "06-render" / "output.json").read_text(encoding="utf-8")
        )
        css = (Path(render_out["topic_dir"]) / "page.css").read_text(encoding="utf-8")
        self.assertIn("review-fix fixture", css)

        # re-reviews keep separate attempt evidence per round
        self.assertTrue(
            (runs / "09-review" / "attempts" / "round-01" / "attempt-01").exists()
        )


if __name__ == "__main__":
    unittest.main()
