"""JSON Schemas for the exam/series pipeline (E1-E4).

Contracts between the stages and their consumers (the F7 test player, the
admin blueprint/coverage views, the DB importer that a later wave owns) and the
deterministic eval checkers in `evals/checkers/exam_checks.py`.

Design rules, mirroring the rest of `factory/`:

- structure strict, prose loose: ids, enums, counts, marks and citations are
  exact; sentences are not constrained beyond a minimum length;
- `additionalProperties: false` on the paper fixture and the exported item
  rows, so a typo in tracked data fails loudly instead of being dropped;
- the **paper fixture has no text field at all**, by design: any key that could
  carry a question, option, passage or answer text is absent from the schema,
  and `validate_paper` separately rejects a document that carries one under an
  unexpected key. That is `DEC-COMP-001` made structural.
"""

from __future__ import annotations

from typing import Any

from . import (
    CONTENT_MODES,
    EXAM_LANGUAGES,
    LICENCE_BASES,
    PACK_LANGUAGES,
    PAPER_SCOPES,
    PAPER_TYPES,
    QUESTION_TYPES,
    SOURCE_TYPES,
)

PAPER_PROVENANCE = {
    "type": "object",
    "required": [
        "basis",
        "question_map_basis",
        "source_url",
        "retrieved_at",
        "verified",
    ],
    "additionalProperties": False,
    "properties": {
        "basis": {"enum": ["public_blueprint", "authored_estimate"]},
        "question_map_basis": {
            "enum": ["published_map", "authored_estimate"],
        },
        "source_url": {"type": "string", "minLength": 10},
        "retrieved_at": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"},
        "verified": {"type": "boolean"},
        "notes": {"type": "string", "minLength": 10},
    },
}

PAPER_SECTION = {
    "type": "object",
    "required": ["id", "marks_each", "question_count"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string", "pattern": "^[A-F]$"},
        "marks_each": {"type": "integer", "minimum": 1, "maximum": 10},
        "question_count": {"type": "integer", "minimum": 1, "maximum": 60},
    },
}

PAPER_QUESTION = {
    "type": "object",
    "required": ["no", "section", "type", "marks", "chapter_id"],
    "additionalProperties": False,
    "properties": {
        "no": {"type": "string", "pattern": "^[0-9]{1,2}(?:[a-z])?$"},
        "section": {"type": "string", "pattern": "^[A-F]$"},
        "type": {"enum": list(QUESTION_TYPES)},
        "marks": {"type": "integer", "minimum": 1, "maximum": 10},
        "chapter_id": {"type": "string", "minLength": 6},
    },
}

# One tracked paper *metadata* fixture (`sources/exam/papers/*.json`). No text.
PAPER_FIXTURE = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "ZivonExamPaperFixture",
    "type": "object",
    "required": [
        "schema_version",
        "paper_id",
        "board",
        "class_num",
        "subject",
        "year",
        "paper_type",
        "language",
        "scope",
        "max_marks",
        "duration_min",
        "sections",
        "questions",
        "provenance",
    ],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"const": 1},
        "paper_id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{5,79}$"},
        "board": {"const": "CBSE"},
        "class_num": {"enum": [10, 12]},
        "subject": {"enum": ["Physics", "Science"]},
        "subject_code": {"type": ["string", "null"]},
        "year": {"type": "integer", "minimum": 2015, "maximum": 2100},
        "paper_type": {"enum": list(PAPER_TYPES)},
        "set_code": {"type": ["string", "null"]},
        "language": {"enum": list(EXAM_LANGUAGES)},
        "scope": {"enum": list(PAPER_SCOPES)},
        "max_marks": {"type": "integer", "minimum": 20, "maximum": 100},
        "duration_min": {"type": "integer", "minimum": 30, "maximum": 240},
        "sections": {"type": "array", "minItems": 1, "items": PAPER_SECTION},
        "questions": {
            "type": "array",
            "minItems": 1,
            "maxItems": 60,
            "items": PAPER_QUESTION,
        },
        "provenance": PAPER_PROVENANCE,
    },
}

