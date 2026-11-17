"""JSON Schemas for the assessment pipeline (A1-A6).

Frozen contracts between the assessment stages and their consumers (the DB
importer that F0 owns later, the practice/speaking frontends, and the
deterministic eval checkers in `evals/checkers/assessment_checks.py`).

Design rules, mirroring `factory/schemas.py`:

- structure strict, prose loose: ids, enums, counts and citations are exact;
  sentences are not constrained beyond a minimum length;
- the authored seed bank (`ASSESSMENT_ITEM_BANK`) and the exported question
  rows (`ASSESSMENT_QUESTIONS`) are different shapes on purpose - authoring
  keeps one entry per item with all three languages together, the export is
  one row per (item, language) as `docs/.../REQUIREMENTS` §7.3 describes;
- `additionalProperties: false` everywhere so a typo in a seed file fails
  loudly instead of silently dropping a field.

The schemas are registered in `factory.schemas.SCHEMAS` so every handoff
contract in the repo has one registry.
"""

from __future__ import annotations

from typing import Any

from . import DIFFICULTIES, ITEM_TYPES, LANGUAGES

# Where the typed source text lives (NCERT section numbering). A source_ref's
# `section` is checked against the chapter number: "4.1.2" is a section of
# chapter 4, "9.3" a section of chapter 9. `example` is optional and names a
# worked example or exercise the item is anchored to.
SOURCE_REF = {
    "type": "object",
    "required": ["book_id", "section"],
    "additionalProperties": False,
    "properties": {
        "book_id": {"type": "string", "minLength": 3},
        "section": {"type": "string", "pattern": "^[0-9]{1,2}\\.[0-9]"},
        "example": {"type": ["string", "null"]},
        "note": {"type": "string"},
    },
}

# A locale's authored text. `options` is present for MCQ and assertion-reason
# items (validators enforce the four-option rule), absent for numeric items.
_AUTHORED_LOCALE = {
    "type": "object",
    "required": ["prompt", "explanation"],
    "additionalProperties": False,
    "properties": {
        "prompt": {"type": "string", "minLength": 10},
        "options": {
            "type": "array",
            "minItems": 4,
            "maxItems": 4,
            "items": {"type": "string", "minLength": 1},
        },
        "explanation": {"type": "string", "minLength": 1},
        "misconception": {"type": "string", "minLength": 5},
    },
}

# Locale completeness is a HARNESS RULE (validate_item_bank's
# `item.language_missing`), not a schema requirement: the schema must accept a
# bank that is missing a translation so the gate can name the missing variant
# and the seeded-defect check can prove the rule fires.
_AUTHORED_LOCALES = {
    "type": "object",
    "minProperties": 1,
    "propertyNames": {"enum": list(LANGUAGES)},
    "additionalProperties": False,
    "properties": {lang: _AUTHORED_LOCALE for lang in LANGUAGES},
}

# One correct answer. MCQ/assertion-reason use an option index; numeric uses a
# value with a declared tolerance and unit (REQUIREMENTS §7.3).
ANSWER = {
    "type": "object",
    "oneOf": [
        {
            "required": ["index"],
            "additionalProperties": False,
            "properties": {"index": {"type": "integer", "minimum": 0}},
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
    ],
}

ASSESSMENT_ITEM = {
    "type": "object",
    "required": [
        "item_id",
        "concept_id",
        "type",
        "difficulty",
        "marks",
        "computation_steps",
        "source_ref",
        "answer",
        "locales",
    ],
    "additionalProperties": False,
    "properties": {
        "item_id": {"type": "string", "pattern": "^q-[a-z0-9-]+$"},
        "concept_id": {"type": "string", "minLength": 3},
        "type": {"enum": list(ITEM_TYPES)},
        "difficulty": {"enum": list(DIFFICULTIES)},
        "marks": {"type": "integer", "minimum": 1, "maximum": 5},
        "computation_steps": {"type": "integer", "minimum": 0, "maximum": 12},
        "distractor_index": {"type": ["integer", "null"], "minimum": 0},
        "source_ref": SOURCE_REF,
        "answer": ANSWER,
        "locales": _AUTHORED_LOCALES,
    },
}

ASSESSMENT_ITEM_BANK: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "AssessmentItemBank",
    "type": "object",
    "required": [
        "schema_version",
        "chapter_id",
        "class",
        "generator",
        "source",
        "items",
    ],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"type": "integer", "minimum": 1},
        "chapter_id": {"type": "string", "pattern": "^class-[0-9]{1,2}-[a-z0-9-]+$"},
        "class": {"type": "integer", "minimum": 9, "maximum": 12},
        "generator": {"type": "string", "minLength": 3},
        "source": {
            "type": "object",
            "required": ["book_id", "chapter_number", "chapter_title"],
            "additionalProperties": False,
            "properties": {
                "book_id": {"type": "string", "minLength": 3},
                "chapter_number": {"type": "integer", "minimum": 1},
                "chapter_title": {"type": "string", "minLength": 3},
                "source_type": {
                    "enum": ["generated", "past_paper", "sample_paper", "curated_pyq"]
                },
                "note": {"type": "string"},
            },
        },
        "items": {
            "type": "array",
            "minItems": 1,
            "maxItems": 60,
            "items": ASSESSMENT_ITEM,
        },
    },
}

