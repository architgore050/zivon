"""Container smoke test: prove the packaged environment is intact.

Runs as the image's default CMD and as the CI smoke check. It imports every
factory module, the pipeline entry point, and the heavy third-party deps the
pipeline needs, so a broken image fails here in seconds instead of mid-pipeline.

Run inside the image:  python docker/smoke_test.py
"""

from __future__ import annotations

import importlib
import importlib.util
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
    "factory.ledger",
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
    "factory.tm_store",
    "factory.transcheck",
    "factory.translate",
    "factory.transrepair",
]

# The shared model-call module: standalone by contract (imports nothing from
# factory/), used in-process by the factory adapter and shipped standalone in
# the llm-manager image (Dockerfile.llm-manager).
LLM_MANAGER_MODULES = [
    "llm_manager",
    "llm_manager.client",
    "llm_manager.config",
    "llm_manager.errors",
    "llm_manager.validation",
]

# The service node lives in the same package but needs fastapi; import it
# when the dependency is present so the factory image (which ships fastapi
# for CI) proves the node module imports too.
if importlib.util.find_spec("fastapi") is not None:
    LLM_MANAGER_MODULES.append("llm_manager.service")

# The single entry point (import-only: its __main__ guard keeps it from running).
ENTRYPOINT = "pipeline"

# Heavy deps that no import above pulls in directly, but the pipeline needs at
# runtime (retrieval, PDF ingest, perf gate) - plus the llm_manager stack.
THIRD_PARTY = [
    "requests",
    "jsonschema",
    "httpx",
    "langchain_openai",
    "pdfplumber",
    "psutil",
    "playwright",
    "sentence_transformers",
]


def main() -> int:
    for name in FACTORY_MODULES + LLM_MANAGER_MODULES + [ENTRYPOINT] + THIRD_PARTY:
        importlib.import_module(name)
        print(f"ok  import {name}")
    print("smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