# E1 output: one record per valid paper + the flat question metadata rows.
PAPER_RECORD = {
    "type": "object",
    "required": [
        "paper_id",
        "board",
        "class_num",
        "subject",
        "year",
        "paper_type",
        "language",
        "scope",
        "max_marks",
        "duration_min",
        "sections",
        "question_count",
        "scope_marks",
        "provenance",
        "file_sha256",
    ],
    "additionalProperties": False,
    "properties": {
        "paper_id": {"type": "string"},
        "board": {"const": "CBSE"},
        "class_num": {"enum": [10, 12]},
        "subject": {"enum": ["Physics", "Science"]},
        "subject_code": {"type": ["string", "null"]},
        "year": {"type": "integer"},
        "paper_type": {"enum": list(PAPER_TYPES)},
        "set_code": {"type": ["string", "null"]},
        "language": {"enum": list(EXAM_LANGUAGES)},
        "scope": {"enum": list(PAPER_SCOPES)},
        "max_marks": {"type": "integer"},
        "scope_marks": {"type": "integer", "minimum": 1},
        "duration_min": {"type": "integer"},
        "sections": {"type": "array", "items": PAPER_SECTION},
        "question_count": {"type": "integer", "minimum": 1},
        "provenance": PAPER_PROVENANCE,
        "file_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    },
}

QUESTION_RECORD = {
    "type": "object",
    "required": ["paper_id", "question_no", "section", "type", "marks", "chapter_id"],
    "additionalProperties": False,
    "properties": {
        "paper_id": {"type": "string"},
        "question_no": {"type": "string"},
        "section": {"type": "string"},
        "type": {"enum": list(QUESTION_TYPES)},
        "marks": {"type": "integer", "minimum": 1, "maximum": 10},
        "chapter_id": {"type": "string"},
    },
}

EXAM_INGEST = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "ZivonExamIngest",
    "type": "object",
    "required": [
        "schema_version",
        "stage",
        "papers",
        "questions",
        "counts",
        "source_text_stored",
    ],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"const": 1},
        "stage": {"const": "E1-ingest"},
        "papers": {"type": "array", "items": PAPER_RECORD},
        "questions": {"type": "array", "items": QUESTION_RECORD},
        "counts": {
            "type": "object",
            "required": ["papers", "questions", "by_class", "by_paper_type"],
            "additionalProperties": False,
            "properties": {
                "papers": {"type": "integer"},
                "questions": {"type": "integer"},
                "by_class": {"type": "object"},
                "by_paper_type": {"type": "object"},
            },
        },
        # Always false in this pipeline: a fixture cannot carry source text.
        # Recorded so an audit does not have to trust the reader.
        "source_text_stored": {"const": False},
        "gate": {"type": "object"},
    },
}

# E2 output: one per class. Shares are recomputed by the checker, never trusted.
EXAM_BLUEPRINT = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "ZivonExamBlueprint",
    "type": "object",
    "required": [
        "schema_version",
        "stage",
        "class_num",
        "subject",
        "subject_code",
        "papers_used",
        "window",
        "recency",
        "chapters",
        "type_mix",
        "section_template",
        "archetypes",
        "confidence",
    ],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"const": 1},
        "stage": {"const": "E2-blueprint"},
        "class_num": {"enum": [10, 12]},
        "subject": {"type": "string"},
        "subject_code": {"type": ["string", "null"]},
        "papers_used": {"type": "array", "items": {"type": "string"}},
        "window": {
            "type": "object",
            "required": ["start_year", "end_year", "years"],
            "additionalProperties": False,
            "properties": {
                "start_year": {"type": "integer"},
                "end_year": {"type": "integer"},
                "years": {"type": "integer"},
            },
        },
        "recency": {
            "type": "object",
            "required": ["decay", "weights"],
            "additionalProperties": False,
            "properties": {
                "decay": {"type": "number"},
                "weights": {
                    "type": "object",
                    "additionalProperties": {"type": "number"},
                },
            },
        },
        "chapters": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "chapter_id",
                    "weighted_marks",
                    "share",
                    "papers_observed",
                ],
                "additionalProperties": False,
                "properties": {
                    "chapter_id": {"type": "string"},
                    "weighted_marks": {"type": "number"},
                    "share": {"type": "number"},
                    "papers_observed": {"type": "integer"},
                },
            },
        },
        "type_mix": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["type", "share", "weighted_marks"],
                "additionalProperties": False,
                "properties": {
                    "type": {"enum": list(QUESTION_TYPES)},
                    "share": {"type": "number"},
                    "weighted_marks": {"type": "number"},
                },
            },
        },
        "section_template": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "marks_each", "question_count", "marks_total"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "marks_each": {"type": "integer"},
                    "question_count": {"type": "integer"},
                    "marks_total": {"type": "integer"},
                },
            },
        },
        "archetypes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "archetype_id",
                    "chapter_id",
                    "type",
                    "marks",
                    "weighted_count",
                    "share",
                ],
                "additionalProperties": False,
                "properties": {
                    "archetype_id": {"type": "string"},
                    "chapter_id": {"type": "string"},
                    "type": {"enum": list(QUESTION_TYPES)},
                    "marks": {"type": "integer"},
                    "weighted_count": {"type": "number"},
                    "share": {"type": "number"},
                },
            },
        },
        "confidence": {
            "type": "object",
            "required": ["verified_papers", "unverified_papers", "question_map_basis"],
            "additionalProperties": False,
            "properties": {
                "verified_papers": {"type": "integer"},
                "unverified_papers": {"type": "integer"},
                "question_map_basis": {"enum": ["published_map", "authored_estimate"]},
            },
        },
        "gate": {"type": "object"},
    },
}