SYLLABUS_CONCEPT = {
    "type": "object",
    "required": [
        "concept_id",
        "title",
        "title_hi",
        "description",
        "prerequisites",
        "section_refs",
    ],
    "additionalProperties": False,
    "properties": {
        "concept_id": {
            "type": "string",
            "pattern": "^class-[0-9]{1,2}-[a-z0-9-]+$",
        },
        "title": {"type": "string", "minLength": 3},
        "title_hi": {"type": "string", "minLength": 1},
        "description": {"type": "string", "minLength": 10},
        "prerequisites": {
            "type": "array",
            "items": {"type": "string", "minLength": 3},
            "uniqueItems": True,
        },
        "section_refs": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "pattern": "^[0-9]{1,2}(\\.[0-9]+)+$"},
        },
    },
}

SYLLABUS_CHAPTER = {
    "type": "object",
    "required": [
        "chapter_id",
        "class",
        "number",
        "title",
        "title_hi",
        "book_id",
        "status",
        "order",
        "concepts_status",
        "concepts",
        "lesson_topic_slug",
    ],
    "additionalProperties": False,
    "properties": {
        "chapter_id": {"type": "string", "pattern": "^class-[0-9]{1,2}-[a-z0-9-]+$"},
        "class": {"type": "integer", "minimum": 9, "maximum": 12},
        "number": {"type": "integer", "minimum": 1, "maximum": 40},
        "title": {"type": "string", "minLength": 3},
        "title_hi": {"type": "string", "minLength": 1},
        "book_id": {"type": "string", "minLength": 3},
        "status": {"enum": ["live", "lesson_only", "in_development"]},
        "order": {"type": "integer", "minimum": 1},
        "exam_weight": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
        "exam_weight_status": {
            "enum": ["curated", "pending_p3_blueprint", "not_applicable"]
        },
        "concepts_status": {"enum": ["curated", "pending_r1_5"]},
        "concepts": {"type": "array", "items": SYLLABUS_CONCEPT},
        "lesson_topic_slug": {"type": ["string", "null"]},
    },
}

_SYLLABUS_CLASS = {
    "type": "object",
    "required": ["class", "book_ids", "textbook_title", "chapters"],
    "additionalProperties": False,
    "properties": {
        "class": {"type": "integer", "minimum": 9, "maximum": 12},
        "book_ids": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 3},
        },
        "textbook_title": {"type": "string", "minLength": 3},
        "chapters": {"type": "array", "minItems": 1, "items": SYLLABUS_CHAPTER},
    },
}

SYLLABUS: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "AssessmentSyllabus",
    "type": "object",
    "required": ["schema_version", "subject", "source_basis", "classes"],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"type": "integer", "minimum": 1},
        "subject": {"type": "string", "enum": ["physics"]},
        "source_basis": {"type": "string", "minLength": 10},
        "updated_at": {"type": "string"},
        "classes": {
            "type": "array",
            "minItems": 4,
            "maxItems": 4,
            "items": _SYLLABUS_CLASS,
        },
    },
}

