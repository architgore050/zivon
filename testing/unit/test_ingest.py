"""Unit tests for stage 00-ingest and stage 01-locate using file:// fixture PDFs."""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from factory.artifacts import RunContext  # noqa: E402
from factory.config import load_config  # noqa: E402
from factory.errors import SourceError  # noqa: E402
from factory.ingest import run as ingest_run  # noqa: E402
from factory.locate import run as locate_run  # noqa: E402
from factory.retrieval import FixtureEmbedder  # noqa: E402
import factory.retrieval as retrieval  # noqa: E402

PDFS = REPO_ROOT / "testing" / "mocks" / "fixtures" / "pdfs"


def stage_book_pdfs(tmp: Path, book_id: str, files: list[str]) -> dict[str, str]:
    """Copy fixture PDFs into the production layout: pdf_cache/<book_id>/<file>.
    Returns {filename: file:// url}. Mirrors how ingest stores real downloads."""
    dest = tmp / "pdfs" / book_id
    dest.mkdir(parents=True, exist_ok=True)
    urls = {}
    for name in files:
        shutil.copy(PDFS / name, dest / name)
        urls[name] = (dest / name).as_uri()
    return urls


def make_cfg(tmp: Path, extra_books=None) -> object:
    base = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
    base["server"]["model"] = "test-model"
    base["paths"]["pdf_cache"] = str(tmp / "pdfs")
    base["paths"]["text_cache"] = str(tmp / "cache")
    base["paths"]["runs"] = str(tmp / "runs")
    ncert = stage_book_pdfs(tmp, "fixture-ncert-9", ["prelims.pdf", "ch01.pdf", "ch02.pdf"])
    alt = stage_book_pdfs(tmp, "alt-open-physics", ["alt-open-physics.pdf"])
    catalog = {
        "version": 1,
        "books": [
            {
                "id": "fixture-ncert-9", "class": 9, "subject": "science",
                "title": "Fixture Science Class 9", "publisher": "fixture",
                "license": "test", "is_ncert": True, "download": "auto",
                "prelims_url": ncert["prelims.pdf"],
                "chapter_url_template": ncert["ch01.pdf"].replace("ch01.pdf", "ch{nn}.pdf"),
                "chapter_numbers": [1, 2],
                "chapters_verified": True,
                "class_evidence": ["class 9"],
            },
            {
                "id": "alt-open-physics", "class": 9, "subject": "physics",
                "title": "Open Physics Notes (fixture)", "publisher": "fixture",
                "license": "CC-BY (fixture)", "is_ncert": False, "download": "auto",
                "prelims_url": alt["alt-open-physics.pdf"],
                "chapter_url_template": alt["alt-open-physics.pdf"],
                "chapter_numbers": [1],
                "chapters_verified": True,
                "class_evidence": [],
            },
        ] + (extra_books or []),
    }
    (tmp / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    base["paths"]["catalog"] = str(tmp / "catalog.json")
    (tmp / "config.json").write_text(json.dumps(base), encoding="utf-8")
    return load_config(tmp / "config.json")


def file_url(name: str) -> str:
    """URL for a NOT-staged file (used to test missing-file behaviour)."""
    return (PDFS / name).as_uri()


class IngestTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cfg = make_cfg(self.tmp)
        self.run_ctx = RunContext(self.cfg.repo_path(self.cfg.paths["runs"]), "t-ingest")

    def test_ingest_indexes_books(self):
        out = ingest_run(self.cfg, self.run_ctx)
        by_id = {b["id"]: b for b in out["books"]}
        self.assertIn("fixture-ncert-9", by_id)
        self.assertIn("alt-open-physics", by_id)
        ncert = by_id["fixture-ncert-9"]
        self.assertEqual([c["n"] for c in ncert["chapters"]], [1, 2])
        self.assertEqual(ncert["chapters"][0]["title_detected"], "Motion")
        self.assertEqual(ncert["chapters"][1]["title_detected"], "Sound")

    def test_class_evidence_mismatch_fails(self):
        bad_pdfs = stage_book_pdfs(self.tmp, "bad-book", ["prelims.pdf", "ch01.pdf"])
        bad = [{
            "id": "bad-book", "class": 42, "subject": "science", "title": "Bad",
            "publisher": "x", "license": "x", "is_ncert": True, "download": "auto",
            "prelims_url": bad_pdfs["prelims.pdf"],
            "chapter_url_template": bad_pdfs["ch01.pdf"].replace("ch01.pdf", "ch{nn}.pdf"),
            "chapter_numbers": [1], "chapters_verified": True,
            "class_evidence": ["class 42"],
        }]
        cfg = make_cfg(self.tmp, extra_books=bad)
        # the bad book is first? it is appended last; run only needs to hit it
        with self.assertRaises(SourceError) as ctx:
            ingest_run(cfg, self.run_ctx)
        self.assertIn("class_evidence", str(ctx.exception))

    def test_missing_chapter_verified_true_fails(self):
        gap_pdfs = stage_book_pdfs(self.tmp, "gap-book", ["prelims.pdf", "ch01.pdf", "ch02.pdf"])
        bad = [{
            "id": "gap-book", "class": 9, "subject": "science", "title": "Gap",
            "publisher": "x", "license": "x", "is_ncert": True, "download": "auto",
            "prelims_url": gap_pdfs["prelims.pdf"],
            "chapter_url_template": gap_pdfs["ch01.pdf"].replace("ch01.pdf", "ch{nn}.pdf"),
            "chapter_numbers": [1, 2, 3],  # ch03.pdf does not exist
            "chapters_verified": True,
            "class_evidence": ["class 9"],
        }]
        cfg = make_cfg(self.tmp, extra_books=bad)
        with self.assertRaises(SourceError) as ctx:
            ingest_run(cfg, self.run_ctx)
        self.assertIn("chapters_verified=true", str(ctx.exception))

    def test_missing_chapter_unverified_truncates_loudly(self):
        gap_pdfs = stage_book_pdfs(self.tmp, "gap-book-u", ["prelims.pdf", "ch01.pdf", "ch02.pdf"])
        bad = [{
            "id": "gap-book-u", "class": 9, "subject": "science", "title": "GapU",
            "publisher": "x", "license": "x", "is_ncert": True, "download": "auto",
            "prelims_url": gap_pdfs["prelims.pdf"],
            "chapter_url_template": gap_pdfs["ch01.pdf"].replace("ch01.pdf", "ch{nn}.pdf"),
            "chapter_numbers": [1, 2, 3],
            "chapters_verified": False,
            "class_evidence": ["class 9"],
        }]
        cfg = make_cfg(self.tmp, extra_books=bad)
        out = ingest_run(cfg, self.run_ctx)
        gap = [b for b in out["books"] if b["id"] == "gap-book-u"][0]
        self.assertEqual(gap["truncated_at"], 3)
        self.assertEqual([c["n"] for c in gap["chapters"]], [1, 2])

    def test_manual_book_missing_gives_instructions(self):
        manual = [{
            "id": "manual-book", "class": 10, "subject": "physics", "title": "Manual",
            "publisher": "x", "license": "CC", "is_ncert": False, "download": "manual",
            "manual_filename": "manual.pdf", "manual_url": "https://example.test/get",
            "class_evidence": [],
        }]
        cfg = make_cfg(self.tmp, extra_books=manual)
        with self.assertRaises(SourceError) as ctx:
            ingest_run(cfg, self.run_ctx)
        self.assertIn("manual-book", str(ctx.exception))
        self.assertIn("manual.pdf", str(ctx.exception))
        self.assertIn("https://example.test/get", str(ctx.exception))

    def test_manual_book_present_indexes(self):
        manual = [{
            "id": "manual-book", "class": 10, "subject": "physics", "title": "Manual",
            "publisher": "x", "license": "CC", "is_ncert": False, "download": "manual",
            "manual_filename": "manual.pdf", "manual_url": "https://example.test/get",
            "class_evidence": [],
        }]
        cfg = make_cfg(self.tmp, extra_books=manual)
        dest = cfg.repo_path(cfg.paths["pdf_cache"]) / "manual-book" / "manual.pdf"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(PDFS / "alt-open-physics.pdf", dest)
        out = ingest_run(cfg, self.run_ctx)
        book = [b for b in out["books"] if b["id"] == "manual-book"][0]
        self.assertEqual(book["chapters"][0]["pages_count"], 5)


class LocateTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cfg = make_cfg(self.tmp)
        self.run_ctx = RunContext(self.cfg.repo_path(self.cfg.paths["runs"]), "t-locate")
        self.run_ctx.save_stage_output("00-ingest", ingest_run(self.cfg, self.run_ctx))
        self.patcher = mock.patch.object(retrieval, "get_embedder", lambda cfg: FixtureEmbedder())
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_locate_finds_motion(self):
        pack = locate_run(self.cfg, self.run_ctx, "Motion", None)
        self.assertEqual(pack["chapter"]["book_id"], "fixture-ncert-9")
        self.assertIn("Motion", pack["chapter"]["title"])
        self.assertIn("Motion", pack["ncert_text"])
        self.assertTrue(len(pack["ncert_text"]) > 200)

    def test_locate_ambiguity_lists_candidates(self):
        # Both fixture books are class 9; give the NCERT book a twin to force ambiguity.
        twin_pdfs = stage_book_pdfs(self.tmp, "fixture-ncert-9b", ["prelims.pdf", "ch01.pdf", "ch02.pdf"])
        twin = [{
            "id": "fixture-ncert-9b", "class": 9, "subject": "science", "title": "Twin Book",
            "publisher": "x", "license": "x", "is_ncert": True, "download": "auto",
            "prelims_url": twin_pdfs["prelims.pdf"],
            "chapter_url_template": twin_pdfs["ch01.pdf"].replace("ch01.pdf", "ch{nn}.pdf"),
            "chapter_numbers": [1, 2], "chapters_verified": True,
            "class_evidence": ["class 9"],
        }]
        tmp2 = Path(tempfile.mkdtemp())
        cfg2 = make_cfg(tmp2, extra_books=twin)
        run2 = RunContext(cfg2.repo_path(cfg2.paths["runs"]), "t-ambig")
        run2.save_stage_output("00-ingest", ingest_run(cfg2, run2))
        with self.assertRaises(SourceError) as ctx:
            locate_run(cfg2, run2, "Motion", None)
        self.assertIn("--class", str(ctx.exception))

    def test_locate_class_filter_resolves(self):
        twin_pdfs = stage_book_pdfs(self.tmp, "fixture-ncert-9b", ["prelims.pdf", "ch01.pdf", "ch02.pdf"])
        twin = [{
            "id": "fixture-ncert-9b", "class": 10, "subject": "science", "title": "Twin Book",
            "publisher": "x", "license": "x", "is_ncert": True, "download": "auto",
            "prelims_url": twin_pdfs["prelims.pdf"],
            "chapter_url_template": twin_pdfs["ch01.pdf"].replace("ch01.pdf", "ch{nn}.pdf"),
            "chapter_numbers": [1, 2], "chapters_verified": True,
            "class_evidence": ["class 9"],
        }]
        tmp2 = Path(tempfile.mkdtemp())
        cfg2 = make_cfg(tmp2, extra_books=twin)
        run2 = RunContext(cfg2.repo_path(cfg2.paths["runs"]), "t-filter")
        run2.save_stage_output("00-ingest", ingest_run(cfg2, run2))
        pack = locate_run(cfg2, run2, "Motion", 10)
        self.assertEqual(pack["chapter"]["book_id"], "fixture-ncert-9b")

    def test_locate_unknown_chapter_lists_library(self):
        with self.assertRaises(SourceError) as ctx:
            locate_run(self.cfg, self.run_ctx, "Photosynthesis Extrasensory", None)
        self.assertIn("matches no NCERT chapter", str(ctx.exception))

    def test_locate_supplements_come_from_other_books(self):
        pack = locate_run(self.cfg, self.run_ctx, "Motion", None)
        book_ids = {s["book_id"] for s in pack["supplements"]}
        self.assertNotIn("fixture-ncert-9", book_ids)
        self.assertIn("alt-open-physics", book_ids)


if __name__ == "__main__":
    unittest.main()