# One authored series item (before export). Answer shapes depend on type.
LOCALE_TEXT = {
    "type": "object",
    "required": ["prompt", "explanation"],
    "additionalProperties": False,
    "properties": {
        "prompt": {"type": "string", "minLength": 8},
        "options": {
            "type": "array",
            "minItems": 4,
            "maxItems": 4,
            "items": {"type": "string", "minLength": 1},
        },
        "explanation": {"type": "string", "minLength": 1},
        "misconception": {"type": "string", "minLength": 5},
        "model_answer": {"type": "string", "minLength": 5},
    },
}

ANSWER = {
    "type": "object",
    "oneOf": [
        {
            "required": ["index"],
            "additionalProperties": False,
            "properties": {"index": {"type": "integer", "minimum": 0, "maximum": 3}},
        },
        {
            "required": ["value", "tolerance", "unit"],
            "additionalProperties": False,
            "properties": {
                "value": {"type": "number"},
                "tolerance": {"type": "number", "minimum": 0},
                "unit": {"type": "string", "minLength": 1},
            },
        },
        {
            "required": ["kind"],
            "additionalProperties": False,
            "properties": {"kind": {"const": "open"}},
        },
    ],
}

EXAM_ITEM = {
    "type": "object",
    "required": [
        "item_id",
        "base_item_id",
        "origin",
        "class_level",
        "chapter_id",
        "concept_id",
        "type",
        "difficulty",
        "marks",
        "section",
        "languages",
        "locales",
        "answer",
        "source_type",
        "pattern_ref",
        "similarity",
        "series_ids",
    ],
    "additionalProperties": False,
    "properties": {
        "item_id": {"type": "string", "minLength": 4},
        "base_item_id": {"type": "string", "minLength": 4},
        "origin": {"enum": ["assessment_bank", "generation_required"]},
        "class_level": {"enum": [9, 10, 11, 12]},
        "chapter_id": {"type": "string", "minLength": 6},
        "concept_id": {"type": "string", "minLength": 6},
        "type": {"enum": list(QUESTION_TYPES)},
        "difficulty": {"enum": ["easy", "medium", "hard"]},
        "marks": {"type": "integer", "minimum": 1, "maximum": 10},
        "section": {"type": ["string", "null"]},
        "languages": {"type": "array", "items": {"enum": list(PACK_LANGUAGES)}},
        "locales": {"type": "object", "additionalProperties": LOCALE_TEXT},
        "answer": ANSWER,
        "source_type": {"enum": list(SOURCE_TYPES)},
        "source_ref": {"type": ["object", "null"]},
        "licence_basis": {"enum": list(LICENCE_BASES)},
        "permission_ref": {"type": ["string", "null"]},
        "pattern_ref": {"type": "string", "minLength": 3},
        "similarity": {"type": "object"},
        "series_ids": {"type": "array", "items": {"type": "string"}},
    },
}

