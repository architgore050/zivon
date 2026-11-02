"""End-to-end integration test: the FULL pipeline against the mock server.

Exercises every stage in order with the real orchestrator (subprocess,
production code path) and a real Chromium for the performance gate:

    fixture PDFs (file://) -> ingest -> locate -> [mock model stages]
    -> render -> perf (real headless Chromium) -> review -> link

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

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

PDFS = REPO_ROOT / "testing" / "content_factory" / "mocks" / "fixtures" / "pdfs"


def chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            b.close()
        return True
    except Exception:  # noqa: BLE001 — probe: any failure just means "not available"
        return False


class TestEndToEnd(unittest.TestCase):
    tmp: Path  # set in setUpClass
    server = None

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="zivon-e2e-"))
        from testing.content_factory.mocks.openai_mock import start_mock

        cls.server, cls.base_url, cls.state = start_mock()

        # --- stage fixture PDFs into the production layout -------------------
        for book, files in (
            ("fixture-ncert-9", ["prelims.pdf", "ch01.pdf", "ch02.pdf"]),
            ("alt-open-physics", ["alt-open-physics.pdf"]),
        ):
            dest = cls.tmp / "pdfs" / book
            dest.mkdir(parents=True, exist_ok=True)
            for f in files:
                shutil.copy(PDFS / f, dest / f)

        # --- frontend copy (link stage must not touch the real repo) ---------
        frontend = cls.tmp / "frontend"
        frontend.mkdir()
        shutil.copytree(REPO_ROOT / "frontend" / "assets", frontend / "assets")
        shutil.copy2(REPO_ROOT / "frontend" / "index.html", frontend / "index.html")
        shutil.copy2(REPO_ROOT / "frontend" / "courses.js", frontend / "courses.js")

        # --- config -----------------------------------------------------------
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
                        cls.tmp / "pdfs" / "fixture-ncert-9" / "prelims.pdf"
                    ).as_uri(),
                    "chapter_url_template": (
                        cls.tmp / "pdfs" / "fixture-ncert-9" / "ch{nn}.pdf"
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
                        cls.tmp / "pdfs" / "alt-open-physics" / "alt-open-physics.pdf"
                    ).as_uri(),
                    "chapter_url_template": (
                        cls.tmp / "pdfs" / "alt-open-physics" / "alt-open-physics.pdf"
                    ).as_uri(),
                    "chapter_numbers": [1],
                    "chapters_verified": True,
                    "class_evidence": [],
                },
            ],
        }
        (cls.tmp / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")

        # --- design doctrine copy (04/06/10 inject it live at build time) ---
        doctrine_dir = cls.tmp / "docs" / "frontend"
        doctrine_dir.mkdir(parents=True)
        for p in (REPO_ROOT / "docs" / "frontend").glob("design-doctrine*"):
            shutil.copy2(p, doctrine_dir / p.name)

        base = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
        base["paths"].update(
            {
                "catalog": str(cls.tmp / "catalog.json"),
                "pdf_cache": str(cls.tmp / "pdfs"),
                "text_cache": str(cls.tmp / "cache"),
                "runs": str(cls.tmp / "runs"),
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
        cls.config_path = cls.tmp / "config.json"
        cls.config_path.write_text(json.dumps(base), encoding="utf-8")
        cls.frontend = frontend

    @classmethod
    def tearDownClass(cls):
        if cls.server:
            cls.server.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _pipeline_env(self):
        env = dict(os.environ)
        env["ZIVON_CONFIG"] = str(self.config_path)
        # server settings are env-only now
        env["ZIVON_BASE_URL"] = self.base_url
        env["ZIVON_MODEL"] = "mock-model"
        env["ZIVON_API_KEY"] = "test-key"
        return env

    @unittest.skipUnless(chromium_available(), "playwright chromium not installed")
    def test_full_run_motion(self):
        result = subprocess.run(
            [sys.executable, "pipeline.py", "Motion", "--run-id", "e2e-motion"],
            cwd=REPO_ROOT,
            env=self._pipeline_env(),
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"pipeline failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}",
        )

        runs = self.tmp / "runs" / "e2e-motion"
        # every stage produced artifacts and was marked ok
        status = json.loads((runs / "status.json").read_text(encoding="utf-8"))
        for stage in [
            "00-ingest",
            "01-locate",
            "02-synth",
            "03-explain",
            "04-draft",
            "05-check",
            "06-interactive",
            "07-render",
            "08-perf",
            "10-review",
            "11-link",
        ]:
            self.assertEqual(status["stages"][stage]["state"], "ok", stage)
        # 09-fixloop only runs if 08 missed; in this fixture it should not be present or is ok
        if "09-fixloop" in status["stages"]:
            self.assertIn(status["stages"]["09-fixloop"]["state"], ("ok",))

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

        # the model stages received exactly one scripted retry on 02-synth
        stages_used = [s["stage"] for s in self.state.served]
        self.assertEqual(
            stages_used.count("02-synth"),
            2,
            "expected one schema retry on 02-synth (attempt-1 fixture is invalid)",
        )

        report = json.loads((runs / "run_report.json").read_text(encoding="utf-8"))
        self.assertTrue(report["ok"])

    def test_pipeline_fails_loudly_without_server(self):
        env = self._pipeline_env()
        # break ONLY the server url (env is the single source for server settings)
        env["ZIVON_BASE_URL"] = "http://127.0.0.1:9/v1"
        result = subprocess.run(
            [
                sys.executable,
                "pipeline.py",
                "Motion",
                "--run-id",
                "e2e-broken",
                "--stages",
                "00-ingest,01-locate,02-synth",
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("PIPELINE FAILED", result.stderr)
        self.assertIn("stage 02-synth", result.stderr)


if __name__ == "__main__":
    unittest.main()
