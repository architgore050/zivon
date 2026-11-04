"""Stage 11-link: publish the reviewed page into frontend/ and regenerate the
course index.

This is the ONLY stage that writes into frontend/. It copies the topic
directory from the staging site, regenerates courses.js from all manifests,
and smoke-tests that every course link resolves to a real file.
"""

from __future__ import annotations

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
        "courses": entries,
        "course_count": len(entries),
    }
