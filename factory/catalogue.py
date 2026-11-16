"""Catalogue v2: publish-time catalogue, version guard and integrity smoke (P5).

Stage 11-link already regenerates ``courses.js`` and ``catalogue.json`` from the
same manifest scan (P1's ``factory.render.write_courses_js``). This module is the
PUBLISH half of that contract (P5):

- it derives the browser catalogue (``courses.js``) from the machine catalogue
  (``catalogue.json``), so a product surface can read status, languages,
  counts, concepts and exam weight without re-parsing manifests;
- it resolves route-aware locale hrefs (``localized_hrefs``) from what is
  actually on disk, so a hub never links a locale page that does not exist;
- it records the ``pipeline_version`` of every topic and marks a mixed tree
  instead of publishing one silently;
- it runs the publish smoke: every href/locale/i18n bundle resolves, every page
  carries the P1 hook contract, every sitemap URL exists, no ``Grade`` title
  and no dev placeholder base URL;
- it reports narration coverage honestly (missing assets are listed, never
  claimed as present).

Nothing here calls a model, reads the clock or fetches the network. The CLI is
the publish flow's gate::

    python3 -m factory.catalogue build --frontend-dir frontend
    python3 -m factory.catalogue check --frontend-dir frontend --strict
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import identity
from .hooks import hook_issues

CATALOGUE_NAME = "catalogue.json"
CATALOGUE_VERSION = 2
COURSES_NAME = "courses.js"

# The dev placeholder base URL (scripts/gen-seo-files.py owns the constant).
PLACEHOLDER_BASE_URL = "https://zivon.local"

# Fields copied from a catalogue entry into the browser file. The browser file
# is a DERIVED VIEW, never an independent source of truth.
_COURSES_FIELDS = (
    "href",
    "course_id",
    "class",
    "chapter_number",
    "title",
    "generated_at",
    "lesson_title",
    "status",
    "languages",
    "counts",
    "concepts",
    "exam_weight",
    "pipeline_version",
    "default_locale",
    "locales_available",
    "titles_by_locale",
    "translation_status",
    "localized_hrefs",
    "missing_locales",
)

_LOCALES_WITHOUT_ROUTE = frozenset({"en", "en-IN"})
_LOC_RE = re.compile(r"<loc>([^<]+)</loc>")
_SITEMAP_LINE_RE = re.compile(r"Sitemap:\s*(\S+)")


@dataclass
class CatalogueReport:
    """Everything a publish gate needs to say out loud."""

    ok: bool = True
    status: str = "ok"
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    topics: int = 0
    locales_checked: int = 0
    versions: dict[str, list[str]] = field(default_factory=dict)
    mixed_versions: list[str] = field(default_factory=list)
    missing_versions: list[str] = field(default_factory=list)
    narration: dict[str, Any] = field(default_factory=dict)

    def error(self, message: str) -> None:
        self.errors.append(message)
        self.ok = False

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "errors": self.errors,
            "warnings": self.warnings,
            "topics": self.topics,
            "locales_checked": self.locales_checked,
            "versions": self.versions,
            "mixed_versions": self.mixed_versions,
            "missing_versions": self.missing_versions,
            "narration": self.narration,
        }

    def summary(self) -> str:
        versions = ",".join(sorted(self.versions)) or "none"
        return (
            f"catalogue: status={self.status} topics={self.topics} "
            f"versions={versions} locales={self.locales_checked} "
            f"errors={len(self.errors)} warnings={len(self.warnings)}"
        )


# --------------------------------------------------------------- discovery
def _topic_dirs(frontend_dir: Path) -> list[Path]:
    courses = frontend_dir / "courses"
    if not courses.is_dir():
        return []
    return sorted(p.parent for p in courses.glob("*/*/manifest.json"))


def _read_manifest(topic_dir: Path) -> dict[str, Any]:
    path = topic_dir / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _rel_topic(frontend_dir: Path, topic_dir: Path) -> str:
    return topic_dir.relative_to(frontend_dir).as_posix()


def _topic_href(frontend_dir: Path, topic_dir: Path) -> str:
    return f"{_rel_topic(frontend_dir, topic_dir)}/index.html"


def _promised_locales(manifest: dict[str, Any]) -> list[str]:
    declared = manifest.get("locales_available")
    if not isinstance(declared, list):
        languages = manifest.get("languages")
        if isinstance(languages, dict):
            available = languages.get("available")
            if isinstance(available, list):
                declared = available
    seen: list[str] = []
    for locale in declared or ["en"]:
        text = str(locale)
        if text not in seen:
            seen.append(text)
    return seen


def localized_hrefs(
    frontend_dir: Path, topic_dir: Path, manifest: dict[str, Any]
) -> tuple[dict[str, str], list[str]]:
    """Route-aware locale hrefs for one topic: ``{locale: relative href}``.

    The shipped lesson layout is ``<topic>/<locale>/index.html``; the reserved
    F1 route layout is ``<frontend>/<locale>/<topic>/index.html``. Both are
    accepted, and only a route that EXISTS on disk is advertised. A promised
    locale with no route is returned separately so the caller can report it -
    never silently fall back to English.
    """
    rel = _rel_topic(frontend_dir, topic_dir)
    hrefs: dict[str, str] = {}
    missing: list[str] = []
    for locale in _promised_locales(manifest):
        if locale in _LOCALES_WITHOUT_ROUTE:
            hrefs[locale] = f"{rel}/index.html"
            continue
        shipped = topic_dir / locale / "index.html"
        if shipped.is_file():
            hrefs[locale] = f"{rel}/{locale}/index.html"
            continue
        prefixed = frontend_dir / locale / rel / "index.html"
        if prefixed.is_file():
            hrefs[locale] = f"{locale}/{rel}/index.html"
            continue
        missing.append(locale)
    return hrefs, missing


def _sort_key(entry: dict[str, Any]) -> tuple[Any, ...]:
    chapter = entry.get("chapter")
    chapter_title = (
        chapter if isinstance(chapter, str) else str((chapter or {}).get("title", ""))
    )
    number = entry.get("chapter_number")
    return (
        entry.get("class") or 0,
        number is None,
        number or 0,
        chapter_title.casefold(),
        str(entry.get("title") or ""),
    )


# ------------------------------------------------------------- catalogue v2
def _base_topics(frontend_dir: Path) -> list[dict[str, Any]]:
    """Read the catalogue P1's stage-11 write produced (fresh by definition)."""
    path = frontend_dir / CATALOGUE_NAME
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
        topics = payload.get("topics")
        if isinstance(topics, list):
            return [entry for entry in topics if isinstance(entry, dict)]
    # Standalone use (tests, a hand-audited tree) with no P1 catalogue: fall
    # back to the manifests themselves instead of inventing an empty site.
    return [
        _fallback_entry(topic, _read_manifest(topic), frontend_dir)
        for topic in _topic_dirs(frontend_dir)
    ]