# Exported item row: one per (item, language), what the player consumes.
EXAM_QUESTION_ROW = {
    "type": "object",
    "required": [
        "question_id",
        "item_id",
        "base_item_id",
        "class_level",
        "chapter_id",
        "concept_id",
        "type",
        "difficulty",
        "marks",
        "language",
        "prompt",
        "answer",
        "explanation",
        "source_type",
        "pattern_ref",
        "series_ids",
    ],
    "additionalProperties": False,
    "properties": {
        "question_id": {"type": "string"},
        "item_id": {"type": "string"},
        "base_item_id": {"type": "string"},
        "class_level": {"type": "integer"},
        "chapter_id": {"type": "string"},
        "concept_id": {"type": "string"},
        "type": {"enum": list(QUESTION_TYPES)},
        "difficulty": {"enum": ["easy", "medium", "hard"]},
        "marks": {"type": "integer"},
        "language": {"enum": list(PACK_LANGUAGES)},
        "section": {"type": ["string", "null"]},
        "prompt": {"type": "string"},
        "options": {"type": "array", "items": {"type": "string"}},
        "answer": ANSWER,
        "explanation": {"type": "string"},
        "misconception": {"type": "string"},
        "model_answer": {"type": "string"},
        "source_type": {"enum": list(SOURCE_TYPES)},
        "source_ref": {"type": ["object", "null"]},
        "pattern_ref": {"type": "string"},
        "similarity": {"type": "object"},
        "series_ids": {"type": "array", "items": {"type": "string"}},
    },
}

SERIES_SECTION_SLOT = {
    "type": "object",
    "required": ["slot_id", "section", "type", "marks", "chapter_id", "item_id"],
    "additionalProperties": False,
    "properties": {
        "slot_id": {"type": "string"},
        "section": {"type": "string"},
        "type": {"enum": list(QUESTION_TYPES)},
        "marks": {"type": "integer"},
        "chapter_id": {"type": "string"},
        "item_id": {"type": ["string", "null"]},
    },
}

SERIES_MANIFEST = {
    "type": "object",
    "required": [
        "series_id",
        "label",
        "label_key",
        "purpose",
        "status",
        "enabled",
        "language_policy",
        "source_policy",
        "notice_id",
        "minimum",
        "delivered",
        "item_ids",
        "papers",
        "sets",
        "marks_total",
        "duration_min",
    ],
    "additionalProperties": False,
    "properties": {
        "series_id": {"type": "string"},
        "label": {"type": "string"},
        "label_key": {"type": "string"},
        "purpose": {"type": "string"},
        "status": {"enum": ["active", "disabled"]},
        "enabled": {"type": "boolean"},
        "disabled_reason": {"type": ["string", "null"]},
        "language_policy": {"type": "array", "items": {"enum": list(PACK_LANGUAGES)}},
        "source_policy": {"type": "string"},
        "notice_id": {"type": ["string", "null"]},
        "copy": {"type": "string"},
        "minimum": {"type": "object"},
        "delivered": {"type": "object"},
        "gap": {"type": "object"},
        "item_ids": {"type": "array", "items": {"type": "string"}},
        "papers": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "paper_id",
                    "sections",
                    "item_ids",
                    "filled_slots",
                    "total_slots",
                    "marks_total",
                ],
                "additionalProperties": False,
                "properties": {
                    "paper_id": {"type": "string"},
                    "sections": {"type": "array", "items": SERIES_SECTION_SLOT},
                    "item_ids": {"type": "array", "items": {"type": "string"}},
                    "filled_slots": {"type": "integer"},
                    "total_slots": {"type": "integer"},
                    "marks_total": {"type": "integer"},
                },
            },
        },
        "sets": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["set_id", "kind", "item_ids"],
                "additionalProperties": False,
                "properties": {
                    "set_id": {"type": "string"},
                    "kind": {"type": "string"},
                    "chapter_id": {"type": ["string", "null"]},
                    "item_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "marks_total": {"type": ["integer", "null"]},
        "duration_min": {"type": ["integer", "null"]},
    },
}

EXAM_SERIES_PACK = {
    "type": "object",
    "required": ["schema_version", "class_num", "series"],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"const": 1},
        "class_num": {"enum": [10, 12]},
        "series": {"type": "array", "items": SERIES_MANIFEST},
        "gate": {"type": "object"},
    },
}

