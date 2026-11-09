#!/usr/bin/env python3
"""Static multilingual SEO generator (docs/specs/frontend/seo-plan.md §4-§5, S3).

Reads `frontend/courses.js`, each published `frontend/courses/*/manifest.json`,
and `ZIVON_PUBLIC_BASE_URL` from the environment (config via env, never
hard-coded), and generates:
  1. `frontend/sitemap.xml` — landing URL + one `<url>` entry per published
     catalogue topic (`<loc>` + `<lastmod>` from `manifest.generated_at`), plus
     per-locale `xhtml:link` alternates when localized variants exist on disk.
  2. `frontend/robots.txt` — allow all, `Disallow: /healthz`, and `Sitemap:`
     pointer.
  3. JSON-LD `LearningResource` / `Course` structured data helper (`build_json_ld`)
     for lesson pages from `manifest.json` (used by publish/tests and available
     for the factory renderer hook).

Offline, deterministic, and idempotent. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FRONTEND = REPO_ROOT / "frontend"
DEFAULT_BASE_URL = "https://zivon.local"


def get_base_url(explicit: str | None = None) -> str:
    raw = (
        explicit
        if explicit is not None
        else os.environ.get("ZIVON_PUBLIC_BASE_URL", DEFAULT_BASE_URL)
    )
    cleaned = raw.strip().rstrip("/")
    return cleaned or DEFAULT_BASE_URL


def parse_courses_js(courses_js_path: Path) -> list[dict[str, Any]]:
    if not courses_js_path.is_file():
        return []
    text = courses_js_path.read_text(encoding="utf-8")
    match = re.search(r"window\.ZIVON_COURSES\s*=\s*(\[.*\])\s*;", text, re.DOTALL)
    if not match:
        return []
    data = json.loads(match.group(1))
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def normalize_topic_path(href: str) -> str:
    clean = href.strip().lstrip("/")
    if clean.endswith("/index.html"):
        clean = clean[: -len("index.html")]
    elif not clean.endswith("/"):
        clean = clean + "/"
    return "/" + clean


def discover_locale_alternates(
    frontend_dir: Path, canonical_rel_path: str
) -> dict[str, str]:
    """Return locale -> URL path for localized variants that exist on disk.

    Per seo-plan.md §3: emit hreflang alternates ONLY when localized route trees
    actually exist on disk (never emit a half-built cluster pointing to 404s).
    """
    alternates: dict[str, str] = {}
    rel_clean = canonical_rel_path.strip("/")
    for locale in ("hi", "hi-Latn"):
        candidate_prefix = frontend_dir / locale / rel_clean / "index.html"
        candidate_sub = frontend_dir / rel_clean / locale / "index.html"
        if candidate_prefix.is_file():
            alternates[locale] = f"/{locale}/{rel_clean}/"
        elif candidate_sub.is_file():
            alternates[locale] = f"/{rel_clean}/{locale}/"
    if alternates:
        alternates["en"] = f"/{rel_clean}/"
    return alternates


def build_json_ld(
    manifest: dict[str, Any], base_url: str | None = None
) -> dict[str, Any]:
    """Build schema.org LearningResource / Course JSON-LD from manifest.json."""
    base = get_base_url(base_url)
    course_id = str(manifest.get("course_id", ""))
    topic_slug = str(manifest.get("topic_slug", ""))
    url = f"{base}/courses/{course_id}/{topic_slug}/"
    sources_raw = manifest.get("sources") or []
    based_on: list[dict[str, str]] = []
    for src in sources_raw:
        if isinstance(src, dict):
            based_on.append(
                {
                    "@type": "Book",
                    "name": str(src.get("title", "")),
                    "license": str(src.get("license", "")),
                }
            )
    return {
        "@context": "https://schema.org",
        "@type": ["LearningResource", "Course"],
        "name": str(manifest.get("title", "")),
        "description": (
            f"Interactive Class {manifest.get('class', '')} Physics lesson on "
            f"{manifest.get('title', '')} from NCERT and open sources."
        ),
        "inLanguage": str(manifest.get("lang", "en")),
        "educationalLevel": f"Class {manifest.get('class', '')}",
        "about": {"@type": "Thing", "name": "Physics"},
        "learningResourceType": "interactive lesson",
        "isBasedOn": based_on,
        "dateModified": str(manifest.get("generated_at", "")),
        "provider": {"@type": "Organization", "name": "Zivon"},
        "url": url,
    }


def generate_sitemap_xml(
    frontend_dir: Path, base_url: str | None = None
) -> str:
    base = get_base_url(base_url)
    entries = parse_courses_js(frontend_dir / "courses.js")
    url_blocks: list[str] = []
    has_any_alternates = False

    latest_ts = ""
    topic_records: list[tuple[str, str, dict[str, str]]] = []
    for item in entries:
        href = str(item.get("href", ""))
        if not href:
            continue
        index_file = frontend_dir / href
        manifest_file = index_file.parent / "manifest.json"
        if not index_file.is_file() or not manifest_file.is_file():
            continue
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        lastmod = str(
            manifest.get("generated_at") or item.get("generated_at") or ""
        ).strip()
        if lastmod > latest_ts:
            latest_ts = lastmod
        rel_path = normalize_topic_path(href)
        alts = discover_locale_alternates(frontend_dir, rel_path)
        if alts:
            has_any_alternates = True
        topic_records.append((rel_path, lastmod, alts))

    # 1. Landing page URL
    landing_lines = [
        "  <url>",
        f"    <loc>{escape(base + '/')}</loc>",
    ]
    if latest_ts:
        landing_lines.append(f"    <lastmod>{escape(latest_ts)}</lastmod>")
    landing_lines.append("  </url>")
    url_blocks.append("\n".join(landing_lines))

    # 2. Published topic pages
    for rel_path, lastmod, alts in topic_records:
        loc = f"{base}{rel_path}"
        lines = [
            "  <url>",
            f"    <loc>{escape(loc)}</loc>",
        ]
        if lastmod:
            lines.append(f"    <lastmod>{escape(lastmod)}</lastmod>")
        if alts:
            for lang_code, alt_path in sorted(alts.items()):
                alt_href = escape(f"{base}{alt_path}")
                lines.append(
                    f'    <xhtml:link rel="alternate" hreflang="{escape(lang_code)}" href="{alt_href}"/>'
                )
            lines.append(
                f'    <xhtml:link rel="alternate" hreflang="x-default" href="{escape(loc)}"/>'
            )
        lines.append("  </url>")
        url_blocks.append("\n".join(lines))

    ns = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
    if has_any_alternates:
        ns += ' xmlns:xhtml="http://www.w3.org/1999/xhtml"'
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f"<urlset {ns}>\n"
        + "\n".join(url_blocks)
        + "\n</urlset>\n"
    )


def generate_robots_txt(base_url: str | None = None) -> str:
    base = get_base_url(base_url)
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /healthz\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )


def write_seo_files(
    frontend_dir: Path = DEFAULT_FRONTEND, base_url: str | None = None
) -> tuple[Path, Path]:
    sitemap_path = frontend_dir / "sitemap.xml"
    robots_path = frontend_dir / "robots.txt"
    sitemap_path.write_text(
        generate_sitemap_xml(frontend_dir, base_url=base_url), encoding="utf-8"
    )
    robots_path.write_text(
        generate_robots_txt(base_url=base_url), encoding="utf-8"
    )
    return sitemap_path, robots_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate frontend/sitemap.xml and frontend/robots.txt"
    )
    parser.add_argument(
        "--frontend-dir",
        type=Path,
        default=DEFAULT_FRONTEND,
        help="Path to the frontend directory (default: repo frontend/)",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Override ZIVON_PUBLIC_BASE_URL",
    )
    args = parser.parse_args(argv)
    write_seo_files(args.frontend_dir, base_url=args.base_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