def _fallback_entry(
    topic_dir: Path, manifest: dict[str, Any], frontend_dir: Path
) -> dict[str, Any]:
    """The minimum a catalogue entry needs when P1's file is absent."""
    chapter = manifest.get("chapter") or {}
    entry: dict[str, Any] = {
        "href": _topic_href(frontend_dir, topic_dir),
        "course_id": manifest.get("course_id"),
        "class": manifest.get("class"),
        "title": manifest.get("title"),
        "lesson_title": manifest.get("lesson_title"),
        "chapter": chapter,
        "chapter_number": chapter.get("number") if isinstance(chapter, dict) else None,
        "generated_at": manifest.get("generated_at"),
        "pipeline_version": manifest.get("pipeline_version"),
    }
    for key in (
        "status",
        "languages",
        "counts",
        "concepts",
        "exam_weight",
        "default_locale",
        "locales_available",
        "titles_by_locale",
        "translation_status",
    ):
        if key in manifest:
            entry[key] = manifest[key]
    return entry


def _narration_report(
    frontend_dir: Path, topic_dir: Path, manifest: dict[str, Any]
) -> dict[str, Any]:
    """Availability of read-aloud assets, with every gap named.

    ``manifest.narration.blocks`` is the stage-12 contract: one entry per
    SPEAKABLE unit, ``available: false`` for a unit that failed. Coverage is
    measured against that set, not against every rendered block (diagram and
    simulation blocks are legitimately not narrated). A pre-contract page falls
    back to the narration manifest vs the block map.
    """
    manifest_path = topic_dir / "narration-manifest.json"
    flag = manifest.get("narration")
    flag_blocks = flag.get("blocks") if isinstance(flag, dict) else None
    if isinstance(flag_blocks, dict):
        speakable = [str(block_id) for block_id in flag_blocks]
    else:
        manifest_blocks = manifest.get("blocks") or []
        if isinstance(manifest_blocks, dict):
            speakable = [str(block_id) for block_id in manifest_blocks]
        else:
            speakable = [
                str(b.get("id")) for b in manifest_blocks if isinstance(b, dict)
            ]
    if not manifest_path.is_file():
        return {
            "available": False,
            "manifest": False,
            "blocks_total": len(speakable),
            "blocks_available": 0,
            "missing_assets": [],
            "missing_blocks": speakable,
        }
    narration = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = [e for e in narration.get("blocks", []) if isinstance(e, dict)]
    paths = [str(e.get("path")) for e in entries if e.get("path")]
    missing_assets = [p for p in paths if not (frontend_dir / p).is_file()]
    present = {str(e.get("block_id")) for e in entries if e.get("block_id")}
    if isinstance(flag_blocks, dict):
        available_ids = set()
        for block_id, value in flag_blocks.items():
            if not isinstance(value, dict) or not value.get("available"):
                continue
            path = value.get("path")
            if path and not (frontend_dir / str(path)).is_file():
                continue
            available_ids.add(str(block_id))
    else:
        available_ids = present
    missing_blocks = [bid for bid in speakable if bid not in available_ids]
    return {
        "available": bool(available_ids) and not missing_assets,
        "manifest": True,
        "mode": narration.get("mode"),
        "lang": narration.get("lang"),
        "blocks_total": len(speakable),
        "blocks_available": len(available_ids),
        "missing_assets": missing_assets,
        "missing_blocks": missing_blocks,
    }