# ---------------------------------------------------------------- speaking
_AUTHORED_RUBRIC_LOCALE = {
    "type": "object",
    "required": ["prompt", "key_ideas", "model_answer"],
    "additionalProperties": False,
    "properties": {
        "prompt": {"type": "string", "minLength": 10},
        "key_ideas": {
            "type": "array",
            "minItems": 3,
            "maxItems": 5,
            "items": {"type": "string", "minLength": 5},
        },
        "model_answer": {"type": "string", "minLength": 40},
    },
}

RUBRIC_THRESHOLDS = {
    "type": "object",
    "required": ["pass_ratio", "strong_ratio", "min_key_ideas", "max_duration_s"],
    "additionalProperties": False,
    "properties": {
        "pass_ratio": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
        "strong_ratio": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
        "min_key_ideas": {"type": "integer", "minimum": 1, "maximum": 5},
        "max_duration_s": {"type": "integer", "minimum": 15, "maximum": 300},
    },
}

ASSESSMENT_SPEAKING_BANK: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "AssessmentSpeakingBank",
    "type": "object",
    "required": ["schema_version", "chapter_id", "class", "prompts"],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"type": "integer", "minimum": 1},
        "chapter_id": {"type": "string", "pattern": "^class-[0-9]{1,2}-[a-z0-9-]+$"},
        "class": {"type": "integer", "minimum": 9, "maximum": 12},
        "prompts": {
            "type": "array",
            "minItems": 1,
            "maxItems": 12,
            "items": {
                "type": "object",
                "required": [
                    "prompt_id",
                    "concept_ids",
                    "source_ref",
                    "thresholds",
                    "locales",
                ],
                "additionalProperties": False,
                "properties": {
                    "prompt_id": {"type": "string", "pattern": "^spk-[a-z0-9-]+$"},
                    "concept_ids": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "minLength": 3},
                    },
                    "source_ref": SOURCE_REF,
                    "thresholds": RUBRIC_THRESHOLDS,
                    "locales": {
                        "type": "object",
                        "required": list(LANGUAGES),
                        "additionalProperties": False,
                        "properties": {
                            lang: _AUTHORED_RUBRIC_LOCALE for lang in LANGUAGES
                        },
                    },
                },
            },
        },
    },
}

# ---------------------------------------------------------------- export rows
_QUESTION_ANSWER = {
    "type": "object",
    "oneOf": [
        {
            "required": ["index"],
            "additionalProperties": False,
            "properties": {"index": {"type": "integer", "minimum": 0}},
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
    ],
}

QUESTION_ROW = {
    "type": "object",
    "required": [
        "question_id",
        "base_item_id",
        "class_level",
        "chapter_id",
        "concept_id",
        "type",
        "difficulty",
        "marks",
        "language",
        "source_type",
        "source_ref",
        "prompt",
        "answer",
        "explanation",
        "expected_time_ms",
        "status",
        "review_mode",
        "version",
        "generator",
        "run_id",
    ],
    "additionalProperties": False,
    "properties": {
        "question_id": {"type": "string", "pattern": "^q-[A-Za-z0-9-]+$"},
        "base_item_id": {"type": "string", "pattern": "^q-[A-Za-z0-9-]+$"},
        "class_level": {"type": "integer", "minimum": 9, "maximum": 12},
        "chapter_id": {"type": "string", "pattern": "^class-[0-9]{1,2}-[a-z0-9-]+$"},
        "concept_id": {"type": "string", "minLength": 3},
        "type": {"enum": list(ITEM_TYPES)},
        "difficulty": {"enum": list(DIFFICULTIES)},
        "marks": {"type": "integer", "minimum": 1, "maximum": 5},
        "language": {"enum": list(LANGUAGES)},
        "source_type": {
            "enum": ["generated", "past_paper", "sample_paper", "curated_pyq"]
        },
        "source_ref": SOURCE_REF,
        "prompt": {"type": "string", "minLength": 10},
        "options": {
            "type": "array",
            "minItems": 4,
            "maxItems": 4,
            "items": {"type": "string", "minLength": 1},
        },
        "answer": _QUESTION_ANSWER,
        "explanation": {"type": "string", "minLength": 1},
        "misconception": {"type": "string", "minLength": 5},
        "distractor_index": {"type": "integer", "minimum": 0, "maximum": 3},
        "expected_time_ms": {"type": "integer", "minimum": 1000},
        "status": {"enum": ["draft", "reviewed", "published"]},
        "review_mode": {"enum": ["deterministic", "judge", "human"]},
        "version": {"type": "integer", "minimum": 1},
        "generator": {"type": "string", "minLength": 3},
        "run_id": {"type": "string", "minLength": 1},
    },
}

ASSESSMENT_QUESTIONS: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "AssessmentQuestionRows",
    "type": "object",
    "required": ["schema_version", "chapter_id", "questions"],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"type": "integer", "minimum": 1},
        "chapter_id": {"type": "string", "pattern": "^class-[0-9]{1,2}-[a-z0-9-]+$"},
        "questions": {"type": "array", "minItems": 1, "items": QUESTION_ROW},
    },
}

