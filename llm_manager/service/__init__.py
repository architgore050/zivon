"""llm_manager.service: the model-call node.

A tiny FastAPI app wrapping LLMManager, shipped as its own image
(Dockerfile.llm-manager) and deployed as an isolated K8s Deployment + Service
(k8s/16-llm-manager.yaml). It speaks plain OpenAI chat-completions, so any
consumer (the factory Job today, a translator tomorrow) points its
ZIVON_BASE_URL at this node's Service and talks to ONE abstracted model
endpoint; the node is the only caller of the actual inference server (via the
dev inference router in container/cluster setups).

The service imports nothing from factory/ (a unit test guards this).
"""

from __future__ import annotations

from .app import create_app

app = create_app()

__all__ = ["app", "create_app"]
