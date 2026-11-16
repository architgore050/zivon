"""Stage 06-render and Stage 10d-transrender: assemble topic pages and staging site.

Renders the ordered blocks into a static, serverless, offline HTML page wired
to the shared zivon.css/zivon.js layer, writes a manifest, regenerates
courses.js, and assembles a complete staging site under the run directory.
Nothing here calls the model. Nothing touches frontend/ - that is stage 11.

Every page carries a strict CSP; all JS is external ('self'), so generated
pages physically cannot make external calls.

Model-authored diagram SVG is rendered exactly as authored: the doctrine §10.7
hand-stroke pass (handify_svg) was retired 2026-11-04 by founder ruling -
diagram geometry is clean; only annotation arrows may carry hand strokes.
"""

from __future__ import annotations

import hashlib
import html as html_mod
import json
import shutil
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from logging_manager import Severity, log_event

from . import identity as ident
from . import sections as section_map
from .artifacts import RunContext, slugify
from .config import Config
from .errors import LintError
from .hooks import hook_issues
from .lint import lint_generated, lint_html, lint_js
from .translate import (
    LOCALE_METADATA,
    extract_diagram_payload,
    extract_sim_strings_from_js,
    is_pure_symbol_or_numeral,
    load_glossary,
    load_ui_strings,
)

STAGE_ID = "06-render"
TRANSRENDER_STAGE_ID = "10d-transrender"

# Element ids from docs/product/ui-element-inventory.csv (EL-LES-01-NNN).
# The renderer marks only the CONTENT elements it actually emits; product
# chrome ids (dock, consent, language bar, report) belong to the shell kit
# (docs/specs/frontend/shell-injection.md §2). An id whose element does not
# exist on a generated page is never emitted as a placeholder.
EL_KICKER = "EL-LES-01-001"
EL_TITLE = "EL-LES-01-002"
EL_OBJECTIVES_LABEL = "EL-LES-01-004"
# EL-LES-01-005 (the objectives list) is deliberately NOT emitted yet: 08-fixloop
# re-extracts the objectives by matching `<ul class="zn-objectives">` exactly,
# so an extra attribute there silently degrades a repaired page. The id lands
# once that rebuild path is hook-aware (tracked in the P1 PR as known debt).
EL_TEXT_PARAGRAPH = "EL-LES-01-010"
EL_DIAGRAM_FIGURE = "EL-LES-01-014"
EL_DIAGRAM_CAPTION = "EL-LES-01-015"
EL_SIM_CARD = "EL-LES-01-018"
EL_SIM_TITLE = "EL-LES-01-019"
EL_SIM_CONTROL = "EL-LES-01-020"
EL_SIM_CANVAS = "EL-LES-01-021"
EL_SIM_MIRROR = "EL-LES-01-022"
EL_CHECK_FIELDSET = "EL-LES-01-025"
EL_CHECK_OPTION = "EL-LES-01-026"
EL_CHECK_NUMERIC = "EL-LES-01-027"
EL_CHECK_BUTTON = "EL-LES-01-028"
EL_CHECK_FEEDBACK = "EL-LES-01-029"
EL_CHECK_WHY = "EL-LES-01-031"
EL_EXAMPLE_PROBLEM = "EL-LES-01-032"
EL_EXAMPLE_STEP = "EL-LES-01-033"
EL_EXAMPLE_ANSWER = "EL-LES-01-034"
EL_REVEAL_DETAILS = "EL-LES-01-035"
EL_GLOSSARY = "EL-LES-01-036"
EL_SOURCES_FOOTER = "EL-LES-01-037"

# Product languages for a lesson (FEATURE-MAP #3 / REQUIREMENTS §7.6). Coverage
# is reported, never promised: `languages.missing` names what does NOT exist in
# this artifact, so a product surface can show the "not available yet" marker.
LESSON_LOCALES = ("en", "hi", "hi-Latn")


# Lesson pages are the ONLY pages that opt into a network connection: the voice
# dock dials the same-origin `wss://<origin>/voice/ws` (ADR-0020 / EX5 client).
# `connect-src 'self'` is the scoped relaxation authorised at P0 wire-up
# (docs/specs/frontend/ws-client-contract.md §8, TIMELINE founder gate 1.2).
# `media-src 'self'` is the same shape of scoped relaxation for §10.13
# read-aloud: narration <audio> files are same-origin build artifacts under
# /audio/<course>/ (C-051 pre-generated), so lesson pages must be allowed to
# load media from their own origin or every narration asset is CSP-blocked.
# Everything else stays locked (`default-src 'none'`, `base-uri 'none'`); the
# nginx server-level header keeps `connect-src 'none'` for every non-lesson
# location, so the relaxation is per-page, not site-wide.
CSP = (
    "default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; media-src 'self'; base-uri 'none'"
)

_SMALL_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


def chapter_display_title(title: str) -> str:
    """NCERT chapter titles are ALL CAPS ("LAWS OF MOTION"); the catalogue and
    the page header want them readable ("Laws of Motion").

    Deterministic on purpose. 2026-11-10 (founder bug report): the topic slug
    and page title were derived from the MODEL'S lesson title, so every run
    invented a fresh headline ("Laws of Motion: From Aristotle's Mistake to
    Newton's Three Laws") and published a SECOND topic directory for the same
    chapter - a tagline in the catalogue and a duplicate page next to the old
    one. The chapter is the identity of a page; the model's headline is not.
    """
    words = [w for w in str(title).split() if w]
    if not words:
        return str(title).strip()
    out: list[str] = []
    for i, word in enumerate(words):
        low = word.lower()
        if 0 < i < len(words) - 1 and low in _SMALL_WORDS:
            out.append(low)
        else:
            out.append(low[:1].upper() + low[1:])
    return " ".join(out)


DEFAULT_UI_STRINGS_EN: dict[str, str] = {
    "lesson.lang.label": "Language",
    "lesson.objectives.heading": "After this lesson you can:",
    "lesson.example.heading": "Worked example",
    "lesson.answer.label": "Answer",
    "lesson.check.submit": "Check",
    "lesson.check.why": "Why?",
    "lesson.check.pick_first": "Pick an option first.",
    "lesson.check.correct": "\u2713 Correct.",
    "lesson.check.wrong": "\u2717 Not yet - try again.",
    "lesson.check.your_answer": "Your answer:",
    "lesson.glossary.heading": "Glossary",
    "lesson.sources.footer": (
        "Generated by the Zivon content factory. Sources are listed in the course index."
    ),
    "lesson.untranslated.block_notice": (
        "This section is currently available in English only."
    ),
    "lesson.untranslated.page_notice": (
        "This lesson is not yet available in the requested language - showing English."
    ),
    "lesson.report.translation_issue": "Report translation issue",
    "lesson.trans.badge": "AI-translated \u00b7 Reviewed",
}


def _ui_for_locale(all_ui: dict[str, dict[str, str]], locale: str) -> dict[str, str]:
    out = dict(DEFAULT_UI_STRINGS_EN)
    for copy_key, by_loc in all_ui.items():
        if isinstance(by_loc, dict):
            val = by_loc.get(locale) or by_loc.get("en")
            if val:
                out[copy_key] = str(val)
    return out