_SPEAKING_KEY_IDEA = {
    "type": "object",
    "required": ["idea_id", "text"],
    "additionalProperties": False,
    "properties": {
        "idea_id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]*$"},
        "text": {"type": "string", "minLength": 5},
    },
}

SPEAKING_ROW = {
    "type": "object",
    "required": [
        "prompt_id",
        "chapter_id",
        "class_level",
        "concept_ids",
        "language",
        "prompt",
        "key_ideas",
        "model_answer",
        "model_answer_source",
        "thresholds",
        "version",
    ],
    "additionalProperties": False,
    "properties": {
        "prompt_id": {"type": "string", "pattern": "^spk-[a-z0-9-]+$"},
        "chapter_id": {"type": "string", "pattern": "^class-[0-9]{1,2}-[a-z0-9-]+$"},
        "class_level": {"type": "integer", "minimum": 9, "maximum": 12},
        "concept_ids": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 3},
        },
        "language": {"enum": list(LANGUAGES)},
        "prompt": {"type": "string", "minLength": 10},
        "key_ideas": {
            "type": "array",
            "minItems": 3,
            "maxItems": 5,
            "items": _SPEAKING_KEY_IDEA,
        },
        "model_answer": {"type": "string", "minLength": 40},
        "model_answer_source": SOURCE_REF,
        "thresholds": RUBRIC_THRESHOLDS,
        "version": {"type": "integer", "minimum": 1},
    },
}

ASSESSMENT_SPEAKING_ROWS: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "AssessmentSpeakingRows",
    "type": "object",
    "required": ["schema_version", "chapter_id", "prompts"],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"type": "integer", "minimum": 1},
        "chapter_id": {"type": "string", "pattern": "^class-[0-9]{1,2}-[a-z0-9-]+$"},
        "prompts": {"type": "array", "minItems": 1, "items": SPEAKING_ROW},
    },
}

# ---------------------------------------------------------------- time priors
TIME_PRIOR_QUESTION = {
    "type": "object",
    "required": ["question_id", "expected_time_ms", "basis"],
    "additionalProperties": False,
    "properties": {
        "question_id": {"type": "string", "minLength": 3},
        "expected_time_ms": {"type": "integer", "minimum": 1000},
        "basis": {
            "type": "object",
            "required": [
                "type",
                "difficulty",
                "marks",
                "language",
                "word_count",
                "computation_steps",
                "formula_version",
            ],
            "additionalProperties": False,
            "properties": {
                "type": {"enum": list(ITEM_TYPES)},
                "difficulty": {"enum": list(DIFFICULTIES)},
                "marks": {"type": "integer", "minimum": 1},
                "language": {"enum": list(LANGUAGES)},
                "word_count": {"type": "integer", "minimum": 0},
                "computation_steps": {"type": "integer", "minimum": 0},
                "formula_version": {"type": "string", "minLength": 3},
            },
        },
    },
}