def build(
    frontend_dir: Path, *, expected_version: str | None = None
) -> CatalogueReport:
    """Enrich P1's catalogue with locale hrefs + integrity, then write v2.

    Writes BOTH ``catalogue.json`` (machine) and ``courses.js`` (browser) from
    the same enriched entries. The stage-11 caller treats version drift as a
    loud warning; the publish script's strict check treats it as a blocker.
    """
    report = CatalogueReport()
    expected = expected_version or identity.pipeline_version()
    base = _base_topics(frontend_dir)
    if not base:
        report.error("no topic manifests under frontend/courses/ - nothing to publish")
        report.status = "empty"
        return report

    topics: list[dict[str, Any]] = []
    versions: dict[str, list[str]] = {}
    for entry in base:
        topic = dict(entry)
        href = str(topic.get("href") or "")
        if not href:
            report.error("catalogue entry has no href")
            continue
        topic_dir = (frontend_dir / href).parent
        if not (topic_dir / "manifest.json").is_file():
            report.error(f"{href}: manifest.json missing")
            continue
        manifest = _read_manifest(topic_dir)
        version = manifest.get("pipeline_version")
        if version is None:
            report.missing_versions.append(href)
        else:
            versions.setdefault(str(version), []).append(href)
        hrefs, missing = localized_hrefs(frontend_dir, topic_dir, manifest)
        report.locales_checked += len(
            [loc for loc in hrefs if loc not in _LOCALES_WITHOUT_ROUTE]
        )
        topic["localized_hrefs"] = hrefs
        topic["missing_locales"] = missing
        topic["narration"] = _narration_report(frontend_dir, topic_dir, manifest)
        topics.append(topic)

    topics.sort(key=_sort_key)
    report.topics = len(topics)
    report.versions = versions
    if len(versions) > 1 or any(v != expected for v in versions):
        report.mixed_versions = sorted(v for v in versions if v != expected)
        report.status = "mixed"
        report.warn(
            f"catalogue mixes incompatible pipeline_versions "
            f"{sorted(versions)} (expected {expected}); republish every topic "
            "on one version before shipping the snapshot"
        )
    elif report.missing_versions:
        report.status = "incomplete"
        report.warn(
            f"{len(report.missing_versions)} topic(s) have no pipeline_version "
            "(pre-manifest-v2 pages); republish them before shipping the snapshot"
        )

    payload = {
        "catalogue_version": CATALOGUE_VERSION,
        "pipeline_version_expected": expected,
        "integrity": {
            "status": report.status,
            "versions": {version: len(hrefs) for version, hrefs in versions.items()},
            "mixed_versions": report.mixed_versions,
            "missing_versions": report.missing_versions,
            "grades": [
                str(topic.get("href"))
                for topic in topics
                if not identity.is_usable_chapter_title(
                    (topic.get("chapter") or {}).get("title")
                    if isinstance(topic.get("chapter"), dict)
                    else topic.get("chapter")
                )
            ],
        },
        "topics": topics,
    }
    (frontend_dir / CATALOGUE_NAME).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    _write_courses_js(frontend_dir, topics)
    return report


