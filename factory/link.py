"""Stage 11-link: publish the reviewed page into frontend/ and regenerate the
course index.

This is the ONLY stage that writes into frontend/. It copies the topic
directory from the staging site, regenerates courses.js from all manifests,
and smoke-tests that every course link resolves to a real file.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .artifacts import RunContext
from .config import Config
from .errors import StageError
from .render import write_courses_js

STAGE_ID = "11-link"


def run(cfg: Config, run_ctx: RunContext, render_out: dict[str, Any]) -> dict[str, Any]:
    frontend = cfg.repo_path(cfg.paths["frontend"])
    site = Path(render_out["site_dir"])
    topic_src = Path(render_out["topic_dir"])
    rel = topic_src.relative_to(site / "courses")
    topic_dst = frontend / "courses" / rel

    topic_dst.parent.mkdir(parents=True, exist_ok=True)
    if topic_dst.exists():
        shutil.rmtree(topic_dst)
    shutil.copytree(topic_src, topic_dst)

    # Stale-duplicate pruning (2026-11-10 founder bug report: two "Laws of
    # Motion" pages, same content). Before the chapter-derived slug, each run
    # named its directory after the MODEL's lesson headline, so a re-run
    # published a new directory and left the old one listed next to it. A
    # chapter owns exactly ONE topic directory: any sibling manifest for the
    # same course + chapter title that is not this topic is a superseded copy.
    pruned: list[str] = []
    ours = json.loads((topic_dst / "manifest.json").read_text(encoding="utf-8"))
    for mf in sorted(topic_dst.parent.glob("*/manifest.json")):
        if mf.parent == topic_dst:
            continue
        try:
            other = json.loads(mf.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if other.get("course_id") == ours.get("course_id") and other.get(
            "chapter", {}
        ).get("title") == ours.get("chapter", {}).get("title"):
            shutil.rmtree(mf.parent)
            pruned.append(mf.parent.name)

    entries = write_courses_js(frontend)

    # Smoke test: every href in courses.js must resolve inside frontend/.
    missing = []
    for e in entries:
        target = frontend / e["href"]
        if not target.exists():
            missing.append(e["href"])
    if missing:
        raise StageError(
            STAGE_ID,
            f"courses.js references missing files: {missing}",
            artifacts_dir=str(run_ctx.stage_dir(STAGE_ID)),
        )

    # Landing page must reference the shared assets that exist.
    index_html = (frontend / "index.html").read_text(encoding="utf-8")
    for ref in ("assets/zivon.css", "assets/zivon.js", "courses.js"):
        if ref not in index_html:
            raise StageError(
                STAGE_ID,
                f"frontend/index.html does not reference {ref}",
                artifacts_dir=str(run_ctx.stage_dir(STAGE_ID)),
            )
        if not (frontend / ref).exists():
            raise StageError(
                STAGE_ID,
                f"frontend/{ref} does not exist",
                artifacts_dir=str(run_ctx.stage_dir(STAGE_ID)),
            )

    return {
        "published_to": str(topic_dst),
        "pruned_stale_topics": pruned,
        "courses": entries,
        "course_count": len(entries),
    }
