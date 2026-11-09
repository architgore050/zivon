"""Stage 10c-transrepair: bounded progress-aware translation repair catcher.

Re-translates ONLY the flagged `(locale, unit_id)` items from `10b-transcheck`
with exact issue feedback, keeping all passing blocks locked and cached in
Translation Memory (`ADR-0021`, `ADR-0022`, `reviewer-rubric.md` §4).
"""

from __future__ import annotations

import copy
import json
from typing import Any

from . import translate
from .artifacts import RunContext
from .config import Config
from .llm import LLMClient

STAGE_ID = "10c-transrepair"


def group_blocking_issues_by_unit(
    transcheck_out: dict[str, Any],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Group fatal/major issues by `locale -> unit_id -> [issues]`."""
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for locale, report in transcheck_out.get("locales", {}).items():
        all_issues = report.get("model_issues", []) + report.get("rule_issues", [])
        for issue in all_issues:
            if issue.get("severity") not in ("fatal", "major"):
                continue
            uid = str(issue.get("block_id") or "b-01")
            grouped.setdefault(locale, {}).setdefault(uid, []).append(issue)
    return grouped


def run_one_round(
    cfg: Config,
    run_ctx: RunContext,
    llm: LLMClient,
    ground_truth: dict[str, Any],
    en_lesson: dict[str, Any],
    en_blocks: dict[str, Any],
    translate_out: dict[str, Any],
    transcheck_out: dict[str, Any],
    round_no: int,
) -> tuple[dict[str, Any], dict[str, set[str]], dict[str, list[dict[str, Any]]]]:
    """Re-translate ONLY flagged `(locale, unit_id)` items for one catcher round.

    Returns `(updated_translate_out, repaired_units_by_locale, round_history_by_locale)`.
    """
    del ground_truth
    grouped = group_blocking_issues_by_unit(transcheck_out)
    glossary_data = translate.load_glossary(cfg)
    glossary_version = str(glossary_data.get("glossary_version", "1.0.0"))
    prompt_version = str(cfg.translation["prompt_version"])
    max_neighbour = int(cfg.translation["max_chars_neighbour_context"]) // 2
    page_js = translate._read_page_js(run_ctx, None)
    extracted_sim_strings = translate.extract_sim_strings_from_js(page_js)
    chapter_title = str(en_lesson.get("title", "Physics"))

    en_blocks_list: list[dict[str, Any]] = list(en_blocks["blocks"])
    en_by_id: dict[str, dict[str, Any]] = {str(b["id"]): b for b in en_blocks_list}
    ordered_ids = ["b-00-meta", *[str(b["id"]) for b in en_blocks_list]]

    updated_out = copy.deepcopy(translate_out)
    repaired_units_by_locale: dict[str, set[str]] = {}
    round_history_by_locale: dict[str, list[dict[str, Any]]] = {}

    for locale, units_map in grouped.items():
        if locale not in updated_out.get("locales", {}):
            continue
        loc_state = updated_out["locales"][locale]
        tr_blocks_by_id: dict[str, dict[str, Any]] = {
            str(b["id"]): b for b in loc_state["blocks"]["blocks"]
        }
        repaired_set: set[str] = set()
        repaired_list: list[str] = []

        for unit_id in ordered_ids:
            if unit_id not in units_map:
                continue
            unit_issues = units_map[unit_id]
            unit_type = "meta" if unit_id == "b-00-meta" else str(en_by_id[unit_id]["type"])
            src_unit = en_lesson if unit_id == "b-00-meta" else en_by_id[unit_id]
            rejected_unit = (
                loc_state["meta"]
                if unit_id == "b-00-meta"
                else tr_blocks_by_id[unit_id]
            )
            rejected_payload = translate.extract_translatable_payload(
                unit_id,
                unit_type,
                rejected_unit,
                sim_strings=loc_state.get("sim_strings")
                if unit_id == "b-00-meta"
                else None,
            )

            pos = ordered_ids.index(unit_id)
            prev_excerpt = ""
            if pos > 0:
                prev_id = ordered_ids[pos - 1]
                prev_unit = (
                    loc_state["meta"]
                    if prev_id == "b-00-meta"
                    else tr_blocks_by_id[prev_id]
                )
                prev_type = "meta" if prev_id == "b-00-meta" else str(prev_unit["type"])
                prev_excerpt = translate._unit_excerpt(
                    prev_type, prev_unit, max_neighbour
                )
            next_excerpt = ""
            if pos + 1 < len(ordered_ids):
                next_id = ordered_ids[pos + 1]
                next_unit = en_by_id[next_id]
                next_excerpt = translate._unit_excerpt(
                    str(next_unit["type"]), next_unit, max_neighbour
                )

            feedback_lines = [
                f"[{i.get('severity')}/{i.get('category')}] {i.get('message')}"
                for i in unit_issues
            ]
            feedback_lines.append(
                "PREVIOUS REJECTED TRANSLATION: "
                + json.dumps(rejected_payload, ensure_ascii=False)
            )
            feedback_lines.append(
                "Fix ONLY the violations listed above while keeping valid translated "
                "sentences intact."
            )

            text_blob = json.dumps(src_unit, ensure_ascii=False)
            glossary_subset = translate.select_glossary_subset(
                glossary_data,
                locale,
                text_blob,
                chapter_glossary=en_lesson.get("glossary"),
            )

            src_payload, tr_payload, reassembled = translate.translate_single_unit(
                cfg,
                run_ctx,
                llm,
                locale,
                unit_id,
                unit_type,
                src_unit,
                glossary_subset,
                {
                    "previous_unit_translated_excerpt": prev_excerpt,
                    "next_unit_source_excerpt": next_excerpt,
                },
                chapter_title=chapter_title,
                sim_strings=extracted_sim_strings if unit_id == "b-00-meta" else None,
                round_tag_prefix=f"repair-r{round_no:02d}",
                repair_feedback=feedback_lines,
            )

            source_sha, tm_key = translate.compute_tm_keys(
                unit_id, src_payload, locale, glossary_version, prompt_version
            )
            envelope = translate.build_checkpoint_envelope(
                unit_id=unit_id,
                unit_type=unit_type,
                locale=locale,
                source_content_sha256=source_sha,
                tm_key=tm_key,
                glossary_version=glossary_version,
                prompt_version=prompt_version,
                model_id=str(cfg.server["model"]),
                source_payload=src_payload,
                translated_payload=tr_payload,
                reassembled_block=reassembled,
                translation_source="machine",
                review_status="draft",
            )
            translate.write_checkpoint_atomic(
                translate.checkpoint_path(run_ctx, locale, unit_id), envelope
            )

            if unit_id == "b-00-meta":
                loc_state["meta"] = reassembled
                loc_state["sim_strings"] = dict(tr_payload.get("sim_strings", {}))
            else:
                tr_blocks_by_id[unit_id] = reassembled
            loc_state.setdefault("unit_status", {})[unit_id] = f"repaired-r{round_no:02d}"
            repaired_set.add(unit_id)
            repaired_list.append(unit_id)

        loc_state["blocks"]["blocks"] = [
            tr_blocks_by_id[str(b["id"])] for b in en_blocks_list
        ]
        repaired_units_by_locale[locale] = repaired_set
        round_history_by_locale[locale] = [
            {
                "round": round_no,
                "repaired_units": repaired_list,
                "issues_targeted": [
                    i for uid in repaired_list for i in units_map.get(uid, [])
                ],
            }
        ]

    return updated_out, repaired_units_by_locale, round_history_by_locale