def run(
    cfg: Config,
    run_ctx: RunContext,
    chapter_query: str,
    source_pack: dict[str, Any],
    lesson: dict[str, Any],
    blocks: dict[str, Any],
    interactive: dict[str, Any],
) -> dict[str, Any]:
    # The CHAPTER is the page's identity (2026-11-10): slug + display title are
    # deterministic from the located chapter, so a re-run replaces the same
    # topic directory instead of publishing a model-invented duplicate (the
    # old lesson-title slug produced "laws-of-motion" AND
    # "laws-of-motion-from-aristotle-s-mistake" for one chapter).
    raw_title = source_pack["chapter"]["title"]
    repaired_title = ident.repair_chapter_title(
        raw_title,
        matched_line=source_pack["chapter"].get("matched_line"),
        query=chapter_query,
    )
    if repaired_title is None:
        raise LintError(
            STAGE_ID,
            f"the located chapter title {raw_title!r} does not name a chapter "
            "and no usable fallback exists (matched_line/query). Re-run 01-locate "
            "with the exact chapter title - publishing a placeholder title is "
            "not allowed.",
            artifacts_dir=str(run_ctx.stage_dir(STAGE_ID)),
        )
    display_title = chapter_display_title(repaired_title)
    slug = slugify(display_title)
    # The course folder follows the class of the chapter actually located -
    # the topic decides where it lives, never a config value (2026-11-06).
    class_level = source_pack["chapter"]["class"]
    course_id = f"class-{class_level}-physics"

    # Stable identity + block -> section ownership (P1, 2026-11-15): the page
    # carries chapter/lesson/concept ids, and every block names the lesson
    # section that owns it (authored by the draft when present, derived
    # deterministically otherwise - see factory/sections.py).
    chapter_key = ident.chapter_id(class_level, slug)
    page_blocks = list(blocks["blocks"])
    content_hash = ident.content_hash(chapter_key, lesson, page_blocks)
    ownership = section_map.resolve_sections(lesson, page_blocks)
    page_blocks = section_map.apply_metadata(page_blocks, ownership, chapter_key)

    page_js = "\n\n".join(
        out["files"].get("page.js", "")
        for out in interactive.values()
        if out["files"].get("page.js")
    )
    page_css = "\n\n".join(
        out["files"].get("page.css", "")
        for out in interactive.values()
        if out["files"].get("page.css")
    )

    body = _render_body(lesson, page_blocks, chapter_key)
    html_text = _page_html(
        cfg,
        lesson,
        body,
        slug,
        course_id,
        display_title=display_title,
        has_page_js=bool(page_js.strip()),
        has_page_css=bool(page_css.strip()),
    )

    hits = lint_generated(page_js, page_css, html_text)
    if hits:
        raise LintError(
            STAGE_ID,
            "rendered page violates hard lints:\n" + "\n".join(hits),
            artifacts_dir=str(run_ctx.stage_dir(STAGE_ID)),
        )
    # The hook contract is a producer guarantee, not a reviewer's hope: a page
    # whose blocks cannot be addressed by the product layers never ships.
    hook_problems = hook_issues(html_text)
    if hook_problems:
        raise LintError(
            STAGE_ID,
            "rendered page violates the renderer hook contract:\n"
            + "\n".join(hook_problems),
            artifacts_dir=str(run_ctx.stage_dir(STAGE_ID)),
        )

    # ---- staging site ------------------------------------------------------
    site = run_ctx.stage_dir(STAGE_ID) / "site"
    topic_dir = site / "courses" / course_id / slug
    topic_dir.mkdir(parents=True, exist_ok=True)
    assets_src = cfg.repo_path(cfg.paths["frontend"]) / "assets"
    assets_dst = site / "assets"
    if assets_src.exists():
        shutil.copytree(assets_src, assets_dst, dirs_exist_ok=True)
    if not (assets_dst / "zivon.css").exists():
        raise LintError(
            STAGE_ID,
            "frontend/assets/zivon.css is missing; the shared style layer must exist",
        )

    (topic_dir / "index.html").write_text(html_text, encoding="utf-8")
    if page_js:
        (topic_dir / "page.js").write_text(page_js, encoding="utf-8")
    if page_css:
        (topic_dir / "page.css").write_text(page_css, encoding="utf-8")

    manifest = _manifest_v2(
        cfg=cfg,
        run_ctx=run_ctx,
        source_pack=source_pack,
        lesson=lesson,
        blocks=page_blocks,
        chapter_query=chapter_query,
        chapter_key=chapter_key,
        course_id=course_id,
        slug=slug,
        display_title=display_title,
        content_hash=content_hash,
    )
    (topic_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Landing page + courses.js inside staging so perf can test the real thing.
    shutil.copy2(
        cfg.repo_path(cfg.paths["frontend"]) / "index.html", site / "index.html"
    )
    _write_courses_js(site)

    return {
        "topic_dir": str(topic_dir),
        "site_dir": str(site),
        "manifest": manifest,
        "files": sorted(p.name for p in topic_dir.iterdir()),
        # Honesty channel for the ownership map: how much of it the draft
        # authored versus the renderer derived.
        "hooks": {
            "chapter_id": chapter_key,
            "lesson_id": manifest["lesson_id"],
            "sections": len(manifest["sections"]),
            "blocks": len(page_blocks),
            "sections_authored": ownership.authored,
            "sections_derived": ownership.derived,
            "content_hash": manifest["content_hash"],
        },
    }


# ------------------------------------------------------- manifest / identity
def _lesson_languages(available: list[str] | None = None) -> dict[str, Any]:
    """Language coverage of THIS artifact (never a promise).

    ``available`` lists the locale bundles that exist on disk; ``missing``
    lists the product languages that do not. A surface that sees a locale in
    ``missing`` shows the "not available yet" marker instead of English
    pretending to be Hindi (REQUIREMENTS §7.6).
    """
    locales = ["en"]
    for loc in available or []:
        if loc and loc not in locales:
            locales.append(loc)
    return {
        "default": "en",
        "available": locales,
        "missing": [loc for loc in LESSON_LOCALES if loc not in locales],
    }


def _manifest_counts(blocks: list[dict[str, Any]]) -> dict[str, int]:
    """Counts of what the artifact actually contains.

    Practice and test counts are deliberately ABSENT until P2/P3 produce those
    items: a fabricated ``0`` would read as "this chapter has no practice" when
    the truth is "no practice exists yet".
    """
    by_type: dict[str, int] = {}
    for block in blocks:
        by_type[str(block["type"])] = by_type.get(str(block["type"]), 0) + 1
    return {
        "lesson_blocks": len(blocks),
        "checks": by_type.get("check", 0),
        "worked_examples": by_type.get("worked_example", 0),
        "diagrams": by_type.get("diagram", 0),
        "simulations": by_type.get("simulation", 0),
        "reveals": by_type.get("reveal", 0),
        "text_blocks": by_type.get("text", 0),
    }


def _manifest_sections(
    lesson: dict[str, Any], blocks: list[dict[str, Any]], chapter_key: str
) -> list[dict[str, Any]]:
    titles = {str(s["id"]): str(s.get("title", "")) for s in lesson.get("sections", [])}
    out: list[dict[str, Any]] = []
    for section_id, group in section_map.group_by_section(lesson, blocks):
        if not section_id:
            continue
        out.append(
            {
                "id": section_id,
                "title": titles.get(section_id, ""),
                "concept_id": ident.concept_id(chapter_key, section_id),
                "block_ids": [str(b["id"]) for b in group],
            }
        )
    return out


def _manifest_block_map(
    blocks: list[dict[str, Any]],
) -> dict[str, dict[str, str]]:
    """block id -> {type, section_id, concept_id}: F4's drawer and LES-10
    ``block_view`` read this instead of re-parsing HTML."""
    out: dict[str, dict[str, str]] = {}
    for block in blocks:
        section_id = str(block.get("section_id") or "")
        if not section_id:
            continue
        out[str(block["id"])] = {
            "type": str(block["type"]),
            "section_id": section_id,
            "concept_id": str(block.get("concept_id") or ""),
        }
    return out


def _manifest_v2(
    *,
    cfg: Config,
    run_ctx: RunContext,
    source_pack: dict[str, Any],
    lesson: dict[str, Any],
    blocks: list[dict[str, Any]],
    chapter_query: str,
    chapter_key: str,
    course_id: str,
    slug: str,
    display_title: str,
    content_hash: str,
    locales_available: list[str] | None = None,
) -> dict[str, Any]:
    """The topic manifest, v2 (additive over v1 - see ``schemas.MANIFEST_V2``)."""
    del cfg  # language coverage is a fact about this artifact, not a config
    chapter = source_pack["chapter"]
    section_entries = _manifest_sections(lesson, blocks, chapter_key)
    return {
        "manifest_version": 2,
        "chapter_id": chapter_key,
        "lesson_id": ident.lesson_id(chapter["class"], slug),
        "course_id": course_id,
        "subject": ident.SUBJECT,
        "class": chapter["class"],
        "topic_slug": slug,
        "title": display_title,
        # Additive (2026-11-10): the model's own lesson headline stays on
        # record, but it never names the page or the topic directory.
        "lesson_title": lesson["title"],
        # Status describes what this artifact IS: a lesson page with no
        # practice items or test series attached yet. P2/P3 raise it when they
        # produce those artifacts; publish does not change it.
        "status": "lesson_only",
        "languages": _lesson_languages(locales_available),
        "counts": _manifest_counts(blocks),
        "concepts": [
            {
                "concept_id": entry["concept_id"],
                "section_id": entry["id"],
                "title": entry["title"],
            }
            for entry in section_entries
        ],
        "sections": section_entries,
        "blocks": _manifest_block_map(blocks),
        # `exam_weight` is absent on purpose: only a syllabus manifest (P2) can
        # state a chapter's exam weight from a source. Unknown = absent.
        "pipeline_version": ident.pipeline_version(),
        "content_hash": content_hash,
        "chapter": {
            "query": chapter_query,
            # The title the locator produced, repaired when it was page
            # furniture ("Grade"): an unusable title never reaches a manifest.
            "title": ident.repair_chapter_title(
                chapter["title"],
                matched_line=chapter.get("matched_line"),
                query=chapter_query,
            ),
            "book": chapter["book_title"],
            "pages": chapter["pages"],
            # NCERT numbers run continuously across parts (Part II starts at
            # 8 in class 11 - founder confirmed 2026-11-09); the landing page
            # orders by this. None for non-NCERT topics (sorts last).
            "number": chapter.get("number"),
        },
        "sources": _sources_list(source_pack),
        "run_id": run_ctx.run_id,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "block_counts": _block_counts({"blocks": blocks}),
    }


# ------------------------------------------------------------------ blocks
def _esc(text: Any) -> str:
    return html_mod.escape(str(text), quote=True)


def _block_attrs(block: dict[str, Any], attrs: str = "") -> str:
    """The machine hooks every block element carries.

    ``data-block-type`` is the schema's block type (never inferred from a class
    name), ``data-concept-id`` is the section-scoped concept key. Both are part
    of the shell contract (docs/specs/frontend/shell-injection.md §2).
    """
    block_type = _esc(block["type"])
    concept = _esc(block.get("concept_id") or "")
    out = f' data-block-type="{block_type}"'
    if concept:
        out += f' data-concept-id="{concept}"'
    return out + attrs


def _render_body(
    lesson: dict[str, Any],
    blocks: list[dict[str, Any]],
    chapter_key: str,
    *,
    with_i18n_attrs: bool = False,
    ui_copy: dict[str, str] | None = None,
    fallback_block_ids: frozenset[str] = frozenset(),
) -> str:
    """Render the ordered blocks inside their owning ``<section>`` wrappers.

    A section wrapper is structure only: it carries the section + concept ids
    (and the shell can read the localized title from ``i18n/<locale>.json``),
    never new visible prose - wrapping must not change what the page looks
    like, only what it exposes to machines.
    """
    chunks: list[str] = []
    for section_id, group in section_map.group_by_section(lesson, blocks):
        inner = "\n".join(
            _render_block(
                block,
                with_i18n_attrs=with_i18n_attrs,
                ui_copy=ui_copy,
                is_fallback_en=str(block["id"]) in fallback_block_ids,
            )
            for block in group
        )
        if not section_id:
            chunks.append(inner)
            continue
        concept = _esc(ident.concept_id(chapter_key, section_id))
        chunks.append(
            f'  <section class="zn-section" id="{_esc(section_id)}" '
            f'data-section-id="{_esc(section_id)}" data-concept-id="{concept}">\n'
            f"{inner}\n  </section>"
        )
    return "\n".join(chunks)


def _tag_svg_with_i18n(block_id: str, svg_str: str) -> str:
    """Ensure descriptive <text> nodes in an SVG carry data-i18n attributes."""
    if 'data-i18n="' in svg_str:
        return svg_str
    try:
        root = ET.fromstring(svg_str)
    except ET.ParseError:
        return svg_str
    idx = 0
    for elem in root.iter():
        tag = elem.tag.split("}", 1)[1] if "}" in elem.tag else elem.tag
        if tag in ("text", "tspan"):
            raw = (elem.text or "").strip()
            if raw and not is_pure_symbol_or_numeral(raw):
                elem.set("data-i18n", f"{block_id}.svg_texts.t-{idx}")
                idx += 1
    return ET.tostring(root, encoding="unicode")


def _render_block(
    b: dict[str, Any],
    *,
    with_i18n_attrs: bool = False,
    ui_copy: dict[str, str] | None = None,
    is_fallback_en: bool = False,
) -> str:
    ui = {**DEFAULT_UI_STRINGS_EN, **(ui_copy or {})}
    t, spec = b["type"], b["spec"]
    bid = _esc(b["id"])
    hooks = _block_attrs(b)
    fallback_attr = ' lang="en" data-fallback-en="true"' if is_fallback_en else ""
    fallback_banner = (
        f'    <p class="zn-untranslated-notice" data-i18n="ui.untranslated_block_notice">'
        f"{_esc(ui['lesson.untranslated.block_notice'])}</p>\n"
        if is_fallback_en
        else ""
    )

    if t == "text":
        if with_i18n_attrs:
            paras = "\n".join(
                f'    <p data-element-id="{EL_TEXT_PARAGRAPH}" '
                f'data-i18n="{bid}.paragraphs.{i}">{_esc(p)}</p>'
                for i, p in enumerate(spec.get("paragraphs", []))
            )
            return (
                f'  <section class="zn-text" id="{bid}"{hooks}{fallback_attr}>\n'
                f"{fallback_banner}{paras}\n  </section>"
            )
        paras = "\n".join(
            f'    <p data-element-id="{EL_TEXT_PARAGRAPH}">{_esc(p)}</p>'
            for p in spec.get("paragraphs", [])
        )
        # Every rendered block element carries its stable block id: the shell
        # kit keys read-aloud controls (§10.13), the context snapshot and the
        # tutor highlight off it. The non-i18n path must not drop it.
        return f'  <section class="zn-text" id="{bid}"{hooks}>\n{paras}\n  </section>'

    if t == "worked_example":
        if with_i18n_attrs:
            steps = "\n".join(
                f'      <li data-element-id="{EL_EXAMPLE_STEP}">'
                f'<strong data-i18n="{bid}.steps.{i}.title">{_esc(s.get("title", ""))}</strong> '
                f'<span data-i18n="{bid}.steps.{i}.detail">{_esc(s.get("detail", ""))}</span></li>'
                for i, s in enumerate(spec.get("steps", []))
            )
            return (
                f'  <section class="zn-example" id="{bid}"{hooks}{fallback_attr}>\n'
                f"{fallback_banner}"
                f'    <h3 data-i18n="ui.example_heading">{_esc(ui["lesson.example.heading"])}</h3>\n'
                f'    <p class="zn-example-problem" data-element-id="{EL_EXAMPLE_PROBLEM}" '
                f'data-i18n="{bid}.problem">{_esc(spec.get("problem", ""))}</p>\n'
                f"    <ol>\n{steps}\n    </ol>\n"
                f'    <p class="zn-answer"><span class="zn-answer-label" data-i18n="ui.answer_label">'
                f"{_esc(ui['lesson.answer.label'])}</span> "
                f'<span data-element-id="{EL_EXAMPLE_ANSWER}" '
                f'data-i18n="{bid}.answer">{_esc(spec.get("answer", ""))}</span></p>\n'
                "  </section>"
            )
        steps = "\n".join(
            f'      <li data-element-id="{EL_EXAMPLE_STEP}">'
            f"<strong>{_esc(s.get('title', ''))}</strong> {_esc(s.get('detail', ''))}</li>"
            for s in spec.get("steps", [])
        )
        return (
            f'  <section class="zn-example" id="{bid}"{hooks}>\n'
            f"    <h3>Worked example</h3>\n"
            f'    <p class="zn-example-problem" data-element-id="{EL_EXAMPLE_PROBLEM}">'
            f"{_esc(spec.get('problem', ''))}</p>\n"
            f"    <ol>\n{steps}\n    </ol>\n"
            f'    <p class="zn-answer"><span class="zn-answer-label">Answer</span> '
            f'<span data-element-id="{EL_EXAMPLE_ANSWER}">'
            f"{_esc(spec.get('answer', ''))}</span></p>\n"
            "  </section>"
        )

    if t == "check":
        return _render_check(
            b,
            with_i18n_attrs=with_i18n_attrs,
            ui=ui,
            fallback_attr=fallback_attr,
            fallback_banner=fallback_banner,
        )

    if t == "reveal":
        if with_i18n_attrs:
            steps = "\n".join(
                f'      <details class="zn-reveal-step" data-element-id="{EL_REVEAL_DETAILS}">'
                f'<summary data-i18n="{bid}.steps.{i}.title">{_esc(s.get("title", ""))}</summary>'
                f'<p data-i18n="{bid}.steps.{i}.detail">{_esc(s.get("detail", ""))}</p></details>'
                for i, s in enumerate(spec.get("steps", []))
            )
            return (
                f'  <section class="zn-reveal" id="{bid}"{hooks}{fallback_attr}>\n'
                f"{fallback_banner}"
                f'    <h3 data-i18n="{bid}.title">{_esc(spec.get("title", ""))}</h3>\n{steps}\n  </section>'
            )
        steps = "\n".join(
            f'      <details class="zn-reveal-step" data-element-id="{EL_REVEAL_DETAILS}">'
            f"<summary>{_esc(s.get('title', ''))}</summary>"
            f"<p>{_esc(s.get('detail', ''))}</p></details>"
            for s in spec.get("steps", [])
        )
        return (
            f'  <section class="zn-reveal" id="{bid}"{hooks}>\n'
            f"    <h3>{_esc(spec.get('title', ''))}</h3>\n{steps}\n  </section>"
        )

    if t == "diagram":
        if with_i18n_attrs:
            tagged_svg = _tag_svg_with_i18n(str(b["id"]), str(spec.get("svg", "")))
            return (
                f'  <figure class="zn-diagram" id="{bid}" '
                f'data-element-id="{EL_DIAGRAM_FIGURE}"{hooks}{fallback_attr}>\n'
                f"{fallback_banner}"
                f'    <div class="zn-diagram-svg">{tagged_svg}</div>\n'
                f'    <figcaption data-element-id="{EL_DIAGRAM_CAPTION}" '
                f'data-i18n="{bid}.caption">{_esc(spec.get("caption", ""))}</figcaption>\n  </figure>'
            )
        return (
            f'  <figure class="zn-diagram" id="{bid}" '
            f'data-element-id="{EL_DIAGRAM_FIGURE}"{hooks}>\n'
            f'    <div class="zn-diagram-svg">{spec.get("svg", "")!s}</div>\n'
            f'    <figcaption data-element-id="{EL_DIAGRAM_CAPTION}">'
            f"{_esc(spec.get('caption', ''))}</figcaption>\n  </figure>"
        )

    if t == "simulation":
        return _render_simulation(
            b,
            with_i18n_attrs=with_i18n_attrs,
            fallback_attr=fallback_attr,
            fallback_banner=fallback_banner,
        )

    raise ValueError(f"unknown block type {t!r}")  # schema prevents this


def _render_check(
    b: dict[str, Any],
    *,
    with_i18n_attrs: bool = False,
    ui: dict[str, str] | None = None,
    fallback_attr: str = "",
    fallback_banner: str = "",
) -> str:
    ui_map = {**DEFAULT_UI_STRINGS_EN, **(ui or {})}
    spec = b["spec"]
    qid = _esc(b["id"])
    hooks = _block_attrs(b)
    q = _esc(spec.get("question", ""))
    fmt = spec.get("format")
    if fmt == "mcq":
        if with_i18n_attrs:
            inputs = "\n".join(
                f'      <label class="zn-opt" data-element-id="{EL_CHECK_OPTION}">'
                f'<input type="radio" name="check-{qid}" value="{i}"> '
                f'<span data-i18n="{qid}.options.{i}">{_esc(opt)}</span></label>'
                for i, opt in enumerate(spec.get("options", []))
            )
        else:
            inputs = "\n".join(
                f'      <label class="zn-opt" data-element-id="{EL_CHECK_OPTION}">'
                f'<input type="radio" name="check-{qid}" value="{i}"> '
                f"<span>{_esc(opt)}</span></label>"
                for i, opt in enumerate(spec.get("options", []))
            )
        data = f'data-answer-index="{int(spec.get("answer_index", -1))}"'
    else:
        prompt_lbl = _esc(ui_map["lesson.check.your_answer"])
        if with_i18n_attrs:
            inputs = (
                f'      <label class="zn-opt zn-opt-numeric" '
                f'data-element-id="{EL_CHECK_NUMERIC}">'
                f'<span data-i18n="ui.check_your_answer">{prompt_lbl}</span> '
                f'<input type="text" inputmode="decimal" class="zn-numeric-input" name="check-{qid}-input"></label>'
            )
        else:
            inputs = (
                f'      <label class="zn-opt zn-opt-numeric" '
                f'data-element-id="{EL_CHECK_NUMERIC}">Your answer: '
                f'<input type="text" inputmode="decimal" class="zn-numeric-input" name="check-{qid}-input"></label>'
            )
        data = f'data-answer="{_esc(spec.get("answer", ""))}"'
    explanation = _esc(spec.get("explanation", ""))
    if with_i18n_attrs:
        return (
            f'  <fieldset class="zn-check" id="{qid}" data-element-id="{EL_CHECK_FIELDSET}" '
            f'data-format="{fmt}" {data}{hooks}{fallback_attr}>\n'
            f"{fallback_banner}"
            f'    <legend data-i18n="{qid}.question">{q}</legend>\n{inputs}\n'
            f'    <button type="button" class="zn-check-btn" data-element-id="{EL_CHECK_BUTTON}" '
            f'data-i18n="ui.check_submit">'
            f"{_esc(ui_map['lesson.check.submit'])}</button>\n"
            f'    <p class="zn-check-feedback" data-element-id="{EL_CHECK_FEEDBACK}" '
            f'aria-live="polite"></p>\n'
            f'    <details class="zn-check-why" data-element-id="{EL_CHECK_WHY}">'
            f'<summary data-i18n="ui.check_why">'
            f"{_esc(ui_map['lesson.check.why'])}</summary>"
            f'<p data-i18n="{qid}.explanation">{explanation}</p></details>\n'
            "  </fieldset>"
        )
    return (
        f'  <fieldset class="zn-check" id="{qid}" data-element-id="{EL_CHECK_FIELDSET}" '
        f'data-format="{fmt}" {data}{hooks}>\n'
        f"    <legend>{q}</legend>\n{inputs}\n"
        f'    <button type="button" class="zn-check-btn" '
        f'data-element-id="{EL_CHECK_BUTTON}">Check</button>\n'
        f'    <p class="zn-check-feedback" data-element-id="{EL_CHECK_FEEDBACK}" '
        f'aria-live="polite"></p>\n'
        f'    <details class="zn-check-why" data-element-id="{EL_CHECK_WHY}">'
        f"<summary>Why?</summary><p>{explanation}</p></details>\n"
        "  </fieldset>"
    )


def _render_simulation(
    b: dict[str, Any],
    *,
    with_i18n_attrs: bool = False,
    fallback_attr: str = "",
    fallback_banner: str = "",
) -> str:
    spec = b["spec"]
    sid = _esc(b["id"])
    hooks = _block_attrs(b)
    if with_i18n_attrs:
        controls = "\n".join(
            f'      <label class="zn-sim-control" data-element-id="{EL_SIM_CONTROL}">'
            f'<span data-i18n="{sid}.controls.{_esc(c.get("id"))}.label">'
            f"{_esc(c.get('label', c.get('id')))}</span>"
            f'<input type="range" data-control="{_esc(c.get("id"))}" min="{_esc(c.get("min", 0))}" '
            f'max="{_esc(c.get("max", 100))}" step="{_esc(c.get("step", 1))}" value="{_esc(c.get("initial", 0))}">'
            f"<output>{_esc(c.get('initial', 0))}</output></label>"
            for c in spec.get("controls", [])
        )
        return (
            f'  <section class="zn-sim zn-sim-{sid}" id="{sid}" data-element-id="{EL_SIM_CARD}" '
            f'data-sim-id="{sid}" '
            f'aria-label="{_esc(spec.get("title", ""))}"{hooks}{fallback_attr}>\n'
            f"{fallback_banner}"
            f'    <h3 data-element-id="{EL_SIM_TITLE}" '
            f'data-i18n="{sid}.title">{_esc(spec.get("title", ""))}</h3>\n'
            f'    <div class="zn-sim-controls">\n{controls}\n    </div>\n'
            f'    <div class="zn-sim-canvas-wrap"><canvas class="zn-sim-canvas" '
            f'data-element-id="{EL_SIM_CANVAS}" width="480" '
            f'height="320" tabindex="0" aria-label="{_esc(spec.get("title", ""))} drawing"></canvas></div>\n'
            f'    <p class="zn-sim-read" data-element-id="{EL_SIM_MIRROR}" aria-live="polite"></p>\n'
            f'    <p class="zn-sim-desc" data-i18n="{sid}.description">{_esc(spec.get("description", ""))}</p>\n'
            "  </section>"
        )
    controls = "\n".join(
        f'      <label class="zn-sim-control" data-element-id="{EL_SIM_CONTROL}">'
        f"<span>{_esc(c.get('label', c.get('id')))}</span>"
        f'<input type="range" data-control="{_esc(c.get("id"))}" min="{_esc(c.get("min", 0))}" '
        f'max="{_esc(c.get("max", 100))}" step="{_esc(c.get("step", 1))}" value="{_esc(c.get("initial", 0))}">'
        f"<output>{_esc(c.get('initial', 0))}</output></label>"
        for c in spec.get("controls", [])
    )
    return (
        f'  <section class="zn-sim zn-sim-{sid}" id="{sid}" data-element-id="{EL_SIM_CARD}" '
        f'data-sim-id="{sid}" '
        f'aria-label="{_esc(spec.get("title", ""))}"{hooks}>\n'
        f'    <h3 data-element-id="{EL_SIM_TITLE}">{_esc(spec.get("title", ""))}</h3>\n'
        f'    <div class="zn-sim-controls">\n{controls}\n    </div>\n'
        f'    <div class="zn-sim-canvas-wrap"><canvas class="zn-sim-canvas" '
        f'data-element-id="{EL_SIM_CANVAS}" width="480" '
        f'height="320" tabindex="0" aria-label="{_esc(spec.get("title", ""))} drawing"></canvas></div>\n'
        f'    <p class="zn-sim-read" data-element-id="{EL_SIM_MIRROR}" aria-live="polite"></p>\n'
        f'    <p class="zn-sim-desc">{_esc(spec.get("description", ""))}</p>\n'
        "  </section>"
    )


def _build_lang_bar(
    current_locale: str,
    locales_available: list[str],
    ui_copy: dict[str, str],
    *,
    is_subroute: bool = False,
) -> str:
    """Build the sticky .zn-lang-bar per docs/specs/translation/spec.md §5.2."""
    ordered = ["en"] + [loc for loc in locales_available if loc != "en"]
    for default_loc in ("hi", "hi-Latn"):
        if default_loc not in ordered:
            ordered.append(default_loc)

    def _chip_html(loc: str) -> str:
        meta = LOCALE_METADATA.get(loc, {"autonym": loc, "script": "Latn"})
        autonym = _esc(meta["autonym"])
        checked = "true" if loc == current_locale else "false"
        if is_subroute:
            href = (
                "../index.html"
                if loc == "en"
                else ("index.html" if loc == current_locale else f"../{loc}/index.html")
            )
        else:
            href = "index.html" if loc == "en" else f"{loc}/index.html"
        lang_attr = f' lang="{_esc(loc)}"' if loc != "en" else ""
        disabled_attr = (
            ' aria-disabled="true"'
            if loc not in locales_available and loc != "en"
            else ""
        )
        return (
            f'<button type="button" class="zn-chip" role="radio" '
            f'data-locale="{_esc(loc)}" data-href="{_esc(href)}"{lang_attr}{disabled_attr} '
            f'aria-checked="{checked}">{autonym}</button>'
        )

    if len(ordered) >= 5:
        inline_locs = ordered[:3]
        if current_locale not in inline_locs and current_locale in ordered:
            inline_locs = [ordered[0], ordered[1], current_locale]
        more_locs = [loc for loc in ordered if loc not in inline_locs]
        inline_chips = "".join(_chip_html(loc) for loc in inline_locs)
        more_chips = "".join(_chip_html(loc) for loc in more_locs)
        chips_html = (
            f"{inline_chips}"
            f'<details class="zn-lang-more"><summary class="zn-chip">More \u00b7 \u092d\u093e\u0937\u093e\u090f\u0901</summary>'
            f'<div class="zn-lang-more-list">{more_chips}</div></details>'
        )
    else:
        chips_html = "".join(_chip_html(loc) for loc in ordered)

    badge_hidden = " hidden" if current_locale == "en" else ""
    badge_text = _esc(
        ui_copy.get("lesson.trans.badge", DEFAULT_UI_STRINGS_EN["lesson.trans.badge"])
    )
    lang_label = _esc(
        ui_copy.get("lesson.lang.label", DEFAULT_UI_STRINGS_EN["lesson.lang.label"])
    )
    return (
        f'<header class="zn-lang-bar" data-current-locale="{_esc(current_locale)}">'
        f'<div class="zn-lang-in">'
        f'<span class="zn-lang-lab" data-i18n="ui.lang_label">{lang_label}</span>'
        f'<div class="zn-lang-row" role="radiogroup" aria-label="Language">'
        f"{chips_html}"
        f"</div>"
        f'<span class="zn-trans-badge" data-i18n="ui.trans_badge"{badge_hidden}>{badge_text}</span>'
        f"</div></header>"
    )


# -------------------------------------------------------------------- page
def _page_html(
    cfg: Config,
    lesson: dict[str, Any],
    body: str,
    slug: str,
    course_id: str,
    has_page_js: bool,
    has_page_css: bool = False,
    *,
    locale: str = "en",
    locales_available: list[str] | None = None,
    ui_copy: dict[str, str] | None = None,
    has_i18n_js: bool = False,
    with_i18n_attrs: bool = False,
    display_title: str | None = None,
) -> str:
    del cfg, slug
    # The chapter names the page (2026-11-10): the model lesson title is a
    # headline inside the lesson, never the page/catalogue identity.
    title = display_title or lesson["title"]
    ui = {**DEFAULT_UI_STRINGS_EN, **(ui_copy or {})}
    is_subroute = locale != "en"
    assets_prefix = "../../../../assets" if is_subroute else "../../../assets"
    local_prefix = "../" if is_subroute else ""

    if with_i18n_attrs:
        objectives = "\n".join(
            f'      <li data-i18n="b-00-meta.objectives.{i}">{_esc(o)}</li>'
            for i, o in enumerate(lesson["objectives"])
        )
        glossary = "\n".join(
            f'      <dt data-i18n="b-00-meta.glossary.{i}.term">{_esc(g["term"])}</dt>'
            f'<dd data-i18n="b-00-meta.glossary.{i}.definition">{_esc(g["definition"])}</dd>'
            for i, g in enumerate(lesson["glossary"])
        )
    else:
        objectives = "\n".join(
            f"      <li>{_esc(o)}</li>" for o in lesson["objectives"]
        )
        glossary = "\n".join(
            f"      <dt>{_esc(g['term'])}</dt><dd>{_esc(g['definition'])}</dd>"
            for g in lesson["glossary"]
        )

    page_js_tag = (
        f'<script src="{local_prefix}page.js"></script>' if has_page_js else ""
    )
    page_css_tag = (
        f'<link rel="stylesheet" href="{local_prefix}page.css">' if has_page_css else ""
    )
    i18n_js_tag = (
        f'<script src="{local_prefix}i18n.js"></script>\n' if has_i18n_js else ""
    )

    if with_i18n_attrs:
        avail = locales_available or ["en"]
        lang_bar = _build_lang_bar(locale, avail, ui, is_subroute=is_subroute)
        script_code = LOCALE_METADATA.get(locale, {}).get("script", "Latn")
        html_open = f'<html lang="{_esc(locale)}" data-script="{_esc(script_code)}">'
        alt_links = []
        for alt_loc in avail:
            alt_href = (
                ("../index.html" if is_subroute else "index.html")
                if alt_loc == "en"
                else (
                    "index.html"
                    if (is_subroute and alt_loc == locale)
                    else (
                        f"../{alt_loc}/index.html"
                        if is_subroute
                        else f"{alt_loc}/index.html"
                    )
                )
            )
            alt_links.append(
                f'<link rel="alternate" hreflang="{_esc(alt_loc)}" href="{_esc(alt_href)}">'
            )
        canonical_href = "../index.html" if is_subroute else "index.html"
        seo_links = f'<link rel="canonical" href="{canonical_href}">\n' + (
            "\n".join(alt_links) + "\n" if alt_links else ""
        )
        title_attr = ' data-i18n="b-00-meta.title"'
        obj_lbl_attr = ' data-i18n="ui.objectives_heading"'
        gloss_lbl_attr = ' data-i18n="ui.glossary_heading"'
        sources_attr = ' data-i18n="ui.sources_footer"'
    else:
        lang_bar = (
            '<header class="zn-lang-bar"><div class="zn-lang-in">'
            '<span class="zn-lang-lab">Language</span>'
            '<div class="zn-lang-row" role="radiogroup" aria-label="Language">'
            '<button type="button" class="zn-chip" role="radio" aria-checked="true">English</button>'
            '<button type="button" class="zn-chip" role="radio" aria-checked="false">हिन्दी</button>'
            '<button type="button" class="zn-chip" role="radio" aria-checked="false">Hinglish</button>'
            "</div></div></header>"
        )
        html_open = '<html lang="en">'
        seo_links = ""
        title_attr = ""
        obj_lbl_attr = ""
        gloss_lbl_attr = ""
        sources_attr = ""

    return f"""<!doctype html>
{html_open}
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta http-equiv="Content-Security-Policy" content="{CSP}">
<title>{_esc(title)} - Zivon</title>
{seo_links}<link rel="stylesheet" href="{assets_prefix}/zivon.css">
{page_css_tag}
</head>
<body>
{lang_bar}
<main class="zn-page">
  <header class="zn-header">
    <p class="zn-kicker" data-element-id="{EL_KICKER}">{_esc(course_id)}</p>
    <h1 class="zn-title" data-element-id="{EL_TITLE}"{title_attr}>{_esc(title)}</h1>
    <p class="zn-objectives-label" data-element-id="{EL_OBJECTIVES_LABEL}"{obj_lbl_attr}>{_esc(ui["lesson.objectives.heading"])}</p>
    <ul class="zn-objectives">
{objectives}
    </ul>
  </header>
{body}
  <section class="zn-glossary">
    <h2{gloss_lbl_attr}>{_esc(ui["lesson.glossary.heading"])}</h2>
    <dl data-element-id="{EL_GLOSSARY}">
{glossary}
    </dl>
  </section>
  <footer class="zn-footer">
    <p class="zn-sources" data-element-id="{EL_SOURCES_FOOTER}"{sources_attr}>{_esc(ui["lesson.sources.footer"])}</p>
  </footer>
</main>
{i18n_js_tag}<script src="{assets_prefix}/zivon.js"></script>
{page_js_tag}
</body>
</html>
"""


def _sources_list(source_pack: dict[str, Any]) -> list[dict[str, str]]:
    ch = source_pack["chapter"]
    out = [
        {
            "id": ch["book_id"],
            "title": ch["book_title"],
            "license": "NCERT (free educational use)",
        }
    ]
    seen = {ch["book_id"]}
    for s in source_pack["supplements"]:
        if s["book_id"] not in seen:
            seen.add(s["book_id"])
            out.append(
                {
                    "id": s["book_id"],
                    "title": s["book_title"],
                    "license": "see sources catalog",
                }
            )
    return out


def _block_counts(blocks: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for b in blocks["blocks"]:
        counts[b["type"]] = counts.get(b["type"], 0) + 1
    return counts


CATALOGUE_NAME = "catalogue.json"

# The manifest keys the machine catalogue reuses verbatim (manifest v2 core).
# A v1 manifest simply lacks some of them: absence means "unknown", which is
# exactly what the reader must treat it as - nothing is invented to fill a gap.
_CATALOGUE_CORE_KEYS = (
    "manifest_version",
    "chapter_id",
    "lesson_id",
    "course_id",
    "class",
    "subject",
    "title",
    "lesson_title",
    "chapter",
    "status",
    "languages",
    "counts",
    "concepts",
    "exam_weight",
    "pipeline_version",
    "content_hash",
    "default_locale",
    "locales_available",
    "titles_by_locale",
    "translation_status",
)


def _topic_manifests(frontend_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Every topic manifest under ``courses/`` (locale manifests live deeper)."""
    courses_dir = frontend_dir / "courses"
    if not courses_dir.exists():
        return []
    out: list[tuple[Path, dict[str, Any]]] = []
    for manifest_path in sorted(courses_dir.glob("*/*/manifest.json")):
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append((manifest_path.parent, data))
    return out


def _topic_sort_key(entry: dict[str, Any]) -> tuple[Any, ...]:
    """Catalogue order: class, then NCERT chapter number, then chapter, title."""
    chapter = entry.get("chapter")
    chapter_title = (
        chapter if isinstance(chapter, str) else str((chapter or {}).get("title", ""))
    )
    return (
        entry["class"],
        entry.get("chapter_number") is None,
        entry.get("chapter_number") or 0,
        chapter_title.casefold(),
        entry.get("title", ""),
    )


def _courses_entry(
    parent: Path, data: dict[str, Any], frontend_dir: Path
) -> dict[str, Any]:
    rel = parent.relative_to(frontend_dir).as_posix()
    entry: dict[str, Any] = {
        "href": f"{rel}/index.html",
        "course_id": data["course_id"],
        "class": data["class"],
        "chapter_number": data["chapter"].get("number"),
        "title": data["title"],
        "chapter": data["chapter"]["title"],
        "generated_at": data["generated_at"],
    }
    for opt_key in (
        "default_locale",
        "locales_available",
        "titles_by_locale",
        "translation_status",
    ):
        if opt_key in data:
            entry[opt_key] = data[opt_key]
    return entry


def _catalogue_entry(
    parent: Path, data: dict[str, Any], frontend_dir: Path
) -> dict[str, Any]:
    """One catalogue entry: the manifest v2 core + the two location fields."""
    rel = parent.relative_to(frontend_dir).as_posix()
    entry: dict[str, Any] = {"href": f"{rel}/index.html"}
    for key in _CATALOGUE_CORE_KEYS:
        if key in data:
            entry[key] = data[key]
    # Reuse the catalogue order keys without duplicating them in every read.
    entry["chapter_number"] = data.get("chapter", {}).get("number")
    entry["generated_at"] = data.get("generated_at")
    return entry


def write_catalogue(frontend_dir: Path) -> list[dict[str, Any]]:
    """Write ``catalogue.json``: the machine-readable topic catalogue.

    ``courses.js`` is the browser file (``window.ZIVON_COURSES``); both are
    derived from the SAME topic manifests in one pass, so they can never
    disagree. Product layers (catalogue pages, dashboards, imports) read
    ``catalogue.json``; an entry that predates manifest v2 simply omits the
    keys it does not carry.
    """
    topics = [
        _catalogue_entry(parent, data, frontend_dir)
        for parent, data in _topic_manifests(frontend_dir)
    ]
    topics.sort(key=_topic_sort_key)
    payload = {"catalogue_version": 1, "topics": topics}
    (frontend_dir / CATALOGUE_NAME).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return topics


def write_courses_js(frontend_dir: Path) -> list[dict[str, Any]]:
    """Regenerate courses.js (and catalogue.json) from every manifest under
    frontend/courses/. Exposed here so stage 11-link reuses exactly this
    logic."""
    entries = [
        _courses_entry(parent, data, frontend_dir)
        for parent, data in _topic_manifests(frontend_dir)
    ]
    entries.sort(key=_topic_sort_key)
    payload = json.dumps(entries, indent=2, ensure_ascii=False)
    (frontend_dir / "courses.js").write_text(
        "/* Generated by the Zivon content factory - do not edit by hand.\n"
        "   Regenerated on every successful pipeline run (stage 11-link).\n"
        "   Entries are ordered for the landing page: class first, then chapter,\n"
        "   then title - so the class-grouped catalogue renders deterministically. */\n"
        f"window.ZIVON_COURSES = {payload};\n",
        encoding="utf-8",
    )
    write_catalogue(frontend_dir)
    return entries


def _write_courses_js(site_dir: Path) -> None:
    write_courses_js(site_dir)


def _flatten_strings_map(
    lesson: dict[str, Any],
    blocks: list[dict[str, Any]],
    ui_copy: dict[str, str],
) -> dict[str, str]:
    """Build flat data-i18n key -> string dictionary for instant in-page switching."""
    ui = {**DEFAULT_UI_STRINGS_EN, **ui_copy}
    flat: dict[str, str] = {
        "ui.lang_label": ui["lesson.lang.label"],
        "ui.objectives_heading": ui["lesson.objectives.heading"],
        "ui.example_heading": ui["lesson.example.heading"],
        "ui.answer_label": ui["lesson.answer.label"],
        "ui.check_submit": ui["lesson.check.submit"],
        "ui.check_why": ui["lesson.check.why"],
        "ui.check_pick_first": ui["lesson.check.pick_first"],
        "ui.check_correct": ui["lesson.check.correct"],
        "ui.check_wrong": ui["lesson.check.wrong"],
        "ui.check_your_answer": ui["lesson.check.your_answer"],
        "ui.glossary_heading": ui["lesson.glossary.heading"],
        "ui.sources_footer": ui["lesson.sources.footer"],
        "ui.untranslated_block_notice": ui["lesson.untranslated.block_notice"],
        "ui.untranslated_page_notice": ui["lesson.untranslated.page_notice"],
        "ui.report_issue": ui["lesson.report.translation_issue"],
        "ui.trans_badge": ui["lesson.trans.badge"],
        "b-00-meta.title": str(lesson.get("title", "")),
    }
    for i, obj in enumerate(lesson.get("objectives", [])):
        flat[f"b-00-meta.objectives.{i}"] = str(obj)
    for i, g in enumerate(lesson.get("glossary", [])):
        flat[f"b-00-meta.glossary.{i}.term"] = str(g.get("term", ""))
        flat[f"b-00-meta.glossary.{i}.definition"] = str(g.get("definition", ""))

    for b in blocks:
        bid = b["id"]
        btype = b["type"]
        spec = b.get("spec", {})
        if btype == "text":
            for i, p in enumerate(spec.get("paragraphs", [])):
                flat[f"{bid}.paragraphs.{i}"] = str(p)
        elif btype == "worked_example":
            flat[f"{bid}.problem"] = str(spec.get("problem", ""))
            for i, s in enumerate(spec.get("steps", [])):
                flat[f"{bid}.steps.{i}.title"] = str(s.get("title", ""))
                flat[f"{bid}.steps.{i}.detail"] = str(s.get("detail", ""))
            flat[f"{bid}.answer"] = str(spec.get("answer", ""))
        elif btype == "check":
            flat[f"{bid}.question"] = str(spec.get("question", ""))
            for i, opt in enumerate(spec.get("options", [])):
                flat[f"{bid}.options.{i}"] = str(opt)
            flat[f"{bid}.explanation"] = str(spec.get("explanation", ""))
        elif btype == "reveal":
            flat[f"{bid}.title"] = str(spec.get("title", ""))
            for i, s in enumerate(spec.get("steps", [])):
                flat[f"{bid}.steps.{i}.title"] = str(s.get("title", ""))
                flat[f"{bid}.steps.{i}.detail"] = str(s.get("detail", ""))
        elif btype == "diagram":
            flat[f"{bid}.caption"] = str(spec.get("caption", ""))
            svg_raw = str(spec.get("svg", ""))
            found_tagged = False
            try:
                root = ET.fromstring(svg_raw)
                for elem in root.iter():
                    i18n_key = elem.attrib.get("data-i18n")
                    if i18n_key and (elem.text or "").strip():
                        flat[i18n_key] = (elem.text or "").strip()
                        found_tagged = True
            except ET.ParseError:
                pass
            if not found_tagged:
                diag_payload = extract_diagram_payload(b)
                for item in diag_payload.get("svg_texts", []):
                    flat[f"{bid}.svg_texts.{item['id']}"] = str(item["source"])
        elif btype == "simulation":
            flat[f"{bid}.title"] = str(spec.get("title", ""))
            flat[f"{bid}.description"] = str(spec.get("description", ""))
            for c in spec.get("controls", []):
                cid = c.get("id")
                flat[f"{bid}.controls.{cid}.label"] = str(c.get("label", cid))
    return flat


def _render_locale_hub_html(
    locale: str,
    locales_available: list[str],
    ui_copy: dict[str, str],
) -> str:
    """Render top-level localized course hub page (site/<locale>/index.html)."""
    script_code = LOCALE_METADATA.get(locale, {}).get("script", "Latn")
    lang_bar = _build_lang_bar(locale, locales_available, ui_copy, is_subroute=True)
    hub_titles = {
        "en": ("Zivon - Field Notes", "Courses"),
        "hi": ("Zivon - फ़ील्ड नोट्स", "पाठ्यक्रम (Courses)"),
        "hi-Latn": ("Zivon - Field Notes", "Courses (Paathyakram)"),
    }
    kicker, heading = hub_titles.get(locale, ("Zivon - Field Notes", "Courses"))
    return f"""<!doctype html>
<html lang="{_esc(locale)}" data-script="{_esc(script_code)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{_esc(heading)} - Zivon</title>
<link rel="stylesheet" href="../assets/zivon.css">
</head>
<body>
{lang_bar}
<main class="zn-page zn-home">
  <header class="zn-header">
    <p class="zn-kicker">{_esc(kicker)}</p>
    <h1 class="zn-title">{_esc(heading)}</h1>
  </header>
  <ul id="zn-courses" class="zn-courses" aria-label="Available courses"></ul>
  <p id="zn-empty" class="zn-empty" hidden>No topics published yet.</p>
  <footer class="zn-footer">
    <p class="zn-sources">{_esc(ui_copy.get("lesson.sources.footer", DEFAULT_UI_STRINGS_EN["lesson.sources.footer"]))}</p>
  </footer>
</main>
<script src="../courses.js"></script>
<script src="../assets/zivon.js"></script>
</body>
</html>
"""


def render_localized(
    cfg: Config,
    run_ctx: RunContext,
    chapter_query: str,
    source_pack: dict[str, Any],
    en_lesson: dict[str, Any],
    en_blocks: dict[str, Any],
    render_out: dict[str, Any],
    translate_out: dict[str, Any],
    transcheck_out: dict[str, Any],
) -> dict[str, Any]:
    """Stage 10d-transrender: render localized HTML routes, i18n JSON/JS bundles, and manifest metadata."""
    del chapter_query
    topic_dir = Path(render_out["topic_dir"])
    site_dir = Path(render_out["site_dir"])
    display_title = chapter_display_title(
        ident.repair_chapter_title(
            source_pack["chapter"]["title"],
            matched_line=source_pack["chapter"].get("matched_line"),
            query=source_pack.get("query"),
        )
        or source_pack["chapter"]["title"]
    )
    slug = slugify(display_title)
    class_level = source_pack["chapter"]["class"]
    course_id = f"class-{class_level}-physics"
    chapter_key = ident.chapter_id(class_level, slug)

    page_js_path = topic_dir / "page.js"
    page_css_path = topic_dir / "page.css"
    page_js = page_js_path.read_text(encoding="utf-8") if page_js_path.exists() else ""
    page_css = (
        page_css_path.read_text(encoding="utf-8") if page_css_path.exists() else ""
    )
    has_page_js = bool(page_js.strip())
    has_page_css = bool(page_css.strip())

    all_ui_strings = load_ui_strings(cfg)
    en_ui = _ui_for_locale(all_ui_strings, "en")
    en_sim_strings = extract_sim_strings_from_js(page_js)
    # Section ownership is resolved ONCE, from the English draft, and then
    # applied to every locale: a translated page must have exactly the same
    # section structure as the page it translates (only the words differ).
    en_raw_blocks = list(en_blocks.get("blocks", []))
    ownership = section_map.resolve_sections(en_lesson, en_raw_blocks)
    en_blocks_list = section_map.apply_metadata(en_raw_blocks, ownership, chapter_key)
    en_blocks_by_id = {b["id"]: b for b in en_blocks_list}

    i18n_dir = topic_dir / "i18n"
    i18n_dir.mkdir(parents=True, exist_ok=True)

    locales_map = translate_out.get("locales", {})
    locales_available = ["en"] + [loc for loc in locales_map if loc != "en"]
    glossary_ver = str(load_glossary(cfg).get("glossary_version", "1.0.0"))

    # 1. Build and write English i18n/en.json
    en_strings = _flatten_strings_map(en_lesson, en_blocks_list, en_ui)
    en_bundle = {
        "locale": "en",
        "script": "Latn",
        "status": "verified",
        "glossary_version": glossary_ver,
        "fallback_blocks": [],
        "strings": en_strings,
        "ui_strings": en_ui,
        "sim_strings": en_sim_strings,
        "lesson": en_lesson,
        "blocks": en_blocks_list,
    }
    en_json_path = i18n_dir / "en.json"
    en_json_text = json.dumps(en_bundle, indent=2, ensure_ascii=False)
    en_json_path.write_text(en_json_text, encoding="utf-8")

    js_i18n_payload: dict[str, Any] = {
        "en": {
            "locale": "en",
            "script": "Latn",
            "status": "verified",
            "fallback_blocks": [],
            "strings": en_strings,
            "ui_strings": en_ui,
            "sim_strings": en_sim_strings,
        }
    }
    js_sim_i18n: dict[str, Any] = {"en": en_sim_strings}

    titles_by_locale: dict[str, str] = {"en": str(en_lesson.get("title", ""))}
    translation_status: dict[str, Any] = {}
    i18n_hashes: dict[str, str] = {
        "en": hashlib.sha256(en_json_text.encode("utf-8")).hexdigest()
    }
    locales_out: dict[str, Any] = {}

    # 2. Build per-locale JSON bundles and localized <locale>/index.html pages
    for locale, loc_data in locales_map.items():
        loc_ui = _ui_for_locale(all_ui_strings, locale)
        loc_lesson = loc_data.get("meta") or loc_data.get("lesson") or en_lesson
        loc_blocks_raw = loc_data.get("blocks", {}).get("blocks", en_blocks_list)
        loc_sim_strings = loc_data.get("sim_strings") or en_sim_strings
        script_code = LOCALE_METADATA.get(locale, {}).get("script", "Latn")

        fallback_set = set(loc_data.get("fallback_blocks", []))
        tc_loc = (transcheck_out or {}).get("locales", {}).get(locale, {})
        for bi in tc_loc.get("model_issues", []) + tc_loc.get("rule_issues", []):
            if bi.get("severity") in ("fatal", "major"):
                bid = bi.get("block_id")
                if bid and bid != "b-00-meta":
                    fallback_set.add(bid)
        fallback_blocks = sorted(fallback_set)

        effective_blocks: list[dict[str, Any]] = []
        for b in loc_blocks_raw:
            if b["id"] in fallback_set and b["id"] in en_blocks_by_id:
                effective_blocks.append(en_blocks_by_id[b["id"]])
            else:
                effective_blocks.append(b)
        effective_blocks = section_map.apply_metadata(
            effective_blocks, ownership, chapter_key
        )

        loc_strings = _flatten_strings_map(loc_lesson, effective_blocks, loc_ui)
        loc_status = "partial" if fallback_blocks else "verified"
        loc_bundle = {
            "locale": locale,
            "script": script_code,
            "status": loc_status,
            "glossary_version": glossary_ver,
            "fallback_blocks": fallback_blocks,
            "strings": loc_strings,
            "ui_strings": loc_ui,
            "sim_strings": loc_sim_strings,
            "lesson": loc_lesson,
            "blocks": effective_blocks,
        }
        loc_json_path = i18n_dir / f"{locale}.json"
        loc_json_text = json.dumps(loc_bundle, indent=2, ensure_ascii=False)
        loc_json_path.write_text(loc_json_text, encoding="utf-8")
        i18n_hashes[locale] = hashlib.sha256(loc_json_text.encode("utf-8")).hexdigest()

        js_i18n_payload[locale] = {
            "locale": locale,
            "script": script_code,
            "status": loc_status,
            "fallback_blocks": fallback_blocks,
            "strings": loc_strings,
            "ui_strings": loc_ui,
            "sim_strings": loc_sim_strings,
        }
        js_sim_i18n[locale] = loc_sim_strings

        titles_by_locale[locale] = str(
            loc_lesson.get("title", en_lesson.get("title", ""))
        )
        translation_status[locale] = {
            "status": loc_status,
            "fallback_blocks": fallback_blocks,
            "glossary_version": glossary_ver,
        }

        loc_body = _render_body(
            loc_lesson,
            effective_blocks,
            chapter_key,
            with_i18n_attrs=True,
            ui_copy=loc_ui,
            fallback_block_ids=frozenset(fallback_set),
        )
        loc_html = _page_html(
            cfg,
            loc_lesson,
            loc_body,
            slug,
            course_id,
            display_title=display_title,
            has_page_js=has_page_js,
            has_page_css=has_page_css,
            locale=locale,
            locales_available=locales_available,
            ui_copy=loc_ui,
            has_i18n_js=True,
            with_i18n_attrs=True,
        )
        lint_hits = lint_generated(page_js, page_css, loc_html)
        if lint_hits:
            raise LintError(
                TRANSRENDER_STAGE_ID,
                f"localized page ({locale}) violates hard lints:\n"
                + "\n".join(lint_hits),
                artifacts_dir=str(run_ctx.stage_dir(TRANSRENDER_STAGE_ID)),
            )
        loc_hook_problems = hook_issues(loc_html)
        if loc_hook_problems:
            raise LintError(
                TRANSRENDER_STAGE_ID,
                f"localized page ({locale}) violates the hook contract:\n"
                + "\n".join(loc_hook_problems),
                artifacts_dir=str(run_ctx.stage_dir(TRANSRENDER_STAGE_ID)),
            )

        loc_dir = topic_dir / locale
        loc_dir.mkdir(parents=True, exist_ok=True)
        (loc_dir / "index.html").write_text(loc_html, encoding="utf-8")

        hub_dir = site_dir / locale
        hub_dir.mkdir(parents=True, exist_ok=True)
        hub_html = _render_locale_hub_html(locale, locales_available, loc_ui)
        hub_hits = lint_html(f"{locale}/index.html", hub_html)
        if hub_hits:
            raise LintError(
                TRANSRENDER_STAGE_ID,
                f"localized hub ({locale}) violates hard lints:\n"
                + "\n".join(hub_hits),
                artifacts_dir=str(run_ctx.stage_dir(TRANSRENDER_STAGE_ID)),
            )
        (hub_dir / "index.html").write_text(hub_html, encoding="utf-8")

        locales_out[locale] = {
            "topic_dir": str(loc_dir),
            "index_html": str(loc_dir / "index.html"),
            "i18n_json": str(loc_json_path),
            "lint_hits": lint_hits,
            "fallback_blocks": fallback_blocks,
            "status": loc_status,
        }

    # 3. Emit topic_dir / i18n.js (strictly self-contained, zero network URLs)
    i18n_js_body = (
        "/* Generated by the Zivon content factory (10d-transrender) - do not edit by hand. */\n"
        f"window.ZIVON_I18N = {json.dumps(js_i18n_payload, indent=2, ensure_ascii=False)};\n"
        f"window.ZIVON_SIM_I18N = {json.dumps(js_sim_i18n, indent=2, ensure_ascii=False)};\n"
    )
    i18n_js_body = i18n_js_body.replace("</script", "<\\/script").replace(
        "<!--", "<\\!--"
    )
    i18n_js_hits = lint_js("i18n.js", i18n_js_body)
    if i18n_js_hits:
        raise LintError(
            TRANSRENDER_STAGE_ID,
            "i18n.js violates hard lints:\n" + "\n".join(i18n_js_hits),
            artifacts_dir=str(run_ctx.stage_dir(TRANSRENDER_STAGE_ID)),
        )
    (topic_dir / "i18n.js").write_text(i18n_js_body, encoding="utf-8")

    # 4. Upgrade canonical English topic_dir / index.html with data-i18n attributes and i18n.js
    en_body_i18n = _render_body(
        en_lesson, en_blocks_list, chapter_key, with_i18n_attrs=True, ui_copy=en_ui
    )
    en_html_i18n = _page_html(
        cfg,
        en_lesson,
        en_body_i18n,
        slug,
        course_id,
        display_title=display_title,
        has_page_js=has_page_js,
        has_page_css=has_page_css,
        locale="en",
        locales_available=locales_available,
        ui_copy=en_ui,
        has_i18n_js=True,
        with_i18n_attrs=True,
    )
    en_hits = lint_generated(page_js, page_css, en_html_i18n)
    if en_hits:
        raise LintError(
            TRANSRENDER_STAGE_ID,
            "localized English index.html violates hard lints:\n" + "\n".join(en_hits),
            artifacts_dir=str(run_ctx.stage_dir(TRANSRENDER_STAGE_ID)),
        )
    (topic_dir / "index.html").write_text(en_html_i18n, encoding="utf-8")

    # 5. Update manifest.json with CP-TRN-004 localization metadata and regenerate site courses.js
    manifest_path = topic_dir / "manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists()
        else dict(render_out.get("manifest", {}))
    )
    manifest["default_locale"] = "en"
    manifest["locales_available"] = locales_available
    manifest["titles_by_locale"] = titles_by_locale
    manifest["translation_status"] = translation_status
    manifest["i18n_hashes"] = i18n_hashes
    # Manifest v2 language coverage follows the bundles that now exist: the
    # artifact, not the product promise, decides what `missing` says.
    manifest["languages"] = _lesson_languages(locales_available)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    render_out["manifest"] = manifest
    _write_courses_js(site_dir)

    stage_out = {
        "locales": locales_out,
        "locales_available": locales_available,
        "titles_by_locale": titles_by_locale,
        "translation_status": translation_status,
        "i18n_js": str(topic_dir / "i18n.js"),
        "manifest_updated": True,
    }
    stage_dir = run_ctx.stage_dir(TRANSRENDER_STAGE_ID)
    (stage_dir / "output.json").write_text(
        json.dumps(stage_out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log_event(
        "factory.transrender.complete",
        {"locales": locales_available, "topic_slug": slug},
        severity=Severity.INFO,
        run_id=run_ctx.run_id,
        stage=TRANSRENDER_STAGE_ID,
    )
    return stage_out