def _courses_entry(topic: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {}
    for key in _COURSES_FIELDS:
        if key in topic:
            entry[key] = topic[key]
    chapter = topic.get("chapter")
    entry["chapter"] = (
        chapter if isinstance(chapter, str) else str((chapter or {}).get("title", ""))
    )
    entry["chapter_number"] = topic.get("chapter_number")
    return entry


def _write_courses_js(frontend_dir: Path, topics: list[dict[str, Any]]) -> None:
    entries = [_courses_entry(topic) for topic in topics]
    payload = json.dumps(entries, indent=2, ensure_ascii=False)
    (frontend_dir / COURSES_NAME).write_text(
        "/* Generated by the Zivon content factory - do not edit by hand.\n"
        "   Stage 11-link derives this browser view from catalogue.json.\n"
        "   Entries are ordered for the landing page: class first, then chapter,\n"
        "   then title - so the class-grouped catalogue renders deterministically. */\n"
        f"window.ZIVON_COURSES = {payload};\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------- validation
def _check_hooks(frontend_dir: Path, report: CatalogueReport) -> None:
    for topic_dir in _topic_dirs(frontend_dir):
        index = topic_dir / "index.html"
        rel = _rel_topic(frontend_dir, topic_dir)
        if not index.is_file():
            report.error(f"{rel}: topic directory has no index.html")
            continue
        manifest = _read_manifest(topic_dir)
        issues = hook_issues(index.read_text(encoding="utf-8"), manifest)
        for issue in issues:
            report.error(f"{rel}: {issue}")


def _check_versions(frontend_dir: Path, expected: str, report: CatalogueReport) -> None:
    versions: dict[str, list[str]] = {}
    for topic_dir in _topic_dirs(frontend_dir):
        rel = _rel_topic(frontend_dir, topic_dir)
        manifest = _read_manifest(topic_dir)
        version = manifest.get("pipeline_version")
        if version is None:
            report.missing_versions.append(rel)
            continue
        versions.setdefault(str(version), []).append(rel)
    report.versions = versions
    if report.missing_versions:
        report.status = "incomplete"
        report.error(
            f"{len(report.missing_versions)} topic(s) have no pipeline_version: "
            + ", ".join(sorted(report.missing_versions))
        )
    if not versions:
        report.status = "incomplete"
        return
    if len(versions) > 1:
        report.status = "mixed"
        report.mixed_versions = sorted(v for v in versions if v != expected)
        detail = "; ".join(
            f"{version}: {', '.join(sorted(hrefs))}"
            for version, hrefs in sorted(versions.items())
        )
        report.error(
            f"catalogue mixes pipeline_versions (expected {expected}): {detail}"
        )
    elif expected not in versions:
        report.status = "mixed"
        report.mixed_versions = sorted(versions)
        report.error(
            f"catalogue is on pipeline_version {sorted(versions)} but this "
            f"publisher expects {expected}; republish the topics on one version"
        )


def _check_manifests(frontend_dir: Path, report: CatalogueReport) -> set[str]:
    listed: set[str] = set()
    for topic_dir in _topic_dirs(frontend_dir):
        rel = _rel_topic(frontend_dir, topic_dir)
        href = f"{rel}/index.html"
        listed.add(href)
        manifest = _read_manifest(topic_dir)
        for key in ("course_id", "class", "topic_slug", "title", "pipeline_version"):
            if manifest.get(key) in (None, ""):
                report.error(f"{rel}: manifest.json has no {key!r}")
        chapter = manifest.get("chapter")
        if not isinstance(chapter, dict):
            report.error(f"{rel}: manifest.json has no chapter object")
            continue
        chapter_title = chapter.get("title")
        if not identity.is_usable_chapter_title(chapter_title):
            report.error(
                f"{rel}: chapter.title={chapter_title!r} is not a usable chapter name"
            )
        if not str(manifest.get("lesson_title") or "").strip():
            report.error(f"{rel}: manifest.json has no lesson_title")
        number = chapter.get("number")
        if not isinstance(number, int):
            report.warn(f"{rel}: chapter_number unknown (catalogue sorts it last)")

        declared = _promised_locales(manifest)
        for locale in declared:
            if locale in _LOCALES_WITHOUT_ROUTE:
                continue
            report.locales_checked += 1
            shipped = topic_dir / locale / "index.html"
            prefixed = frontend_dir / locale / rel / "index.html"
            if not shipped.is_file() and not prefixed.is_file():
                report.error(
                    f"{rel}: promised locale {locale!r} has no localized route"
                )
                continue
            locale_manifest = (
                topic_dir / locale / "manifest.json"
                if shipped.is_file()
                else frontend_dir / locale / rel / "manifest.json"
            )
            if not locale_manifest.is_file():
                report.error(
                    f"{rel}: promised locale {locale!r} has no locale manifest.json "
                    "(the shell's localized read-aloud contract)"
                )
            else:
                loc_payload = json.loads(locale_manifest.read_text(encoding="utf-8"))
                if loc_payload.get("locale") != locale:
                    report.error(
                        f"{rel}: {locale}/manifest.json declares locale "
                        f"{loc_payload.get('locale')!r}"
                    )
            bundle = topic_dir / "i18n" / f"{locale}.json"
            if not bundle.is_file():
                report.error(f"{rel}: promised locale {locale!r} has no i18n bundle")
                continue
            payload = json.loads(bundle.read_text(encoding="utf-8"))
            if payload.get("locale") != locale:
                report.error(
                    f"{rel}: i18n/{locale}.json declares locale "
                    f"{payload.get('locale')!r}"
                )
        if manifest.get("status") == "live":
            available = set(_promised_locales(manifest))
            missing = [loc for loc in ("hi", "hi-Latn") if loc not in available]
            if missing:
                report.error(
                    f"{rel}: live lesson is missing required locale(s) {missing} "
                    "(Q-2: no silent English fallback)"
                )
    return listed


def _sitemap_paths(frontend_dir: Path, report: CatalogueReport) -> list[str]:
    sitemap = frontend_dir / "sitemap.xml"
    if not sitemap.is_file():
        report.error("frontend/sitemap.xml is missing (run scripts/gen-seo-files.py)")
        return []
    text = sitemap.read_text(encoding="utf-8")
    locs = _LOC_RE.findall(text)
    if not locs:
        report.error("frontend/sitemap.xml has no <loc> URLs")
        return []
    paths: list[str] = []
    for loc in locs:
        if PLACEHOLDER_BASE_URL in loc:
            report.warn(
                f"sitemap uses the dev placeholder base URL: {loc} "
                "(regenerate with ZIVON_PUBLIC_BASE_URL before publishing)"
            )
            continue
        path = urlparse(loc).path or "/"
        target = frontend_dir / path.lstrip("/")
        if path.endswith("/"):
            target = target / "index.html"
        if not target.is_file():
            report.error(f"sitemap URL does not resolve to a page: {loc}")
        paths.append(path)
    return paths


def _check_robots(frontend_dir: Path, report: CatalogueReport) -> None:
    robots = frontend_dir / "robots.txt"
    if not robots.is_file():
        report.error("frontend/robots.txt is missing (run scripts/gen-seo-files.py)")
        return
    text = robots.read_text(encoding="utf-8")
    if PLACEHOLDER_BASE_URL in text:
        report.warn(
            "robots.txt points at the dev placeholder base URL "
            "(regenerate with ZIVON_PUBLIC_BASE_URL before publishing)"
        )
    if not _SITEMAP_LINE_RE.search(text):
        report.error("robots.txt has no Sitemap: pointer")


def _check_catalogue_file(
    frontend_dir: Path, listed: set[str], report: CatalogueReport
) -> None:
    path = frontend_dir / CATALOGUE_NAME
    if not path.is_file():
        report.error("frontend/catalogue.json is missing (stage 11-link writes it)")
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    version = payload.get("catalogue_version")
    if version != CATALOGUE_VERSION:
        report.error(
            f"catalogue.json version {version!r} is not {CATALOGUE_VERSION} "
            "(republish through stage 11-link)"
        )
    topics = payload.get("topics")
    if not isinstance(topics, list) or not topics:
        report.error("catalogue.json lists no topics")
        return
    catalogued = {str(topic.get("href")) for topic in topics if isinstance(topic, dict)}
    missing = sorted(listed - catalogued)
    if missing:
        report.error(f"topic page(s) absent from catalogue.json: {missing}")
    extra = sorted(catalogued - listed)
    if extra:
        report.error(f"catalogue.json lists missing page(s): {extra}")
    integrity = payload.get("integrity") or {}
    if integrity.get("status") not in (None, "ok"):
        report.error(
            f"catalogue.json marks the tree {integrity.get('status')!r}: "
            f"mixed={integrity.get('mixed_versions')} "
            f"missing={integrity.get('missing_versions')}"
        )


def _check_courses_js(frontend_dir: Path, report: CatalogueReport) -> None:
    path = frontend_dir / COURSES_NAME
    if not path.is_file():
        report.error("frontend/courses.js is missing")
        return
    text = path.read_text(encoding="utf-8")
    if "window.ZIVON_COURSES" not in text:
        report.error("courses.js does not assign window.ZIVON_COURSES")
    hrefs = re.findall(r'"href"\s*:\s*"([^"]+)"', text)
    for href in hrefs:
        if not (frontend_dir / href).is_file():
            report.error(f"courses.js href does not resolve: {href}")
    catalogue_path = frontend_dir / CATALOGUE_NAME
    if catalogue_path.is_file():
        payload = json.loads(catalogue_path.read_text(encoding="utf-8"))
        catalogue_hrefs = {
            str(topic.get("href"))
            for topic in payload.get("topics", [])
            if isinstance(topic, dict)
        }
        if set(hrefs) != catalogue_hrefs:
            report.error(
                "courses.js is not derived from catalogue.json "
                f"(courses-only={sorted(set(hrefs) - catalogue_hrefs)}, "
                f"catalogue-only={sorted(catalogue_hrefs - set(hrefs))})"
            )


def _check_seo(
    frontend_dir: Path,
    report: CatalogueReport,
    *,
    allow_placeholder: bool,
) -> None:
    _sitemap_paths(frontend_dir, report)
    _check_robots(frontend_dir, report)
    if not allow_placeholder:
        for name in (
            CATALOGUE_NAME,
            COURSES_NAME,
            "sitemap.xml",
            "robots.txt",
            "index.html",
        ):
            path = frontend_dir / name
            if path.is_file() and PLACEHOLDER_BASE_URL in path.read_text(
                encoding="utf-8"
            ):
                report.error(
                    f"{name} contains the dev placeholder base URL "
                    f"{PLACEHOLDER_BASE_URL}; set ZIVON_PUBLIC_BASE_URL and "
                    "regenerate SEO files"
                )


def _check_narration(
    frontend_dir: Path, report: CatalogueReport, *, require: bool
) -> None:
    summary: dict[str, Any] = {
        "topics": 0,
        "with_manifest": 0,
        "missing_manifests": [],
        "missing_assets": {},
        "missing_blocks": {},
        "modes": {},
    }
    for topic_dir in _topic_dirs(frontend_dir):
        rel = _rel_topic(frontend_dir, topic_dir)
        manifest = _read_manifest(topic_dir)
        coverage = _narration_report(frontend_dir, topic_dir, manifest)
        summary["topics"] += 1
        if coverage["manifest"]:
            summary["with_manifest"] += 1
            summary["modes"][str(coverage.get("mode"))] = (
                summary["modes"].get(str(coverage.get("mode")), 0) + 1
            )
        else:
            summary["missing_manifests"].append(rel)
        if coverage["missing_assets"]:
            summary["missing_assets"][rel] = coverage["missing_assets"]
        if coverage["missing_blocks"]:
            summary["missing_blocks"][rel] = coverage["missing_blocks"]
        if require and not coverage["available"]:
            report.error(
                f"{rel}: narration is not available "
                f"({len(coverage['missing_assets'])} missing asset(s), "
                f"{len(coverage['missing_blocks'])} un-narrated block(s))"
            )
    report.narration = summary
    if summary["missing_manifests"]:
        report.warn(
            "narration manifest missing for: " + ", ".join(summary["missing_manifests"])
        )
    if summary["missing_assets"]:
        report.warn(
            "narration assets missing: "
            + "; ".join(
                f"{topic}: {len(paths)} file(s)"
                for topic, paths in summary["missing_assets"].items()
            )
        )


def validate(
    frontend_dir: Path,
    *,
    expected_version: str | None = None,
    allow_placeholder: bool = False,
    require_narration: bool = False,
    check_seo: bool = True,
) -> CatalogueReport:
    """The publish smoke. ``ok`` is false only on technical breakage."""
    report = CatalogueReport()
    topics = _topic_dirs(frontend_dir)
    if not topics:
        report.error("no published topics under frontend/courses/")
        report.status = "empty"
        return report
    expected = expected_version or identity.pipeline_version()
    _check_versions(frontend_dir, expected, report)
    listed = _check_manifests(frontend_dir, report)
    _check_catalogue_file(frontend_dir, listed, report)
    _check_courses_js(frontend_dir, report)
    _check_hooks(frontend_dir, report)
    _check_narration(frontend_dir, report, require=require_narration)
    if check_seo:
        _check_seo(frontend_dir, report, allow_placeholder=allow_placeholder)
    report.topics = len(topics)
    if report.status == "ok" and report.errors:
        report.status = "error"
    return report


# --------------------------------------------------------------------- CLI
def _cmd_build(args: argparse.Namespace) -> int:
    report = build(args.frontend_dir, expected_version=args.expected_version)
    print(report.summary())
    if report.status != "ok":
        print(
            f"catalogue: integrity={report.status} "
            f"mixed={report.mixed_versions} missing={report.missing_versions}",
            file=sys.stderr,
        )
    for message in report.warnings:
        print(f"warning: {message}", file=sys.stderr)
    if args.strict and report.errors:
        for message in report.errors:
            print(f"error: {message}", file=sys.stderr)
        return 1
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    report = validate(
        args.frontend_dir,
        expected_version=args.expected_version,
        allow_placeholder=args.allow_placeholder,
        require_narration=args.require_narration,
        check_seo=not args.skip_seo,
    )
    if args.json:
        print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    else:
        print(report.summary())
        for message in report.warnings:
            print(f"warning: {message}")
        for message in report.errors:
            print(f"error: {message}", file=sys.stderr)
    if args.strict and not report.ok:
        return 1
    return 0 if report.ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build or verify the published catalogue (P5)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def _common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--frontend-dir", type=Path, default=Path("frontend"))
        p.add_argument("--expected-version", default=None)

    build_parser = sub.add_parser("build", help="write catalogue.json + courses.js")
    _common(build_parser)
    build_parser.add_argument("--strict", action="store_true")

    check_parser = sub.add_parser("check", help="run the publish smoke")
    _common(check_parser)
    check_parser.add_argument("--strict", action="store_true")
    check_parser.add_argument(
        "--allow-placeholder",
        action="store_true",
        help="accept the dev placeholder base URL (never for a production publish)",
    )
    check_parser.add_argument(
        "--require-narration",
        action="store_true",
        help="fail when a topic has no usable read-aloud coverage",
    )
    check_parser.add_argument(
        "--skip-seo",
        action="store_true",
        help="skip sitemap/robots checks (pre-copy verification of a staging tree)",
    )
    check_parser.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "build":
        return _cmd_build(args)
    return _cmd_check(args)


if __name__ == "__main__":
    raise SystemExit(main())
