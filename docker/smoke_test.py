"""Container smoke test: prove the packaged environment is intact.

Runs as the image's default CMD and as the CI smoke check. It imports every
factory module plus the heavy third-party dependencies the pipeline needs, so
a broken image fails here in seconds instead of mid-pipeline.

Run inside the image:  python docker/smoke_test.py
"""

from __future__ import annotations

import importlib
import sys

FACTORY_MODULES = [
    "factory.config",
    "factory.errors",
    "factory.artifacts",
    "factory.llm",
    "factory.schemas",
    "factory.textops",
]

# Heavy deps that no module import above pulls in directly, but the pipeline
# needs at runtime (retrieval, PDF ingest, perf gate).
THIRD_PARTY = [
    "requests",
    "jsonschema",
    "pypdf",
    "psutil",
    "playwright",
    "sentence_transformers",
]


def main() -> int:
    for name in FACTORY_MODULES + THIRD_PARTY:
        importlib.import_module(name)
        print(f"ok  import {name}")
    print("smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
