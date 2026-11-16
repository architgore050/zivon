"""Glossary coverage gate for `EV-E2E-002` (0 model calls).

Two contracts:

1. Every canonical glossary term is complete in every locale the launch
   promises (`hi`, `hi-Latn` per FEATURE-MAP #3). A missing native term means
   a translated page will silently fall back to English mid-sentence.
2. Every glossary term a golden page actually uses has a complete entry in
   every locale that page promises (its manifest's `locales_available`).

P2 owns authoring entries; this checker only measures and blocks a publish
whose promise cannot be kept.
"""

from __future__ import annotations

import json
from typing import Any

from factory.checks import rule_glossary_coverage

from ..config import EvalConfig
from ..models import EvalCard, IssueRecord

CHECK_ID = "DET-E2E02-GLOSSARY-COVERAGE"
LAUNCH_ID = "DET-E2E02-GLOSSARY-LAUNCH"

LAUNCH_LOCALES = ("hi", "hi-Latn")


def _load_glossary(cfg: EvalConfig) -> dict[str, Any]:
    path = cfg.repo_root / "sources" / "glossary" / "physics_glossary.json"
    if not path.is_file():
        return {"terms": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _topic_content(
    cfg: EvalConfig, topic_rel: str
) -> tuple[dict, list[dict], list[str]]:
    """(lesson, blocks, promised non-English locales) for one golden topic.

    Only a **published** topic is graded: a golden whose `artifact_ref.json`
    has no `published_dir` (e.g. GT-04, contract-frozen) has no page promise to
    keep, so it is skipped rather than substituted with an unrelated fixture.
    """
    tdir = cfg.repo_root / topic_rel
    ref_path = tdir / "artifact_ref.json"
    promised: list[str] = []
    if not ref_path.is_file():
        return {}, [], promised
    ref = json.loads(ref_path.read_text(encoding="utf-8"))
    published = ref.get("published_dir")
    if not published:
        return {}, [], promised
    manifest_path = cfg.repo_root / published / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        promised = [
            loc
            for loc in manifest.get("locales_available", [])
            if loc not in ("en", "en-IN")
        ]
    bundle = cfg.repo_root / published / "i18n" / "en.json"
    if bundle.is_file():
        payload = json.loads(bundle.read_text(encoding="utf-8"))
        return payload["lesson"], list(payload["blocks"]), promised
    return {}, [], promised


def check_launch_locale_coverage(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-E2E02-GLOSSARY-LAUNCH`: every canonical term has hi + hi-Latn."""
    issues: list[IssueRecord] = []
    glossary = _load_glossary(cfg)
    metrics = context.setdefault("metrics", {})
    terms = glossary.get("terms", [])
    complete = 0
    for entry in terms:
        english = str(entry.get("english_term") or "")
        locales = entry.get("locales") or {}
        missing = []
        for locale in LAUNCH_LOCALES:
            loc = locales.get(locale) or {}
            if (
                not str(loc.get("native_term") or "").strip()
                or not str(loc.get("first_mention_gloss") or "").strip()
            ):
                missing.append(locale)
        if missing:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id=LAUNCH_ID,
                    category="glossary",
                    message=f"glossary term {english!r} is missing a complete "
                    f"{'/'.join(missing)} entry (launch locales: {LAUNCH_LOCALES})",
                )
            )
        else:
            complete += 1
    metrics["glossary_terms_total"] = len(terms)
    metrics["glossary_terms_launch_complete"] = complete
    if not terms:
        context.setdefault("skipped_checks", {})[LAUNCH_ID] = (
            "sources/glossary/physics_glossary.json has no terms"
        )
    return issues


def check_page_glossary_coverage(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-E2E02-GLOSSARY-COVERAGE`: used terms exist in every promised locale."""
    issues: list[IssueRecord] = []
    glossary = _load_glossary(cfg)
    metrics = context.setdefault("metrics", {})
    pages = 0
    unpublished: list[str] = []
    promised_locales: set[str] = set()
    for topic_rel in card.golden_inputs.get("topics", []):
        lesson, blocks, promised = _topic_content(cfg, topic_rel)
        if not lesson:
            unpublished.append(topic_rel)
            continue
        pages += 1
        promised_locales.update(promised)
        for finding in rule_glossary_coverage(lesson, blocks, glossary, promised):
            issues.append(
                IssueRecord(
                    severity=str(finding.get("severity", "fatal")),
                    check_id=CHECK_ID,
                    category="glossary",
                    message=f"{topic_rel}: {finding.get('message', '')}",
                )
            )
    metrics["glossary_pages_checked"] = pages
    metrics["glossary_topics_without_published_page"] = unpublished
    metrics["glossary_promised_locales"] = sorted(promised_locales)
    if pages == 0:
        context.setdefault("skipped_checks", {})[CHECK_ID] = (
            "no golden topic has a published English bundle to grade"
        )
    return issues
