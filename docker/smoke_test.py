"""Container smoke test: prove the packaged environment is intact.

Runs as the image's default CMD and as the CI smoke check. It imports every
factory module, the pipeline entry point, and the heavy third-party deps the
pipeline needs, so a broken image fails here in seconds instead of mid-pipeline.

Run inside the image:  python docker/smoke_test.py
"""

from __future__ import annotations

import importlib
import sys

FACTORY_MODULES = [
    "factory.agents",
    "factory.artifacts",
    "factory.checks",
    "factory.config",
    "factory.errors",
    "factory.fixloop",
    "factory.ingest",
    "factory.interactive",
    "factory.link",
    "factory.lint",
    "factory.llm",
    "factory.locate",
    "factory.perf",
    "factory.render",
    "factory.retrieval",
    "factory.review",
    "factory.schemas",
    "factory.stages",
    "factory.textops",
]

# The single entry point (import-only: its __main__ guard keeps it from running).
ENTRYPOINT = "pipeline"

# Heavy deps that no import above pulls in directly, but the pipeline needs at
# runtime (retrieval, PDF ingest, perf gate).
THIRD_PARTY = [
    "requests",
    "jsonschema",
    "pdfplumber",
    "psutil",
    "playwright",
    "sentence_transformers",
]


def main() -> int:
    for name in FACTORY_MODULES + [ENTRYPOINT] + THIRD_PARTY:
        importlib.import_module(name)
        print(f"ok  import {name}")
    print("smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
