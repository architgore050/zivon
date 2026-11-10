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
from urllib.parse import urlparse
from xml.sax.saxutils import escape, quoteattr

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FRONTEND = REPO_ROOT / "frontend"
# Dev-only placeholder. Real deployments MUST set ZIVON_PUBLIC_BASE_URL; the
# generator marks any output built from this value as a placeholder so a
# committed sitemap cannot be mistaken for canonical URLs.
PLACEHOLDER_BASE_URL = "https://zivon.local"
DEFAULT_BASE_URL = PLACEHOLDER_BASE_URL


def get_base_url(explicit: str | None = None) -> str:
    raw = (
        explicit
        if explicit is not None
        else os.environ.get("ZIVON_PUBLIC_BASE_URL", DEFAULT_BASE_URL)
    )
    cleaned = raw.strip().rstrip("/")
    return cleaned or DEFAULT_BASE_URL


def is_placeholder_base(base_url: str | None = None) -> bool:
    return get_base_url(base_url) == PLACEHOLDER_BASE_URL


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


def topic_rel_path_from_href(href: str) -> str | None:
    """Map a courses.js href (relative path OR absolute URL) to a site path.

    Absolute hrefs used to be joined straight onto the frontend dir, which
    silently produced a nonexistent path and skipped the topic. Normalise first
    so an absolute href resolves against the same on-disk tree.
    """
    raw = str(href or "").strip()
    if not raw:
        return None
    if raw.startswith(("http://", "https://", "//")):
        raw = urlparse(raw).path or "/"
    return normalize_topic_path(raw)


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


def generate_sitemap_xml(frontend_dir: Path, base_url: str | None = None) -> str:
    base = get_base_url(base_url)
    entries = parse_courses_js(frontend_dir / "courses.js")
    url_blocks: list[str] = []
    has_any_alternates = False

    latest_ts = ""
    topic_records: list[tuple[str, str, dict[str, str]]] = []
    for item in entries:
        href = str(item.get("href", ""))
        rel_path = topic_rel_path_from_href(href)
        if rel_path is None:
            continue
        topic_dir = frontend_dir / rel_path.strip("/")
        index_file = topic_dir / "index.html"
        manifest_file = topic_dir / "manifest.json"
        if not index_file.is_file():
            print(
                f"gen-seo-files: skipping {href!r}: no {index_file}",
                file=sys.stderr,
            )
            continue
        if not manifest_file.is_file():
            print(
                f"gen-seo-files: skipping {href!r}: no manifest.json beside index.html",
                file=sys.stderr,
            )
            continue
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        lastmod = str(
            manifest.get("generated_at") or item.get("generated_at") or ""
        ).strip()
        latest_ts = max(latest_ts, lastmod)
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
                lines.append(
                    f'    <xhtml:link rel="alternate" '
                    f"hreflang={quoteattr(lang_code)} "
                    f"href={quoteattr(f'{base}{alt_path}')}/>"
                )
            lines.append(
                f'    <xhtml:link rel="alternate" '
                f"hreflang={quoteattr('x-default')} "
                f"href={quoteattr(loc)}/>"
            )
        lines.append("  </url>")
        url_blocks.append("\n".join(lines))

    ns = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
    if has_any_alternates:
        ns += ' xmlns:xhtml="http://www.w3.org/1999/xhtml"'
    header = "<!-- Generated by scripts/gen-seo-files.py; do not edit by hand."
    if is_placeholder_base(base_url):
        header += (
            " PLACEHOLDER base URL: set ZIVON_PUBLIC_BASE_URL and regenerate"
            " before deploying."
        )
    header += " -->\n"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        + header
        + f"<urlset {ns}>\n"
        + "\n".join(url_blocks)
        + "\n</urlset>\n"
    )


def generate_robots_txt(base_url: str | None = None) -> str:
    base = get_base_url(base_url)
    header = "# Generated by scripts/gen-seo-files.py; do not edit by hand.\n"
    if is_placeholder_base(base_url):
        header += "# PLACEHOLDER base URL: set ZIVON_PUBLIC_BASE_URL and regenerate before deploying.\n"
    return (
        header
        + f"User-agent: *\nAllow: /\nDisallow: /healthz\nSitemap: {base}/sitemap.xml\n"
    )


def _set_meta_content(html: str, attr: str, key: str, value: str) -> str:
    pattern = re.compile(
        r"(<meta\s+" + attr + r'="' + re.escape(key) + r'"\s+content=")[^"]*(")'
    )
    escaped = quoteattr(value)[1:-1]  # attribute body without the surrounding quotes
    return pattern.sub(lambda m: m.group(1) + escaped + m.group(2), html)


def update_shell_metadata(
    frontend_dir: Path = DEFAULT_FRONTEND, base_url: str | None = None
) -> Path | None:
    """Make the shell's social-card URLs absolute from the single base URL.

    og:image / twitter:image / og:url MUST be absolute for crawlers; the shell
    is hand-maintained, so the generator rewrites just those three values and
    leaves every other byte alone. Returns the index path it touched, or None.
    """
    index_path = frontend_dir / "index.html"
    if not index_path.is_file():
        return None
    base = get_base_url(base_url)
    html = index_path.read_text(encoding="utf-8")
    html = _set_meta_content(html, "property", "og:image", f"{base}/assets/og-card.png")
    html = _set_meta_content(
        html, "name", "twitter:image", f"{base}/assets/og-card.png"
    )
    if re.search(r'<meta\s+property="og:url"', html):
        html = _set_meta_content(html, "property", "og:url", f"{base}/")
    else:
        og_url = f'<meta property="og:url" content={quoteattr(base + "/")}>'
        html = re.sub(
            r'(<meta\s+property="og:type"\s+content="[^"]*">)',
            lambda m: m.group(1) + "\n" + og_url,
            html,
            count=1,
        )
    index_path.write_text(html, encoding="utf-8")
    return index_path


def write_seo_files(
    frontend_dir: Path = DEFAULT_FRONTEND, base_url: str | None = None
) -> tuple[Path, Path]:
    sitemap_path = frontend_dir / "sitemap.xml"
    robots_path = frontend_dir / "robots.txt"
    sitemap_path.write_text(
        generate_sitemap_xml(frontend_dir, base_url=base_url), encoding="utf-8"
    )
    robots_path.write_text(generate_robots_txt(base_url=base_url), encoding="utf-8")
    update_shell_metadata(frontend_dir, base_url=base_url)
    return sitemap_path, robots_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate frontend/sitemap.xml, robots.txt and shell og: URLs"
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
    parser.add_argument(
        "--allow-placeholder",
        action="store_true",
        help=(
            "Allow generating with the dev placeholder base URL. Without this, "
            "an unset ZIVON_PUBLIC_BASE_URL is a hard error so a deploy never "
            "ships placeholder canonical URLs by accident."
        ),
    )
    args = parser.parse_args(argv)
    resolved = get_base_url(args.base_url)
    if is_placeholder_base(resolved) and not args.allow_placeholder:
        print(
            "gen-seo-files: ZIVON_PUBLIC_BASE_URL is unset (or the dev "
            "placeholder). Set it, or pass --allow-placeholder for local "
            "output that will be clearly marked as a placeholder.",
            file=sys.stderr,
        )
        return 2
    write_seo_files(args.frontend_dir, base_url=resolved)
    return 0


if __name__ == "__main__":
    sys.exit(main())
