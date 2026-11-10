"""Rendered screenshots for the visual reviewer (09-review).

The design reviewer used to judge the rendered page from its files alone.
This module lets the model SEE the page: it renders the staged topic page
in headless Chromium at the doctrine's three frames (~360 / ~768 / ~1280 px
- phones, tablets, laptops; same geometry family as the zoom in/out a human
reader does when resizing), and captures the regions that carry visual
judgment - the page header's first screen plus every diagram and
simulation element. The PNGs live in the run dir ONLY: they are review
evidence, never shipped (they never enter topic_dir or the staging site).

Failure posture: capture is best-effort. If playwright is unavailable or a
render fails, capture returns [] and the reviewer proceeds fully text-only
(as it always did). Screenshots are an input-fidelity upgrade, not a gate.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

# Doctrine §10.2 frames. Height: tall enough for a couple of rows of content;
# a full-height capture of a 20k-px lesson is useless to a model (context and
# image-token cost), so capture is per-visual, not full-page.
VIEWPORTS = (360, 768, 1280)
VIEWPORT_HEIGHT = 900

# Content-bearing selectors, in page order. The header strip comes first so
# the reviewer sees title/objectives/lang-bar rendered, not just code.
# Body prose is deliberately NOT captured (2026-11-10 founder correction: body
# text was fine; the jumbling was inside the visual elements - labels within
# diagrams, sims and graphs - so imaging flowing prose only burned image
# tokens for nothing).
_REGIONS = (".zn-header", "figure.zn-diagram", "section.zn-sim", "section.zn-check")


def capture(topic_dir: Path, out_dir: Path) -> list[dict[str, Any]]:
    """Screenshot every diagram/sim (and the page header) at each doctrine
    frame. Returns a manifest: [{path, width, label}] - empty on any failure
    (playwright missing, render error) so callers simply proceed text-only."""
    index_html = topic_dir / "index.html"
    if not index_html.exists():
        return []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return []

    shots: list[dict[str, Any]] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                for width in VIEWPORTS:
                    page = browser.new_page(
                        viewport={"width": width, "height": VIEWPORT_HEIGHT}
                    )
                    try:
                        page.goto(index_html.as_uri())
                        page.wait_for_timeout(400)
                        for sel in _REGIONS:
                            for i, el in enumerate(page.query_selector_all(sel)):
                                label = (
                                    sel.replace(".", "").replace("zn-", "")
                                    + f"#{i + 1}"
                                )
                                name = f"{label.replace('#', '-')}-w{width}.png"
                                dest = out_dir / name
                                el.screenshot(path=str(dest))
                                shots.append(
                                    {
                                        "path": str(dest),
                                        "width": width,
                                        "label": f"{label} @ {width}px",
                                        "bytes": dest.stat().st_size,
                                    }
                                )
                    finally:
                        page.close()
            finally:
                browser.close()
    except Exception:  # noqa: BLE001 - capture is best-effort by contract; review proceeds text-only
        return []
    (out_dir / "manifest.json").write_text(
        json.dumps({"viewport_widths": list(VIEWPORTS), "shots": shots}, indent=2),
        encoding="utf-8",
    )
    return shots


def vision_parts(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """OpenAI-format vision parts (data URIs) for the review call. Each part
    carries its label as the preceding text so the model knows what it is."""
    parts: list[dict[str, Any]] = []
    for shot in shots:
        data_uri = (
            "data:image/png;base64,"
            + base64.b64encode(Path(shot["path"]).read_bytes()).decode()
        )
        parts.append({"type": "text", "text": f"[{shot['label']}]"})
        parts.append({"type": "image_url", "image_url": {"url": data_uri}})
    return parts
