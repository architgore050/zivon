"""JSON Schemas for every stage handoff.

These are the frozen contracts between stages (v2, 2026-11-03 - consolidated
generation graph). Design notes:
- Block payloads always live under "spec" (AGENTS.md format), which resolves
  the AGENTS.md-vs-TIMELINE.md contradiction in favour of AGENTS.md.
- Every factual block carries citations that must reference ground-truth claim
  ids; the 03-check stage enforces this in code, not vibes.
- Schemas are deliberately loose about prose (strings) and strict about
  structure, ids and enums, so a small local model can satisfy them reliably.
- GENERATED is the one-giant-call contract (02-generate): ground truth, lesson
  and blocks in a single JSON object, so the reasoning layer pays ONE thinking
  cycle instead of three.
"""

from __future__ import annotations

from typing import Any

CITATION = {
    "type": "object",
    "properties": {
        "claim_id": {"type": "string"},
        "source_id": {"type": "string"},
        "note": {"type": "string"},
    },
    "anyOf": [
        {"required": ["claim_id"]},
        {"required": ["source_id"]},
    ],
    "additionalProperties": False,
}

GROUND_TRUTH = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": [
        "topic",
        "summary",
        "claims",
        "key_terms",
        "equations",
        "misconceptions",
        "uncertain",
    ],
    "additionalProperties": False,
    "properties": {
        "topic": {"type": "string", "minLength": 2},
        "summary": {"type": "string", "minLength": 40},
        "claims": {
            "type": "array",
            "minItems": 4,
            "items": {
                "type": "object",
                "required": ["id", "statement", "citations"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "pattern": "^claim-[0-9]{2,3}$"},
                    "statement": {"type": "string", "minLength": 15},
                    "citations": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["source_id", "locator"],
                            "additionalProperties": False,
                            "properties": {
                                "source_id": {"type": "string"},
                                "locator": {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
        "key_terms": {
            "type": "array",
            "minItems": 2,
            "items": {
                "type": "object",
                "required": ["term", "definition", "citations"],
                "additionalProperties": False,
                "properties": {
                    "term": {"type": "string"},
                    "definition": {"type": "string", "minLength": 10},
                    "citations": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["source_id", "locator"],
                            "additionalProperties": False,
                            "properties": {
                                "source_id": {"type": "string"},
                                "locator": {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
        "equations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "expression", "description", "citations"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "pattern": "^eq-[0-9]{2,3}$"},
                    "expression": {"type": "string", "minLength": 2},
                    "description": {"type": "string", "minLength": 10},
                    "citations": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["source_id", "locator"],
                            "additionalProperties": False,
                            "properties": {
                                "source_id": {"type": "string"},
                                "locator": {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
        "misconceptions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "wrong_belief", "correction", "citations"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "pattern": "^mis-[0-9]{2,3}$"},
                    "wrong_belief": {"type": "string", "minLength": 10},
                    "correction": {"type": "string", "minLength": 10},
                    "citations": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["source_id", "locator"],
                            "additionalProperties": False,
                            "properties": {
                                "source_id": {"type": "string"},
                                "locator": {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
        "uncertain": {
            "type": "array",
            "description": "Questions the synthesizer could not answer from the sources. Honesty field.",
            "items": {"type": "string"},
        },
    },
}

LESSON = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["title", "objectives", "sections", "glossary"],
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string", "minLength": 3},
        "objectives": {
            "type": "array",
            "minItems": 2,
            "items": {"type": "string", "minLength": 15},
        },
        "sections": {
            "type": "array",
            "minItems": 2,
            "items": {
                "type": "object",
                "required": ["id", "title", "paragraphs"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "pattern": "^sec-[0-9]{2}$"},
                    "title": {"type": "string", "minLength": 3},
                    "paragraphs": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "minLength": 40},
                    },
                },
            },
        },
        "glossary": {
            "type": "array",
            "minItems": 2,
            "items": {
                "type": "object",
                "required": ["term", "definition"],
                "additionalProperties": False,
                "properties": {
                    "term": {"type": "string"},
                    "definition": {"type": "string", "minLength": 10},
                },
            },
        },
    },
}

BLOCK_TYPES = ["text", "worked_example", "check", "reveal", "diagram", "simulation"]

BLOCKS: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["blocks"],
    "additionalProperties": False,
    "properties": {
        "blocks": {
            "type": "array",
            "minItems": 4,
            # 45, not 18 (2026-11-05): the founder's coverage contract (the chapter
            # is the unit of teaching - every section, in-text question and exercise)
            # needs more blocks than the original 18; the founder's own rebuilt
            # example carries ~28 content blocks for one chapter. The prompt states
            # the same budget - prompt and schema must never contradict each other.
            "maxItems": 45,
            "items": {
                "type": "object",
                "required": ["id", "type", "spec", "citations"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "pattern": "^b-[0-9]{2}$"},
                    "type": {"enum": BLOCK_TYPES},
                    "citations": {"type": "array", "items": CITATION},
                    "spec": {"type": "object"},
                },
            },
        },
    },
}

# Failure categories for review issues (2026-11-08): every 09-review finding
# carries one, so cross-run ledgers can name the classes that prompting and
# generation should target.
REVIEW_CATEGORIES = [
    "answer_key",
    "fact",
    "drawn_behaviour",
    "inconsistency",
    "visual_language",
    "frame",
    "accessibility",
    "rendering",
    "other",
]

CHECK_REPORT = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["verdict", "issues"],
    "additionalProperties": False,
    "properties": {
        "verdict": {"enum": ["pass", "fail"]},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["severity", "message"],
                "additionalProperties": False,
                "properties": {
                    "block_id": {"type": "string"},
                    "severity": {"enum": ["fatal", "major", "minor"]},
                    # Optional (2026-11-08): 09-review's split calls tag every
                    # issue with a failure category; the ledger aggregates them
                    # so prompting improvements can target the common classes.
                    # 03-check does not emit it yet.
                    "category": {"enum": REVIEW_CATEGORIES},
                    "message": {"type": "string", "minLength": 10},
                },
            },
        },
    },
}

INTERACTIVE = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["id", "files"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string"},
        "files": {
            "type": "object",
            "required": [],
            "additionalProperties": {"type": "string"},
            "description": "Map of filename (page.js / page.css fragment names) to full file content.",
        },
    },
}

FIX_PLAN = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["analysis", "files"],
    "additionalProperties": False,
    "properties": {
        "analysis": {"type": "string", "minLength": 20},
        "files": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "description": "Full replacement content for the topic-local files being fixed.",
        },
        # Spec-correction channel (2026-11-09): the reviewer gates the page
        # the renderer drew (index.html) - errors in block CONTENT (wrong
        # diagram geometry, wrong caption) live in the block specs, not in
        # page.js. The fixer returns corrected FULL block objects here; the
        # harness merges them by id and re-renders the page body from the
        # corrected specs (renderer re-runs the blocks-to-body path, so
        # index.html still has exactly one writer). Simulations are excluded
        # (their behavior is page.js draw code, owned by 05/10 boundary).
        # Optional; omit when the defect is code-only.
        "blocks": {
            "type": "array",
            "minItems": 1,
            "items": BLOCKS["properties"]["blocks"]["items"],
        },
    },
}

