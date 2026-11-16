"""Catalogue/publish integrity for `EV-E2E-002` (0 model calls, no cluster).

The published tree is a contract between four writers: the factory (topic
directories + manifests), the publish bridge (P5), the hand-maintained shell
(F1) and SEO generation (P5). This checker fails on *technical breakage* -
an entry that points at nothing, a declared locale route that does not exist,
a sitemap URL with no page - and records metadata/publish debt as non-blocking
`minor` findings (the R1 content gate blocks breakage, not debt).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..config import EvalConfig
from ..models import EvalCard, IssueRecord

CHECK_ID = "DET-E2E02-CATALOGUE-INTEGRITY"

_HREF_RE = re.compile(r'"href"\s*:\s*"([^"]+)"')
_ENTRY_RE = re.compile(r"\{[^{}]*?\"href\"[^{}]*?\}", re.DOTALL)
_LOC_RE = re.compile(r"<loc>([^<]+)</loc>")


def _entries(courses_js: Path) -> list[dict[str, Any]]:
    text = courses_js.read_text(encoding="utf-8")
    entries: list[dict[str, Any]] = []
    for chunk in _ENTRY_RE.findall(text):
        try:
            entries.append(json.loads("{" + chunk.strip().rstrip(",") + "}"))
        except json.JSONDecodeError:
            continue
    if not entries:
        entries = [{"href": href} for href in _HREF_RE.findall(text)]
    return entries


def check_catalogue_integrity(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-E2E02-CATALOGUE-INTEGRITY`: entries, locale routes, manifests, sitemap."""
    issues: list[IssueRecord] = []
    metrics = context.setdefault("metrics", {})
    courses_js = cfg.frontend_dir / "courses.js"
    if not courses_js.is_file():
        return [
            IssueRecord(
                severity="fatal",
                check_id=CHECK_ID,
                category="rendering",
                message="frontend/courses.js is missing",
            )
        ]
    entries = _entries(courses_js)
    if not entries:
        return [
            IssueRecord(
                severity="fatal",
                check_id=CHECK_ID,
                category="rendering",
                message="frontend/courses.js lists no catalogue entries",
            )
        ]

    listed: set[str] = set()
    locales_checked = 0
    for entry in entries:
        href = str(entry.get("href") or "")
        if not href:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id=CHECK_ID,
                    category="rendering",
                    message="catalogue entry has no href",
                )
            )
            continue
        page = cfg.frontend_dir / href
        if not page.is_file():
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id=CHECK_ID,
                    category="rendering",
                    message=f"catalogue href does not resolve: {href}",
                )
            )
            continue
        listed.add(str(page.parent.resolve()))
        manifest_path = page.parent / "manifest.json"
        if not manifest_path.is_file():
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id=CHECK_ID,
                    category="rendering",
                    message=f"{href}: manifest.json missing",
                )
            )
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for key in ("course_id", "class", "topic_slug", "title"):
            if manifest.get(key) in (None, ""):
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id=CHECK_ID,
                        category="rendering",
                        message=f"{href}: manifest.json has no {key!r}",
                    )
                )
        chapter_title = str((manifest.get("chapter") or {}).get("title") or "")
        if not chapter_title:
            issues.append(
                IssueRecord(
                    severity="minor",
                    check_id=CHECK_ID,
                    category="content",
                    message=f"{href}: manifest chapter.title is missing (metadata debt)",
                )
            )
        elif chapter_title.strip().lower() in ("grade", "class"):
            issues.append(
                IssueRecord(
                    severity="minor",
                    check_id=CHECK_ID,
                    category="content",
                    message=f"{href}: manifest chapter.title={chapter_title!r} is not a "
                    "chapter name (metadata debt)",
                )
            )
        if manifest.get("pipeline_version") is None:
            issues.append(
                IssueRecord(
                    severity="minor",
                    check_id=CHECK_ID,
                    category="content",
                    message=f"{href}: manifest has no pipeline_version (publish debt)",
                )
            )

        for locale in manifest.get("locales_available", []):
            if locale in ("en", "en-IN"):
                continue
            locales_checked += 1
            localized = page.parent / locale / "index.html"
            if not localized.is_file():
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id=CHECK_ID,
                        category="rendering",
                        message=f"{href}: promised locale {locale!r} has no {locale}/index.html",
                    )
                )
            bundle = page.parent / "i18n" / f"{locale}.json"
            if not bundle.is_file():
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id=CHECK_ID,
                        category="rendering",
                        message=f"{href}: promised locale {locale!r} has no i18n bundle",
                    )
                )
            else:
                payload = json.loads(bundle.read_text(encoding="utf-8"))
                if payload.get("locale") != locale:
                    issues.append(
                        IssueRecord(
                            severity="fatal",
                            check_id=CHECK_ID,
                            category="rendering",
                            message=f"{href}: i18n/{locale}.json declares locale "
                            f"{payload.get('locale')!r}",
                        )
                    )
                if payload.get("status") not in ("verified",):
                    issues.append(
                        IssueRecord(
                            severity="minor",
                            check_id=CHECK_ID,
                            category="content",
                            message=f"{href}: locale {locale!r} status="
                            f"{payload.get('status')!r} (translation debt)",
                        )
                    )

    # Orphan topic directories: built but not in the catalogue.
    courses_dir = cfg.frontend_dir / "courses"
    if courses_dir.is_dir():
        for index in courses_dir.rglob("index.html"):
            parent = index.parent
            if parent.name in ("en", "hi", "hi-Latn") or parent.name.startswith("hi"):
                continue
            if "i18n" in parent.parts:
                continue
            if str(parent.resolve()) not in listed:
                issues.append(
                    IssueRecord(
                        severity="minor",
                        check_id=CHECK_ID,
                        category="content",
                        message=f"{parent.relative_to(cfg.frontend_dir)}: topic page "
                        "exists but is not in courses.js (publish debt)",
                    )
                )

    sitemap = cfg.frontend_dir / "sitemap.xml"
    sitemap_urls = 0
    if sitemap.is_file():
        text = sitemap.read_text(encoding="utf-8")
        for loc in _LOC_RE.findall(text):
            sitemap_urls += 1
            path = urlparse(loc).path or "/"
            if "zivon.local" in loc:
                issues.append(
                    IssueRecord(
                        severity="minor",
                        check_id=CHECK_ID,
                        category="content",
                        message=f"sitemap uses the placeholder base URL: {loc} "
                        "(regenerate with ZIVON_PUBLIC_BASE_URL)",
                    )
                )
                continue
            target = cfg.frontend_dir / path.lstrip("/")
            if path.endswith("/"):
                target = target / "index.html"
            if not target.is_file():
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id=CHECK_ID,
                        category="rendering",
                        message=f"sitemap URL does not resolve to a page: {loc}",
                    )
                )

    metrics["catalogue_entries"] = len(entries)
    metrics["catalogue_locales_checked"] = locales_checked
    metrics["sitemap_urls"] = sitemap_urls
    metrics["catalogue_orphans"] = sum(
        1 for i in issues if "not in courses.js" in i.message
    )
    return issues
