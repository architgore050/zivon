"""Container entry point: `python -m llm_manager.service`.

Loads LLMConfig.from_env() LOUDLY before uvicorn starts (a misconfigured node
must fail at boot, not on its first request), then serves the app. The listen
address/port are environment knobs per AGENTS.md (no hardcoded ports):
LLM_MANAGER_HOST (default 0.0.0.0 - the node exists to be reached) and
LLM_MANAGER_PORT (default 8000, matching the K8s Service targetPort).
"""

from __future__ import annotations

import os

import uvicorn

from ..config import LLMConfig
from .app import create_app


def main() -> None:
    LLMConfig.from_env()  # tripwire: refuse to boot without server config
    app = create_app()
    uvicorn.run(
        app,
        host=os.environ.get("LLM_MANAGER_HOST", "0.0.0.0"),
        port=int(os.environ.get("LLM_MANAGER_PORT", "8000")),
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