REVIEW_REPORT = CHECK_REPORT  # same shape: verdict + issues

# 09-review sub-call contract (2026-11-08 split): ISSUES ONLY. The verdict is
# computed by the harness from severities - the rule that used to be prompt
# prose ("fail only if at least one fatal") is now code (guarantee in the
# harness, not in the prompt), and each call carries a smaller task.
REVIEW_CALL_REPORT = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["issues"],
    "additionalProperties": False,
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["severity", "category", "message"],
                "additionalProperties": False,
                "properties": {
                    "block_id": {"type": "string"},
                    "severity": {"enum": ["fatal", "major", "minor"]},
                    "category": {"enum": REVIEW_CATEGORIES},
                    "message": {"type": "string", "minLength": 10},
                },
            },
        },
    },
}


# ---- 02-generate: the one giant generation call (Curator + Synthesizer +
# Instructional Designer in a single model call). Sub-schemas are reused
# verbatim (minus their $schema markers) so the contracts stay identical.
def _sub(schema: dict) -> dict:
    s = {k: v for k, v in schema.items() if k != "$schema"}
    return s


GENERATED = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["ground_truth", "lesson", "blocks"],
    "additionalProperties": False,
    "properties": {
        "ground_truth": _sub(GROUND_TRUTH),
        "lesson": _sub(LESSON),
        "blocks": _sub(BLOCKS),
    },
}

# ---- 04-repair: the content catcher. Replacement blocks use the SAME block
# item schema as BLOCKS; the orchestrator merges them into the current draft
# by id (a flagged block with no replacement is removed).
REPAIR = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["analysis", "blocks"],
    "additionalProperties": False,
    "properties": {
        "analysis": {"type": "string", "minLength": 20},
        "blocks": {
            "type": "array",
            "minItems": 1,
            "items": BLOCKS["properties"]["blocks"]["items"],
        },
    },
}

SCHEMAS = {
    "generated": GENERATED,
    "ground_truth": GROUND_TRUTH,
    "lesson": LESSON,
    "blocks": BLOCKS,
    "check_report": CHECK_REPORT,
    "repair": REPAIR,
    "interactive": INTERACTIVE,
    "fix_plan": FIX_PLAN,
    "review_report": REVIEW_REPORT,
    "review_call": REVIEW_CALL_REPORT,
}