EXAM_PACK_MANIFEST = {
    "type": "object",
    "required": [
        "pack_version",
        "exam_pipeline_version",
        "run_id",
        "generated_at",
        "class_num",
        "subject",
        "content_mode",
        "notice_version",
        "compliance",
        "counts",
        "coverage",
        "publish",
        "gate",
        "content_hash",
        "files",
    ],
    "additionalProperties": False,
    "properties": {
        "pack_version": {"const": 1},
        "exam_pipeline_version": {"type": "string"},
        "run_id": {"type": "string"},
        "generated_at": {"type": "string"},
        "class_num": {"enum": [10, 12]},
        "subject": {"type": "string"},
        "subject_code": {"type": ["string", "null"]},
        "content_mode": {"enum": list(CONTENT_MODES)},
        "notice_version": {"type": "string"},
        "compliance": {"type": "object"},
        "counts": {"type": "object"},
        "coverage": {"type": "object"},
        "publish": {"type": "object"},
        "gate": {"type": "object"},
        "content_hash": {"type": "string"},
        "files": {"type": "object"},
    },
}

EXAM_DEFECT_SAMPLE = {
    "type": "object",
    "required": [
        "sample_id",
        "defect_class",
        "expected_rule",
        "expected_severity",
        "mutations",
    ],
    "additionalProperties": False,
    "properties": {
        "sample_id": {"type": "string", "pattern": "^SD-(EXM|SER)-[0-9]{3}$"},
        "defect_class": {"type": "string", "minLength": 4},
        "expected_rule": {"type": "string", "minLength": 4},
        "expected_severity": {"enum": ["fatal", "major", "minor"]},
        "mutations": {
            "type": "object",
            "required": ["operation"],
            "additionalProperties": True,
            "properties": {
                "operation": {
                    "enum": [
                        "patch_paper",
                        "remove_paper",
                        "add_paper",
                        "patch_question",
                        "add_question",
                        "patch_blueprint_chapter",
                        "set_question_key",
                        "set_section_count",
                        "patch_item",
                        "remove_item",
                        "patch_series",
                        "remove_series",
                        "drop_section",
                        "drop_paper_slots",
                        "drop_series_items",
                    ]
                }
            },
        },
    },
}

EXAM_GOLDEN_EXPECTED = {
    "type": "object",
    "required": ["golden_id", "class_num", "papers", "blueprint", "series"],
    "additionalProperties": False,
    "properties": {
        "golden_id": {"type": "string"},
        "class_num": {"enum": [10, 12]},
        "papers": {
            "type": "object",
            "required": ["min", "by_type"],
            "additionalProperties": False,
            "properties": {
                "min": {"type": "integer"},
                "by_type": {"type": "object"},
            },
        },
        "blueprint": {
            "type": "object",
            "required": [
                "chapter_ids",
                "section_ids",
                "scope_marks",
                "type_counts_min",
            ],
            "additionalProperties": False,
            "properties": {
                "chapter_ids": {"type": "array", "items": {"type": "string"}},
                "section_ids": {"type": "array", "items": {"type": "string"}},
                "scope_marks": {"type": "integer"},
                "type_counts_min": {"type": "object"},
            },
        },
        "series": {
            "type": "object",
            "required": ["ids", "expected_minimums"],
            "additionalProperties": False,
            "properties": {
                "ids": {"type": "array", "items": {"type": "string"}},
                "expected_minimums": {"type": "object"},
                "expected_gaps": {"type": "object"},
                "dark": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
}

EXAM_SCHEMAS: dict[str, dict[str, Any]] = {
    "exam_paper_fixture": PAPER_FIXTURE,
    "exam_ingest": EXAM_INGEST,
    "exam_blueprint": EXAM_BLUEPRINT,
    "exam_item": EXAM_ITEM,
    "exam_question_row": EXAM_QUESTION_ROW,
    "exam_series_manifest": SERIES_MANIFEST,
    "exam_series_pack": EXAM_SERIES_PACK,
    "exam_pack_manifest": EXAM_PACK_MANIFEST,
    "exam_defect_sample": EXAM_DEFECT_SAMPLE,
    "exam_golden_expected": EXAM_GOLDEN_EXPECTED,
}

__all__ = [
    "ANSWER",
    "EXAM_BLUEPRINT",
    "EXAM_DEFECT_SAMPLE",
    "EXAM_GOLDEN_EXPECTED",
    "EXAM_INGEST",
    "EXAM_ITEM",
    "EXAM_PACK_MANIFEST",
    "EXAM_QUESTION_ROW",
    "EXAM_SCHEMAS",
    "EXAM_SERIES_PACK",
    "PAPER_FIXTURE",
    "SERIES_MANIFEST",
]
