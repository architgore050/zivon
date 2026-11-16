"""Catalogue v2, version guard, locale hrefs and publish smoke (P5, 2026-11-16).

Every test here is deterministic and offline: a synthetic published tree is
built on disk, then the publish gate is exercised against it. No model calls,
no browser, no cluster.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from factory import catalogue, identity

REPO_ROOT = Path(__file__).resolve().parents[3]
PUBLISH_SCRIPT = REPO_ROOT / "scripts" / "publish-frontend.sh"
GEN_SEO = REPO_ROOT / "scripts" / "gen-seo-files.py"

CONCEPT = "class-9-motion-sec-01"
VALID_PAGE = f"""<!doctype html>
<html lang="en"><head><title>Motion - Zivon</title></head>
<body>
<main class="zn-page">
  <section class="zn-section" id="sec-01" data-section-id="sec-01"
           data-concept-id="{CONCEPT}">
    <section class="zn-text" id="b-01" data-block-type="text"
             data-concept-id="{CONCEPT}">
      <p>Motion is a change of position.</p>
    </section>
    <fieldset class="zn-check" id="b-02" data-block-type="check"
              data-concept-id="{CONCEPT}">
      <legend>Check</legend>
    </fieldset>
  </section>
</main>
</body></html>
"""


def _manifest(
    *,
    course_id: str = "class-9-physics",
    class_level: int = 9,
    topic_slug: str = "motion",
    title: str = "Motion",
    lesson_title: str = "How Forces Affect Motion",
    chapter_title: str = "Motion",
    chapter_number: int | None = 1,
    version: str | None = identity.pipeline_version(),
    locales: list[str] | None = None,
    status: str = "lesson_only",
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "manifest_version": 2,
        "chapter_id": f"class-{class_level}-{topic_slug}",
        "lesson_id": f"class-{class_level}-{topic_slug}",
        "course_id": course_id,
        "subject": "physics",
        "class": class_level,
        "topic_slug": topic_slug,
        "title": title,
        "lesson_title": lesson_title,
        "status": status,
        "chapter": {
            "query": chapter_title,
            "title": chapter_title,
            "book": "NCERT",
            "pages": [1, 2],
            "number": chapter_number,
        },
        "blocks": {
            "b-01": {"type": "text", "section_id": "sec-01", "concept_id": CONCEPT},
            "b-02": {"type": "check", "section_id": "sec-01", "concept_id": CONCEPT},
        },
        "sections": [
            {
                "id": "sec-01",
                "title": "Motion",
                "concept_id": CONCEPT,
                "block_ids": ["b-01", "b-02"],
            }
        ],
        "concepts": [
            {"concept_id": CONCEPT, "section_id": "sec-01", "title": "Motion"}
        ],
        "counts": {"lesson_blocks": 2, "text_blocks": 1, "checks": 1},
        "languages": {"default": "en", "available": ["en", "hi", "hi-Latn"]},
        "locales_available": ["en", "hi", "hi-Latn"],
        "default_locale": "en",
        "content_hash": "sha256:" + "0" * 64,
        "generated_at": "2026-11-16T00:00:00Z",
    }
    if version is not None:
        manifest["pipeline_version"] = version
    if locales is not None:
        manifest["locales_available"] = locales
    return manifest


def _write_topic(
    frontend: Path,
    manifest: dict[str, Any],
    *,
    html: str | None = None,
    locales: tuple[str, ...] = (),
    narration: dict[str, Any] | None = None,
) -> Path:
    topic = (
        frontend / "courses" / str(manifest["course_id"]) / str(manifest["topic_slug"])
    )
    topic.mkdir(parents=True, exist_ok=True)
    (topic / "index.html").write_text(html or VALID_PAGE, encoding="utf-8")
    (topic / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    for locale in locales:
        loc_dir = topic / locale
        loc_dir.mkdir(exist_ok=True)
        (loc_dir / "index.html").write_text(VALID_PAGE, encoding="utf-8")
        (loc_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "course_id": manifest["course_id"],
                    "topic_slug": manifest["topic_slug"],
                    "locale": locale,
                    "narration": {"available": False, "lang": locale, "blocks": {}},
                }
            ),
            encoding="utf-8",
        )
        (topic / "i18n").mkdir(exist_ok=True)
        (topic / "i18n" / f"{locale}.json").write_text(
            json.dumps({"locale": locale, "status": "verified"}), encoding="utf-8"
        )
    if narration is not None:
        (topic / "narration-manifest.json").write_text(
            json.dumps(narration), encoding="utf-8"
        )
    return topic


def _write_seo(frontend: Path, base: str = "https://example.test") -> None:
    topics = sorted(frontend.glob("courses/*/*/manifest.json"))
    urls = [f"{base}/"]
    for manifest in topics:
        rel = manifest.parent.relative_to(frontend).as_posix()
        urls.append(f"{base}/{rel}/")
    body = "\n".join(f"  <url><loc>{url}</loc></url>" for url in urls)
    (frontend / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{body}\n'
        "</urlset>\n",
        encoding="utf-8",
    )
    (frontend / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n",
        encoding="utf-8",
    )


def _build_site(tmp: Path) -> Path:
    frontend = tmp / "frontend"
    frontend.mkdir(parents=True, exist_ok=True)
    (frontend / "index.html").write_text(VALID_PAGE, encoding="utf-8")
    _write_topic(
        frontend,
        _manifest(),
        locales=("hi", "hi-Latn"),
    )
    _write_topic(
        frontend,
        _manifest(
            course_id="class-11-physics",
            class_level=11,
            topic_slug="laws-of-motion",
            title="Laws of Motion",
            chapter_title="Laws of Motion",
            chapter_number=4,
            locales=[],
        ),
        locales=(),
    )
    _write_seo(frontend)
    catalogue.build(frontend)
    return frontend


class TestCatalogueVersionGuard(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.frontend = self.tmp / "frontend"

    def test_one_pipeline_version_is_recorded_per_topic(self) -> None:
        _write_topic(self.frontend, _manifest())
        _write_seo(self.frontend)
        report = catalogue.build(self.frontend)
        self.assertEqual(report.status, "ok")
        payload = json.loads(
            (self.frontend / "catalogue.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["catalogue_version"], 2)
        self.assertEqual(payload["topics"][0]["pipeline_version"], "9")
        self.assertEqual(payload["integrity"]["versions"], {"9": 1})

    def test_mixed_versions_are_marked_and_strict_check_refuses(self) -> None:
        _write_topic(self.frontend, _manifest(topic_slug="motion"))
        _write_topic(
            self.frontend,
            _manifest(
                class_level=11,
                course_id="class-11-physics",
                topic_slug="laws-of-motion",
                title="Laws of Motion",
                chapter_title="Laws of Motion",
                version="8",
            ),
        )
        _write_seo(self.frontend)
        report = catalogue.build(self.frontend)
        self.assertEqual(report.status, "mixed")
        payload = json.loads(
            (self.frontend / "catalogue.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["integrity"]["status"], "mixed")
        self.assertEqual(payload["integrity"]["mixed_versions"], ["8"])
        checked = catalogue.validate(self.frontend)
        self.assertFalse(checked.ok)
        self.assertEqual(checked.status, "mixed")
        self.assertTrue(
            any("mixes pipeline_versions" in e for e in checked.errors),
            checked.errors,
        )

    def test_a_manifest_without_pipeline_version_is_incomplete_not_ok(self) -> None:
        _write_topic(self.frontend, _manifest(version=None))
        _write_seo(self.frontend)
        report = catalogue.build(self.frontend)
        self.assertEqual(report.status, "incomplete")
        checked = catalogue.validate(self.frontend)
        self.assertFalse(checked.ok)
        self.assertTrue(any("no pipeline_version" in e for e in checked.errors))


class TestCatalogueV2Shape(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.frontend = _build_site(self.tmp)

    def test_courses_js_is_derived_from_catalogue_with_v2_fields(self) -> None:
        text = (self.frontend / "courses.js").read_text(encoding="utf-8")
        match = re.search(r"window\.ZIVON_COURSES = (\[.*\]);", text, re.DOTALL)
        assert match is not None
        entries = json.loads(match.group(1))
        self.assertEqual(len(entries), 2)
        first = next(e for e in entries if e["course_id"] == "class-9-physics")
        for key in (
            "status",
            "languages",
            "counts",
            "concepts",
            "localized_hrefs",
            "pipeline_version",
        ):
            self.assertIn(key, first)
        self.assertEqual(first["chapter"], "Motion")
        self.assertEqual(first["chapter_number"], 1)

    def test_ordering_is_class_then_chapter_number_then_chapter_then_title(
        self,
    ) -> None:
        payload = json.loads(
            (self.frontend / "catalogue.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            [t["course_id"] for t in payload["topics"]],
            ["class-9-physics", "class-11-physics"],
        )
        text = (self.frontend / "courses.js").read_text(encoding="utf-8")
        self.assertLess(text.index("class-9-physics"), text.index("class-11-physics"))

    def test_localized_hrefs_only_advertise_routes_that_exist(self) -> None:
        topic = self.frontend / "courses" / "class-9-physics" / "motion"
        # hi exists (written by the helper); hi-Latn is promised but absent.
        shutil.rmtree(topic / "hi-Latn")
        catalogue.build(self.frontend)
        payload = json.loads(
            (self.frontend / "catalogue.json").read_text(encoding="utf-8")
        )
        entry = next(
            t for t in payload["topics"] if t["course_id"] == "class-9-physics"
        )
        self.assertEqual(
            entry["localized_hrefs"]["en"],
            f"{topic.relative_to(self.frontend).as_posix()}/index.html",
        )
        self.assertIn("hi", entry["localized_hrefs"])
        self.assertEqual(entry["missing_locales"], ["hi-Latn"])
        checked = catalogue.validate(self.frontend)
        self.assertFalse(checked.ok)
        self.assertTrue(any("promised locale 'hi-Latn'" in e for e in checked.errors))

    def test_prefixed_locale_route_is_supported(self) -> None:
        topic = self.frontend / "courses" / "class-11-physics" / "laws-of-motion"
        manifest = json.loads((topic / "manifest.json").read_text(encoding="utf-8"))
        manifest["locales_available"] = ["en", "hi"]
        (topic / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        prefixed = self.frontend / "hi" / topic.relative_to(self.frontend)
        prefixed.mkdir(parents=True)
        (prefixed / "index.html").write_text(VALID_PAGE, encoding="utf-8")
        (prefixed / "manifest.json").write_text(
            json.dumps({"locale": "hi"}), encoding="utf-8"
        )
        (topic / "i18n").mkdir(exist_ok=True)
        (topic / "i18n" / "hi.json").write_text(
            json.dumps({"locale": "hi", "status": "verified"}), encoding="utf-8"
        )
        catalogue.build(self.frontend)
        payload = json.loads(
            (self.frontend / "catalogue.json").read_text(encoding="utf-8")
        )
        entry = next(
            t for t in payload["topics"] if t["course_id"] == "class-11-physics"
        )
        self.assertEqual(
            entry["localized_hrefs"]["hi"],
            "hi/courses/class-11-physics/laws-of-motion/index.html",
        )


class TestPublishSmoke(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.frontend = _build_site(self.tmp)

    def test_clean_tree_passes_without_placeholder(self) -> None:
        report = catalogue.validate(self.frontend)
        self.assertTrue(report.ok, report.errors)
        self.assertEqual(report.status, "ok")
        self.assertEqual(report.topics, 2)
        self.assertGreater(report.locales_checked, 0)

    def test_grade_chapter_title_is_refused(self) -> None:
        topic = self.frontend / "courses" / "class-9-physics" / "motion"
        manifest = json.loads((topic / "manifest.json").read_text(encoding="utf-8"))
        manifest["chapter"]["title"] = "Grade"
        (topic / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        catalogue.build(self.frontend)
        report = catalogue.validate(self.frontend)
        self.assertFalse(report.ok)
        self.assertTrue(any("not a usable chapter name" in e for e in report.errors))

    def test_missing_lesson_title_is_refused(self) -> None:
        topic = self.frontend / "courses" / "class-9-physics" / "motion"
        manifest = json.loads((topic / "manifest.json").read_text(encoding="utf-8"))
        manifest.pop("lesson_title")
        (topic / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        report = catalogue.validate(self.frontend)
        self.assertTrue(any("no lesson_title" in e for e in report.errors))

    def test_missing_locale_manifest_is_refused(self) -> None:
        topic = self.frontend / "courses" / "class-9-physics" / "motion"
        (topic / "hi" / "manifest.json").unlink()
        report = catalogue.validate(self.frontend)
        self.assertFalse(report.ok)
        self.assertTrue(
            any("no locale manifest.json" in e for e in report.errors),
            report.errors,
        )

    def test_page_without_p1_hooks_is_refused(self) -> None:
        topic = self.frontend / "courses" / "class-9-physics" / "motion"
        (topic / "index.html").write_text(
            "<!doctype html><html><body><p>plain</p></body></html>",
            encoding="utf-8",
        )
        report = catalogue.validate(self.frontend)
        self.assertFalse(report.ok)
        self.assertTrue(any("no block elements" in e for e in report.errors))

    def test_placeholder_sitemap_is_refused_unless_explicitly_allowed(self) -> None:
        _write_seo(self.frontend, base="https://zivon.local")
        report = catalogue.validate(self.frontend)
        self.assertFalse(report.ok)
        self.assertTrue(
            any("placeholder" in e for e in report.errors),
            report.errors,
        )
        allowed = catalogue.validate(self.frontend, allow_placeholder=True)
        self.assertTrue(allowed.ok, allowed.errors)

    def test_sitemap_url_without_a_page_is_refused(self) -> None:
        sitemap = self.frontend / "sitemap.xml"
        sitemap.write_text(
            sitemap.read_text(encoding="utf-8").replace(
                "</urlset>",
                "  <url><loc>https://example.test/ghost/</loc></url>\n</urlset>",
            ),
            encoding="utf-8",
        )
        report = catalogue.validate(self.frontend)
        self.assertFalse(report.ok)
        self.assertTrue(any("does not resolve" in e for e in report.errors))

    def test_courses_js_must_be_derived_from_the_catalogue(self) -> None:
        path = self.frontend / "courses.js"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "courses/class-9-physics/motion/index.html",
                "courses/class-9-physics/ghost/index.html",
            ),
            encoding="utf-8",
        )
        report = catalogue.validate(self.frontend)
        self.assertFalse(report.ok)
        self.assertTrue(
            any("not derived from catalogue.json" in e for e in report.errors)
        )

    def test_missing_catalogue_json_is_refused(self) -> None:
        (self.frontend / "catalogue.json").unlink()
        report = catalogue.validate(self.frontend)
        self.assertFalse(report.ok)
        self.assertTrue(any("catalogue.json is missing" in e for e in report.errors))

    def test_narration_coverage_lists_missing_assets_instead_of_claiming(self) -> None:
        topic = self.frontend / "courses" / "class-9-physics" / "motion"
        narration = {
            "lang": "en",
            "mode": "live",
            "blocks": [
                {
                    "block_id": "b-01",
                    "lang": "en",
                    "hash": "abc",
                    "path": "audio/class-9-physics/missing.opus",
                }
            ],
        }
        (topic / "narration-manifest.json").write_text(
            json.dumps(narration), encoding="utf-8"
        )
        report = catalogue.validate(self.frontend)
        self.assertIn(
            "courses/class-9-physics/motion", report.narration["missing_assets"]
        )
        self.assertIn(
            "courses/class-9-physics/motion", report.narration["missing_blocks"]
        )
        # Narration gaps are reported, not treated as page breakage.
        self.assertTrue(report.ok, report.errors)

    def test_missing_narration_manifest_is_reported_honestly(self) -> None:
        report = catalogue.validate(self.frontend)
        self.assertIn(
            "courses/class-11-physics/laws-of-motion",
            report.narration["missing_manifests"],
        )

    def test_require_narration_promotes_the_gap_to_a_blocker(self) -> None:
        report = catalogue.validate(self.frontend, require_narration=True)
        self.assertFalse(report.ok)
        self.assertTrue(any("narration is not available" in e for e in report.errors))


class TestSeoGeneratorUsesCatalogue(unittest.TestCase):
    def test_sitemap_uses_catalogue_locale_hrefs_and_verifies_them(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        frontend = _build_site(tmp)
        shutil.rmtree(frontend / "courses" / "class-9-physics" / "motion" / "hi-Latn")
        catalogue.build(frontend)
        result = subprocess.run(
            [
                sys.executable,
                str(GEN_SEO),
                "--frontend-dir",
                str(frontend),
                "--base-url",
                "https://example.test",
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        sitemap = (frontend / "sitemap.xml").read_text(encoding="utf-8")
        self.assertIn('xmlns:xhtml="http://www.w3.org/1999/xhtml"', sitemap)
        self.assertIn('hreflang="hi"', sitemap)
        self.assertNotIn('hreflang="hi-Latn"', sitemap)  # promised, no route
        self.assertIn("https://example.test/courses/class-9-physics/motion/", sitemap)


class TestPublishScriptDryRun(unittest.TestCase):
    def _run(self, source: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env["ZIVON_PUBLIC_BASE_URL"] = "https://example.test"
        env["PYTHONPATH"] = str(REPO_ROOT)
        return subprocess.run(
            [
                "bash",
                str(PUBLISH_SCRIPT),
                "--dry-run",
                "--source-dir",
                str(source),
                *extra,
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env=env,
            check=False,
        )

    def test_dry_run_accepts_a_homogeneous_tree(self) -> None:
        frontend = _build_site(Path(tempfile.mkdtemp()))
        result = self._run(frontend)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("DRY RUN OK", result.stdout)

    def test_dry_run_refuses_a_mixed_tree(self) -> None:
        frontend = _build_site(Path(tempfile.mkdtemp()))
        topic = frontend / "courses" / "class-11-physics" / "laws-of-motion"
        manifest = json.loads((topic / "manifest.json").read_text(encoding="utf-8"))
        manifest["pipeline_version"] = "8"
        (topic / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        catalogue.build(frontend)
        # build() marks the tree mixed; the publish dry run must refuse it.
        result = self._run(frontend)
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("mixes pipeline_versions", combined)


if __name__ == "__main__":
    unittest.main()


class TestLinkPublish(unittest.TestCase):
    """Stage 11-link writes the catalogue and preserves read-aloud on re-publish."""

    def setUp(self) -> None:
        from factory.artifacts import RunContext
        from testing.content_factory.unit.test_render import make_cfg

        self.tmp = Path(tempfile.mkdtemp())
        self.cfg, self.frontend = make_cfg(self.tmp)
        runs_dir = self.cfg.repo_path(self.cfg.paths["runs"])
        self.run_ctx = RunContext(runs_dir, "t-p5-link")

    def _render_and_link(self) -> dict[str, Any]:
        from factory import link
        from factory.render import run as render_run
        from testing.content_factory.unit.test_render import minimal_inputs

        source_pack, lesson, blocks, interactive = minimal_inputs()
        out = render_run(
            self.cfg,
            self.run_ctx,
            "Motion",
            source_pack,
            lesson,
            blocks,
            interactive,
        )
        return link.run(self.cfg, self.run_ctx, out)

    def test_link_writes_catalogue_and_courses_from_one_source(self) -> None:
        published = self._render_and_link()
        self.assertEqual(published["course_count"], 1)
        payload = json.loads(
            (self.frontend / "catalogue.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["catalogue_version"], 2)
        self.assertEqual(payload["integrity"]["status"], "ok")
        self.assertEqual(payload["topics"][0]["pipeline_version"], "9")
        text = (self.frontend / "courses.js").read_text(encoding="utf-8")
        self.assertIn('"pipeline_version": "9"', text)
        self.assertIn('"localized_hrefs"', text)

    def test_republish_prunes_a_same_run_duplicate_with_a_different_title(self) -> None:
        # One run produces one page: a pre-P1 model-titled duplicate carries the
        # same run_id but a different chapter title, so chapter-title pruning
        # alone misses it.
        self._render_and_link()
        duplicate = self.frontend / "courses" / "class-9-physics" / "motion-a-tagline"
        duplicate.mkdir(parents=True)
        (duplicate / "index.html").write_text("<html></html>", encoding="utf-8")
        (duplicate / "manifest.json").write_text(
            json.dumps(
                {
                    "course_id": "class-9-physics",
                    "class": 9,
                    "title": "Motion: A Tagline",
                    "chapter": {"title": "Motion: A Tagline"},
                    "run_id": "t-p5-link",
                    "generated_at": "2026-11-09T00:00:00Z",
                }
            ),
            encoding="utf-8",
        )
        published = self._render_and_link()
        self.assertIn("motion-a-tagline", published["pruned_stale_topics"])
        self.assertFalse(duplicate.exists())

    def test_republish_preserves_narration_for_an_unchanged_page(self) -> None:
        self._render_and_link()
        topic = self.frontend / "courses" / "class-9-physics" / "motion"
        narration = {
            "lang": "en",
            "voice": "Shivani",
            "mode": "live",
            "blocks": [
                {
                    "block_id": "b-01",
                    "lang": "en",
                    "hash": "abc",
                    "path": "audio/x.opus",
                }
            ],
        }
        (topic / "narration-manifest.json").write_text(
            json.dumps(narration), encoding="utf-8"
        )
        manifest = json.loads((topic / "manifest.json").read_text(encoding="utf-8"))
        manifest["narration"] = {"available": True, "lang": "en", "blocks": {}}
        (topic / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        published = self._render_and_link()
        self.assertTrue(published["narration_preserved"])
        self.assertTrue((topic / "narration-manifest.json").is_file())
        re_manifest = json.loads((topic / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(re_manifest["narration"]["lang"], "en")


class TestLocaleManifestContract(unittest.TestCase):
    """`zivon.js` reads `<locale>/manifest.json`; publish must always write it."""

    def test_preserved_locale_manifest_keeps_its_narration(self) -> None:
        from factory.link import _write_locale_manifests

        topic = Path(tempfile.mkdtemp()) / "motion"
        (topic / "hi").mkdir(parents=True)
        (topic / "hi" / "index.html").write_text(VALID_PAGE, encoding="utf-8")
        manifest = _manifest()
        preserved = {
            "hi": {
                "locale": "hi",
                "narration": {
                    "available": True,
                    "lang": "hi",
                    "blocks": {"b-01": {"available": True, "path": "audio/hi.opus"}},
                },
            }
        }
        _write_locale_manifests(topic, manifest, preserved)
        written = json.loads((topic / "hi" / "manifest.json").read_text())
        self.assertEqual(written["locale"], "hi")
        self.assertTrue(written["narration"]["available"])
        self.assertEqual(written["course_id"], "class-9-physics")

    def test_stale_locale_narration_is_replaced_with_unavailable(self) -> None:
        from factory.link import _write_locale_manifests

        topic = Path(tempfile.mkdtemp()) / "motion"
        (topic / "hi").mkdir(parents=True)
        (topic / "hi" / "index.html").write_text(VALID_PAGE, encoding="utf-8")
        manifest = _manifest()
        preserved = {
            "hi": {
                "locale": "hi",
                "narration": {
                    "available": True,
                    "lang": "hi",
                    "blocks": {"b-99": {"available": True, "path": "audio/hi.opus"}},
                },
            }
        }
        _write_locale_manifests(topic, manifest, preserved)
        written = json.loads((topic / "hi" / "manifest.json").read_text())
        self.assertFalse(written["narration"]["available"])
        self.assertEqual(written["narration"]["blocks"], {})


class TestCommittedSnapshot(unittest.TestCase):
    """The committed deployable snapshot passes the same gate the publish flow runs."""

    def test_committed_tree_passes_the_publish_smoke(self) -> None:
        frontend = REPO_ROOT / "frontend"
        if not (frontend / "catalogue.json").is_file():
            self.skipTest("no committed catalogue in this checkout")
        report = catalogue.validate(frontend, allow_placeholder=True)
        self.assertTrue(report.ok, report.errors)
        self.assertEqual(report.status, "ok")
        payload = json.loads((frontend / "catalogue.json").read_text())
        self.assertEqual(payload["integrity"]["status"], "ok")
        self.assertEqual(payload["integrity"]["grades"], [])