TIME_PRIORS: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "AssessmentTimePriors",
    "type": "object",
    "required": ["schema_version", "formula_version", "questions", "topics"],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"type": "integer", "minimum": 1},
        "formula_version": {"type": "string", "minLength": 3},
        "questions": {
            "type": "array",
            "minItems": 1,
            "items": TIME_PRIOR_QUESTION,
        },
        "topics": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": [
                    "chapter_id",
                    "scope",
                    "scope_id",
                    "expected_time_ms",
                    "questions",
                ],
                "additionalProperties": False,
                "properties": {
                    "chapter_id": {
                        "type": "string",
                        "pattern": "^class-[0-9]{1,2}-[a-z0-9-]+$",
                    },
                    "scope": {"enum": ["chapter", "concept"]},
                    "scope_id": {"type": "string", "minLength": 3},
                    "expected_time_ms": {"type": "integer", "minimum": 1000},
                    "questions": {"type": "integer", "minimum": 1},
                },
            },
        },
    },
}

# ---------------------------------------------------------------- pack
PACK_MANIFEST: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "AssessmentPackManifest",
    "type": "object",
    "required": [
        "pack_version",
        "assessment_pipeline_version",
        "run_id",
        "generated_at",
        "chapter_id",
        "chapter_title",
        "class_level",
        "subject",
        "generator",
        "languages",
        "counts",
        "coverage",
        "gate",
        "content_hash",
        "files",
    ],
    "additionalProperties": False,
    "properties": {
        "pack_version": {"type": "integer", "minimum": 1},
        "assessment_pipeline_version": {"type": "string", "minLength": 1},
        "run_id": {"type": "string", "minLength": 1},
        "generated_at": {"type": "string"},
        "chapter_id": {"type": "string", "pattern": "^class-[0-9]{1,2}-[a-z0-9-]+$"},
        "chapter_title": {"type": "string", "minLength": 3},
        "class_level": {"type": "integer", "minimum": 9, "maximum": 12},
        "subject": {"type": "string", "enum": ["physics"]},
        "generator": {"type": "string", "minLength": 3},
        "languages": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string"},
        },
        "counts": {
            "type": "object",
            "required": [
                "base_items",
                "question_rows",
                "speaking_prompts",
                "concepts",
                "blocks_tagged",
            ],
            "additionalProperties": False,
            "properties": {
                "base_items": {"type": "integer", "minimum": 0},
                "question_rows": {"type": "integer", "minimum": 0},
                "speaking_prompts": {"type": "integer", "minimum": 0},
                "concepts": {"type": "integer", "minimum": 0},
                "blocks_tagged": {"type": "integer", "minimum": 0},
            },
        },
        "coverage": {
            "type": "object",
            "required": ["by_type", "by_difficulty", "by_language", "by_concept"],
            "additionalProperties": False,
            "properties": {
                "by_type": {"type": "object"},
                "by_difficulty": {"type": "object"},
                "by_language": {"type": "object"},
                "by_concept": {"type": "object"},
                "speaking_by_language": {"type": "object"},
                "block_tagging": {"type": "string"},
            },
        },
        "gate": {
            "type": "object",
            "required": ["verdict", "error_count", "warning_count"],
            "additionalProperties": False,
            "properties": {
                "verdict": {"enum": ["pass", "fail"]},
                "error_count": {"type": "integer", "minimum": 0},
                "warning_count": {"type": "integer", "minimum": 0},
            },
        },
        "content_hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
        "files": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "required": ["sha256", "bytes"],
                "additionalProperties": False,
                "properties": {
                    "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "bytes": {"type": "integer", "minimum": 0},
                },
            },
        },
    },
}

