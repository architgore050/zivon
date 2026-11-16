"""Stage 11-link: publish the reviewed page into frontend/ and regenerate the
course catalogue.

This is the ONLY stage that writes into frontend/. It copies the topic
directory from the staging site, copies any localized course hub directories
when present, derives `catalogue.json` + `courses.js` (P5 factory/catalogue.py),
and smoke-tests that every course link and localized variant resolves to a real
file.

Republishing an existing topic must not silently drop its read-aloud story:
narration is generated AFTER this stage (12-narration) and its assets are
content-addressed, so a re-render of the same drafts re-attaches the previous
narration manifest + availability flag. If the block set changed, the stale
flag is left behind (honest unavailable) instead of claiming audio that no
longer matches.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from . import catalogue
from .artifacts import RunContext
from .config import Config
from .errors import StageError
from .render import write_courses_js
from .translate import LOCALE_METADATA

STAGE_ID = "11-link"


def _preserved_state(topic_dir: Path) -> dict[str, Any] | None:
    """Capture an existing topic's narration + locale state before replacement."""
    manifest_path = topic_dir / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    narration_manifest = topic_dir / "narration-manifest.json"
    narration: dict[str, Any] | None = None
    flag = manifest.get("narration")
    if narration_manifest.is_file():
        try:
            narration = json.loads(narration_manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            narration = None
    if not isinstance(flag, dict) or narration is None:
        flag = None
        narration = None
    locale_manifests: dict[str, dict[str, Any]] = {}
    for locale_path in topic_dir.glob("*/manifest.json"):
        locale = locale_path.parent.name
        if locale in ("en", "i18n"):
            continue
        try:
            locale_manifests[locale] = json.loads(
                locale_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            continue
    return {
        "narration_manifest": narration,
        "flag": flag,
        "block_ids": set(manifest.get("blocks") or {}),
        "narrated_ids": {
            str(block.get("block_id"))
            for block in (narration or {}).get("blocks", [])
            if isinstance(block, dict) and block.get("block_id")
        },
        "locale_manifests": locale_manifests,
    }


def _reattach_narration(topic_dir: Path, preserved: dict[str, Any] | None) -> bool:
    """Re-attach a previous narration state when it still describes this page.

    The block -> section map is the identity of the page's readable content;
    an identical block set means the content-addressed audio addresses still
    match. A changed block set means the old audio is stale - leave it behind
    and let 12-narration report the gaps.
    """
    if preserved is None or preserved["flag"] is None:
        return False
    new_manifest_path = topic_dir / "manifest.json"
    new_manifest = json.loads(new_manifest_path.read_text(encoding="utf-8"))
    new_blocks = new_manifest.get("blocks")
    new_block_ids = set(new_blocks) if isinstance(new_blocks, dict) else set()
    old_block_ids = preserved["block_ids"]
    if old_block_ids:
        # v2-era page: the block -> section map identifies the readable content.
        if new_block_ids != old_block_ids:
            return False
    elif not (preserved["narrated_ids"] - {"b-00-meta"}) <= new_block_ids:
        # pre-v2 page: only the narrated blocks are known; every one of them
        # must still exist or the audio addresses no longer describe this page.
        # b-00-meta is the header/objectives narration unit, not a rendered
        # block, so it is never in the v2 block map.
        return False
    new_manifest["narration"] = preserved["flag"]
    new_manifest_path.write_text(
        json.dumps(new_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (topic_dir / "narration-manifest.json").write_text(
        json.dumps(preserved["narration_manifest"], indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return True


def _write_locale_manifests(
    topic_dir: Path,
    topic_manifest: dict[str, Any],
    preserved: dict[str, dict[str, Any]],
) -> None:
    """Each localized route needs its own ``manifest.json`` (shell contract).

    ``zivon.js`` reads ``<locale>/manifest.json`` for localized read-aloud;
    the renderer writes the route page and the i18n bundle, so publish owns this
    small manifest. A preserved locale manifest keeps its (already generated)
    localized narration when its block ids still describe this page; otherwise
    an honest ``available: false`` flag replaces a stale claim.
    """
    block_ids = set(topic_manifest.get("blocks") or {})
    locales = [
        str(loc)
        for loc in topic_manifest.get("locales_available", [])
        if loc not in ("en", "en-IN")
    ]
    for locale in locales:
        locale_dir = topic_dir / locale
        if not (locale_dir / "index.html").is_file():
            continue
        payload = preserved.get(locale)
        if payload is not None:
            narration = payload.get("narration")
            raw_blocks = (
                narration.get("blocks") if isinstance(narration, dict) else None
            )
            blocks = raw_blocks if isinstance(raw_blocks, dict) else {}
            if not set(blocks) - {"b-00-meta"} <= block_ids:
                payload = None
        if payload is None:
            payload = {
                "course_id": topic_manifest.get("course_id"),
                "topic_slug": topic_manifest.get("topic_slug"),
                "locale": locale,
                "default_locale": "en",
                "locales_available": topic_manifest.get("locales_available"),
                "titles_by_locale": topic_manifest.get("titles_by_locale"),
                "translation_status": topic_manifest.get("translation_status"),
                "narration": {"available": False, "lang": locale, "blocks": {}},
            }
        else:
            payload["course_id"] = topic_manifest.get("course_id")
            payload["topic_slug"] = topic_manifest.get("topic_slug")
            payload["locale"] = locale
            payload["default_locale"] = "en"
            payload["locales_available"] = topic_manifest.get("locales_available")
            payload["titles_by_locale"] = topic_manifest.get("titles_by_locale")
            payload["translation_status"] = topic_manifest.get("translation_status")
        (locale_dir / "manifest.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def run(cfg: Config, run_ctx: RunContext, render_out: dict[str, Any]) -> dict[str, Any]:
    frontend = cfg.repo_path(cfg.paths["frontend"])
    site = Path(render_out["site_dir"])
    topic_src = Path(render_out["topic_dir"])
    rel = topic_src.relative_to(site / "courses")
    topic_dst = frontend / "courses" / rel

    topic_dst.parent.mkdir(parents=True, exist_ok=True)
    preserved = _preserved_state(topic_dst)
    if topic_dst.exists():
        shutil.rmtree(topic_dst)
    shutil.copytree(topic_src, topic_dst)
    narration_preserved = _reattach_narration(topic_dst, preserved)
    new_manifest = json.loads((topic_dst / "manifest.json").read_text(encoding="utf-8"))
    _write_locale_manifests(
        topic_dst,
        new_manifest,
        preserved["locale_manifests"] if preserved else {},
    )

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
        same_chapter = other.get("course_id") == ours.get("course_id") and other.get(
            "chapter", {}
        ).get("title") == ours.get("chapter", {}).get("title")
        same_run = bool(ours.get("run_id")) and other.get("run_id") == ours.get(
            "run_id"
        )
        if same_chapter or same_run:
            shutil.rmtree(mf.parent)
            pruned.append(mf.parent.name)

    # Copy top-level locale hub directories (e.g. site/hi/index.html -> frontend/hi/index.html)
    published_locale_hubs: list[str] = []
    for loc in LOCALE_METADATA:
        if loc == "en":
            continue
        hub_src = site / loc
        if hub_src.is_dir() and (hub_src / "index.html").is_file():
            hub_dst = frontend / loc
            if hub_dst.exists():
                shutil.rmtree(hub_dst)
            shutil.copytree(hub_src, hub_dst)
            published_locale_hubs.append(loc)

    # P1 writes the base catalogue from the same manifest scan; P5 then derives
    # the browser file from it and adds locale hrefs + the version guard.
    write_courses_js(frontend)
    report = catalogue.build(frontend)
    payload = json.loads(
        (frontend / catalogue.CATALOGUE_NAME).read_text(encoding="utf-8")
    )
    entries = payload.get("topics", [])
    if not report.ok:
        raise StageError(
            STAGE_ID,
            "catalogue publish failed: " + "; ".join(report.errors),
            artifacts_dir=str(run_ctx.stage_dir(STAGE_ID)),
        )
    if report.status != "ok":
        print(
            f"[{STAGE_ID}] catalogue integrity={report.status}: "
            + " | ".join(report.warnings)
        )

    # Smoke test: every href in courses.js (and any declared locales_available) must resolve.
    missing = []
    for e in entries:
        target = frontend / e["href"]
        if not target.exists():
            missing.append(e["href"])
        topic_folder = target.parent
        for loc in e.get("locales_available", []):
            if loc == "en":
                continue
            loc_index = topic_folder / loc / "index.html"
            loc_json = topic_folder / "i18n" / f"{loc}.json"
            if not loc_index.exists():
                missing.append(str(loc_index.relative_to(frontend)))
            if not loc_json.exists():
                missing.append(str(loc_json.relative_to(frontend)))
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
        "published_locale_hubs": published_locale_hubs,
        "courses": entries,
        "course_count": len(entries),
        "narration_preserved": narration_preserved,
        "catalogue": report.as_dict(),
    }
