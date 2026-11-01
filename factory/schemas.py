"""JSON Schemas for every stage handoff.

These are the frozen contracts between stages (v1, 2026-11-01). Design notes:
- Block payloads always live under "spec" (AGENTS.md format), which resolves
  the AGENTS.md-vs-TIMELINE.md contradiction in favour of AGENTS.md.
- Every factual block carries citations that must reference ground-truth claim
  ids; the 05-check stage enforces this in code, not vibes.
- Schemas are deliberately loose about prose (strings) and strict about
  structure, ids and enums, so a small local model can satisfy them reliably.
"""

from __future__ import annotations

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
    "required": ["topic", "summary", "claims", "key_terms", "equations", "misconceptions", "uncertain"],
    "additionalProperties": False,
    "properties": {
        "topic": {"type": "string", "minLength": 2},
        "summary": {"type": "string", "minLength": 40},
        "claims": {
            "type": "array", "minItems": 4,
            "items": {
                "type": "object",
                "required": ["id", "statement", "citations"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "pattern": "^claim-[0-9]{2,3}$"},
                    "statement": {"type": "string", "minLength": 15},
                    "citations": {"type": "array", "minItems": 1, "items": {
                        "type": "object", "required": ["source_id", "locator"],
                        "additionalProperties": False,
                        "properties": {"source_id": {"type": "string"}, "locator": {"type": "string"}},
                    }},
                },
            },
        },
        "key_terms": {
            "type": "array", "minItems": 2,
            "items": {
                "type": "object", "required": ["term", "definition", "citations"],
                "additionalProperties": False,
                "properties": {
                    "term": {"type": "string"},
                    "definition": {"type": "string", "minLength": 10},
                    "citations": {"type": "array", "minItems": 1, "items": {
                        "type": "object", "required": ["source_id", "locator"],
                        "additionalProperties": False,
                        "properties": {"source_id": {"type": "string"}, "locator": {"type": "string"}},
                    }},
                },
            },
        },
        "equations": {
            "type": "array",
            "items": {
                "type": "object", "required": ["id", "expression", "description", "citations"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "pattern": "^eq-[0-9]{2,3}$"},
                    "expression": {"type": "string", "minLength": 2},
                    "description": {"type": "string", "minLength": 10},
                    "citations": {"type": "array", "minItems": 1, "items": {
                        "type": "object", "required": ["source_id", "locator"],
                        "additionalProperties": False,
                        "properties": {"source_id": {"type": "string"}, "locator": {"type": "string"}},
                    }},
                },
            },
        },
        "misconceptions": {
            "type": "array",
            "items": {
                "type": "object", "required": ["id", "wrong_belief", "correction", "citations"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "pattern": "^mis-[0-9]{2,3}$"},
                    "wrong_belief": {"type": "string", "minLength": 10},
                    "correction": {"type": "string", "minLength": 10},
                    "citations": {"type": "array", "minItems": 1, "items": {
                        "type": "object", "required": ["source_id", "locator"],
                        "additionalProperties": False,
                        "properties": {"source_id": {"type": "string"}, "locator": {"type": "string"}},
                    }},
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
        "objectives": {"type": "array", "minItems": 2, "items": {"type": "string", "minLength": 15}},
        "sections": {
            "type": "array", "minItems": 2,
            "items": {
                "type": "object", "required": ["id", "title", "paragraphs"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "pattern": "^sec-[0-9]{2}$"},
                    "title": {"type": "string", "minLength": 3},
                    "paragraphs": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 40}},
                },
            },
        },
        "glossary": {
            "type": "array", "minItems": 2,
            "items": {
                "type": "object", "required": ["term", "definition"],
                "additionalProperties": False,
                "properties": {"term": {"type": "string"}, "definition": {"type": "string", "minLength": 10}},
            },
        },
    },
}

BLOCK_TYPES = ["text", "worked_example", "check", "reveal", "diagram", "simulation"]

BLOCKS = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["blocks"],
    "additionalProperties": False,
    "properties": {
        "blocks": {
            "type": "array", "minItems": 4, "maxItems": 18,
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
                "type": "object", "required": ["severity", "message"],
                "additionalProperties": False,
                "properties": {
                    "block_id": {"type": "string"},
                    "severity": {"enum": ["fatal", "major", "minor"]},
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
            "type": "object", "required": [], "additionalProperties": {"type": "string"},
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
            "type": "object", "additionalProperties": {"type": "string"},
            "description": "Full replacement content for the topic-local files being fixed.",
        },
    },
}

REVIEW_REPORT = CHECK_REPORT  # same shape: verdict + issues

SCHEMAS = {
    "ground_truth": GROUND_TRUTH,
    "lesson": LESSON,
    "blocks": BLOCKS,
    "check_report": CHECK_REPORT,
    "interactive": INTERACTIVE,
    "fix_plan": FIX_PLAN,
    "review_report": REVIEW_REPORT,
}