# ---------------------------------------------------------------- eval goldens
ASSESSMENT_GOLDEN_EXPECTED: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "AssessmentGoldenExpected",
    "type": "object",
    "required": [
        "golden_id",
        "chapter_id",
        "class_level",
        "item_count",
        "type_counts",
        "difficulty_share",
        "concepts_min",
        "languages",
        "time_prior_ms",
        "speaking_prompts_min",
    ],
    "additionalProperties": False,
    "properties": {
        "golden_id": {"type": "string", "pattern": "^GA-[0-9]{2}$"},
        "chapter_id": {"type": "string", "pattern": "^class-[0-9]{1,2}-[a-z0-9-]+$"},
        "class_level": {"type": "integer", "minimum": 9, "maximum": 12},
        "item_count": {
            "type": "object",
            "required": ["min", "max"],
            "additionalProperties": False,
            "properties": {
                "min": {"type": "integer", "minimum": 1},
                "max": {"type": "integer", "minimum": 1},
            },
        },
        "type_counts": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "required": ["min", "max"],
                "additionalProperties": False,
                "properties": {
                    "min": {"type": "integer", "minimum": 0},
                    "max": {"type": "integer", "minimum": 0},
                },
            },
        },
        "difficulty_share": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "required": ["min", "max"],
                "additionalProperties": False,
                "properties": {
                    "min": {"type": "number", "minimum": 0, "maximum": 1},
                    "max": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
        },
        "concepts_min": {"type": "integer", "minimum": 1},
        "languages": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string"},
        },
        "time_prior_ms": {
            "type": "object",
            "required": ["min", "max"],
            "additionalProperties": False,
            "properties": {
                "min": {"type": "integer", "minimum": 1},
                "max": {"type": "integer", "minimum": 1},
            },
        },
        "speaking_prompts_min": {"type": "integer", "minimum": 1},
    },
}

ASSESSMENT_DEFECT_SAMPLE: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "AssessmentSeededDefect",
    "type": "object",
    "required": [
        "sample_id",
        "chapter_id",
        "defect_class",
        "expected_rule",
        "expected_severity",
        "mutations",
    ],
    "additionalProperties": False,
    "properties": {
        "sample_id": {"type": "string", "pattern": "^SD-ASM-[0-9]{3}$"},
        "chapter_id": {"type": "string", "pattern": "^class-[0-9]{1,2}-[a-z0-9-]+$"},
        "defect_class": {"type": "string", "minLength": 3},
        "expected_rule": {"type": "string", "minLength": 3},
        "expected_severity": {"enum": ["fatal", "major", "minor"]},
        "mutations": {
            "type": "object",
            "required": ["operation"],
            "additionalProperties": False,
            "properties": {
                "operation": {
                    "enum": [
                        "patch_item",
                        "delete_locale",
                        "duplicate_item",
                        "patch_prior",
                    ]
                },
                "item_id": {"type": "string"},
                "source_item_id": {"type": "string"},
                "new_item_id": {"type": "string"},
                "question_id": {"type": "string"},
                "value": {"type": "number"},
                "locale": {"enum": list(LANGUAGES)},
                "patch": {"type": "object"},
            },
        },
    },
}

# Public alias: the manifest schema is imported by name in evals and tests.
ASSESSMENT_PACK_MANIFEST = PACK_MANIFEST

ASSESSMENT_SCHEMAS: dict[str, Any] = {
    "assessment_item_bank": ASSESSMENT_ITEM_BANK,
    "assessment_item": ASSESSMENT_ITEM,
    "assessment_syllabus": SYLLABUS,
    "assessment_speaking_bank": ASSESSMENT_SPEAKING_BANK,
    "assessment_questions": ASSESSMENT_QUESTIONS,
    "assessment_speaking_rows": ASSESSMENT_SPEAKING_ROWS,
    "assessment_time_priors": TIME_PRIORS,
    "assessment_pack_manifest": PACK_MANIFEST,
    "assessment_golden_expected": ASSESSMENT_GOLDEN_EXPECTED,
    "assessment_defect_sample": ASSESSMENT_DEFECT_SAMPLE,
}

__all__ = [
    "ASSESSMENT_DEFECT_SAMPLE",
    "ASSESSMENT_GOLDEN_EXPECTED",
    "ASSESSMENT_ITEM",
    "ASSESSMENT_ITEM_BANK",
    "ASSESSMENT_PACK_MANIFEST",
    "ASSESSMENT_QUESTIONS",
    "ASSESSMENT_SCHEMAS",
    "ASSESSMENT_SPEAKING_BANK",
    "ASSESSMENT_SPEAKING_ROWS",
    "SYLLABUS",
    "TIME_PRIORS",
]
