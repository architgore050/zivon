"""Stage 06-render: assemble the topic page and the staging site.

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

import html as html_mod
import json
import shutil
import time
from pathlib import Path
from typing import Any

from .artifacts import RunContext, slugify
from .config import Config
from .errors import LintError
from .lint import lint_generated

STAGE_ID = "06-render"

CSP = (
    "default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'none'; base-uri 'none'"
)


def run(
    cfg: Config,
    run_ctx: RunContext,
    chapter_query: str,
    source_pack: dict[str, Any],
    lesson: dict[str, Any],
    blocks: dict[str, Any],
    interactive: dict[str, Any],
) -> dict[str, Any]:
    slug = slugify(lesson["title"])
    course_id = f"class-{cfg.learner['class_level']}-physics"

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

    body = "\n".join(_render_block(b) for b in blocks["blocks"])
    html_text = _page_html(
        cfg,
        lesson,
        body,
        slug,
        course_id,
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

    manifest = {
        "course_id": course_id,
        "class": cfg.learner["class_level"],
        "topic_slug": slug,
        "title": lesson["title"],
        "chapter": {
            "query": chapter_query,
            "title": source_pack["chapter"]["title"],
            "book": source_pack["chapter"]["book_title"],
            "pages": source_pack["chapter"]["pages"],
        },
        "sources": _sources_list(source_pack),
        "run_id": run_ctx.run_id,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "block_counts": _block_counts(blocks),
    }
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
    }


# ------------------------------------------------------------------ blocks
def _esc(text: Any) -> str:
    return html_mod.escape(str(text), quote=True)


def _render_block(b: dict[str, Any]) -> str:
    t, spec = b["type"], b["spec"]
    if t == "text":
        paras = "\n".join(f"    <p>{_esc(p)}</p>" for p in spec.get("paragraphs", []))
        return f'  <section class="zn-text">\n{paras}\n  </section>'
    if t == "worked_example":
        steps = "\n".join(
            f"      <li><strong>{_esc(s.get('title', ''))}</strong> {_esc(s.get('detail', ''))}</li>"
            for s in spec.get("steps", [])
        )
        return (
            f'  <section class="zn-example" id="{_esc(b["id"])}">\n'
            f'    <h3>Worked example</h3>\n    <p class="zn-example-problem">{_esc(spec.get("problem", ""))}</p>\n'
            f"    <ol>\n{steps}\n    </ol>\n"
            f'    <p class="zn-answer"><span class="zn-answer-label">Answer</span> {_esc(spec.get("answer", ""))}</p>\n'
            "  </section>"
        )
    if t == "check":
        return _render_check(b)
    if t == "reveal":
        steps = "\n".join(
            f'      <details class="zn-reveal-step"><summary>{_esc(s.get("title", ""))}</summary>'
            f"<p>{_esc(s.get('detail', ''))}</p></details>"
            for s in spec.get("steps", [])
        )
        return (
            f'  <section class="zn-reveal" id="{_esc(b["id"])}">\n'
            f"    <h3>{_esc(spec.get('title', ''))}</h3>\n{steps}\n  </section>"
        )
    if t == "diagram":
        return (
            f'  <figure class="zn-diagram" id="{_esc(b["id"])}">\n'
            f'    <div class="zn-diagram-svg">{spec.get("svg", "")!s}</div>\n'
            f"    <figcaption>{_esc(spec.get('caption', ''))}</figcaption>\n  </figure>"
        )
    if t == "simulation":
        return _render_simulation(b)
    raise ValueError(f"unknown block type {t!r}")  # schema prevents this


def _render_check(b: dict[str, Any]) -> str:
    spec = b["spec"]
    qid = _esc(b["id"])
    q = _esc(spec.get("question", ""))
    fmt = spec.get("format")
    if fmt == "mcq":
        inputs = "\n".join(
            f'      <label class="zn-opt"><input type="radio" name="check-{qid}" value="{i}"> '
            f"<span>{_esc(opt)}</span></label>"
            for i, opt in enumerate(spec.get("options", []))
        )
        data = f'data-answer-index="{int(spec.get("answer_index", -1))}"'
    else:
        inputs = (
            f'      <label class="zn-opt zn-opt-numeric">Your answer: '
            f'<input type="text" inputmode="decimal" class="zn-numeric-input" name="check-{qid}-input"></label>'
        )
        data = f'data-answer="{_esc(spec.get("answer", ""))}"'
    explanation = _esc(spec.get("explanation", ""))
    return (
        f'  <fieldset class="zn-check" id="{qid}" data-format="{fmt}" {data}>\n'
        f"    <legend>{q}</legend>\n{inputs}\n"
        f'    <button type="button" class="zn-check-btn">Check</button>\n'
        f'    <p class="zn-check-feedback" aria-live="polite"></p>\n'
        f'    <details class="zn-check-why"><summary>Why?</summary><p>{explanation}</p></details>\n'
        "  </fieldset>"
    )


def _render_simulation(b: dict[str, Any]) -> str:
    spec = b["spec"]
    sid = _esc(b["id"])
    controls = "\n".join(
        f'      <label class="zn-sim-control"><span>{_esc(c.get("label", c.get("id")))}</span>'
        f'<input type="range" data-control="{_esc(c.get("id"))}" min="{_esc(c.get("min", 0))}" '
        f'max="{_esc(c.get("max", 100))}" step="{_esc(c.get("step", 1))}" value="{_esc(c.get("initial", 0))}">'
        f"<output>{_esc(c.get('initial', 0))}</output></label>"
        for c in spec.get("controls", [])
    )
    return (
        f'  <section class="zn-sim zn-sim-{sid}" id="{sid}" data-sim-id="{sid}" '
        f'aria-label="{_esc(spec.get("title", ""))}">\n'
        f"    <h3>{_esc(spec.get('title', ''))}</h3>\n"
        f'    <div class="zn-sim-controls">\n{controls}\n    </div>\n'
        f'    <div class="zn-sim-canvas-wrap"><canvas class="zn-sim-canvas" width="480" '
        f'height="320" tabindex="0" aria-label="{_esc(spec.get("title", ""))} drawing"></canvas></div>\n'
        f'    <p class="zn-sim-desc">{_esc(spec.get("description", ""))}</p>\n'
        "  </section>"
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
) -> str:
    objectives = "\n".join(f"      <li>{_esc(o)}</li>" for o in lesson["objectives"])
    glossary = "\n".join(
        f"      <dt>{_esc(g['term'])}</dt><dd>{_esc(g['definition'])}</dd>"
        for g in lesson["glossary"]
    )
    page_js_tag = '<script src="page.js"></script>' if has_page_js else ""
    page_css_tag = '<link rel="stylesheet" href="page.css">' if has_page_css else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta http-equiv="Content-Security-Policy" content="{CSP}">
<title>{_esc(lesson["title"])} - Zivon</title>
<link rel="stylesheet" href="../../../assets/zivon.css">
{page_css_tag}
</head>
<body>
<main class="zn-page">
  <header class="zn-header">
    <p class="zn-kicker">{_esc(course_id)}</p>
    <h1 class="zn-title">{_esc(lesson["title"])}</h1>
    <p class="zn-objectives-label">After this lesson you can:</p>
    <ul class="zn-objectives">
{objectives}
    </ul>
  </header>
{body}
  <section class="zn-glossary">
    <h2>Glossary</h2>
    <dl>
{glossary}
    </dl>
  </section>
  <footer class="zn-footer">
    <p class="zn-sources">Generated by the Zivon content factory. Sources are listed in the course index.</p>
  </footer>
</main>
<script src="../../../assets/zivon.js"></script>
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


def write_courses_js(frontend_dir: Path) -> list[dict[str, Any]]:
    """Regenerate courses.js from every manifest under frontend/courses/.
    Exposed here so stage 11-link reuses exactly this logic."""
    courses_dir = frontend_dir / "courses"
    entries: list[dict[str, Any]] = []
    if courses_dir.exists():
        for mf in sorted(courses_dir.glob("*/**/manifest.json")):
            data = json.loads(mf.read_text(encoding="utf-8"))
            # rel already starts with "courses/" (manifests only exist under courses/)
            rel = mf.parent.relative_to(frontend_dir).as_posix()
            entries.append(
                {
                    "href": f"{rel}/index.html",
                    "course_id": data["course_id"],
                    "class": data["class"],
                    "title": data["title"],
                    "chapter": data["chapter"]["title"],
                    "generated_at": data["generated_at"],
                }
            )
    entries.sort(key=lambda e: (e["class"], e["title"]))
    payload = json.dumps(entries, indent=2, ensure_ascii=False)
    (frontend_dir / "courses.js").write_text(
        "/* Generated by the Zivon content factory - do not edit by hand.\n"
        "   Regenerated on every successful pipeline run (stage 11-link). */\n"
        f"window.ZIVON_COURSES = {payload};\n",
        encoding="utf-8",
    )
    return entries


def _write_courses_js(site_dir: Path) -> None:
    write_courses_js(site_dir)
