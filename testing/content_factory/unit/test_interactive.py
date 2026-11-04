"""Unit tests for 05-interactive: the Visual Builder must receive the
ground-truth facts its simulation must obey, the LIVE design doctrine +
examples + parsed palette, and lint violations must enter the retry
transcript instead of killing the run after the model call.
"""

import dataclasses
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from factory import interactive
from factory.artifacts import RunContext
from factory.config import load_config
from factory.llm import LLMClient
from testing.content_factory.unit._server_env import (
    install_server_env,
    release_server_env,
)

FIXTURES = REPO_ROOT / "testing" / "content_factory" / "mocks" / "fixtures"


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class StubLLM:
    """Captures what interactive hands to llm.call; returns the fixture sim."""

    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []
        self.kwargs: dict[str, Any] = {}

    def call(self, stage_id, messages, schema, schema_name, **kw):
        self.messages = messages
        self.kwargs = kw
        return load("05-interactive.json")


class TestInteractiveFacts(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        base = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
        base["paths"]["runs"] = str(self.tmp / "runs")
        (self.tmp / "config.json").write_text(json.dumps(base), encoding="utf-8")
        saved = install_server_env()
        try:
            # root must be the real repo: 06 injects the shipped doctrine,
            # examples and stylesheet from docs/frontend/ and frontend/.
            self.cfg = dataclasses.replace(
                load_config(self.tmp / "config.json"), root=REPO_ROOT
            )
        finally:
            release_server_env(saved)
        self.run_ctx = RunContext(
            self.cfg.repo_path(self.cfg.paths["runs"]), "t-interactive"
        )

    def _run(self, stub: StubLLM) -> dict[str, Any]:
        return interactive.run(
            self.cfg,
            self.run_ctx,
            cast(LLMClient, stub),
            load("blocks.json"),
            load("gt.json"),
        )

    def _messages(self, stub: StubLLM) -> tuple[str, str]:
        self._run(stub)
        user = next(m["content"] for m in stub.messages if m["role"] == "user")
        system = next(m["content"] for m in stub.messages if m["role"] == "system")
        return user, system

    def test_sim_prompt_carries_cited_claims_and_equations(self):
        # The fixture sim block b-06 cites claim-03 and claim-04: their exact
        # statements must be in the prompt; uncited claims must not flood it.
        stub = StubLLM()
        user, _ = self._messages(stub)
        gt = load("gt.json")
        cited = [c for c in gt["claims"] if c["id"] in ("claim-03", "claim-04")]
        uncited = next(c for c in gt["claims"] if c["id"] == "claim-01")
        self.assertTrue(cited)
        for c in cited:
            self.assertIn(c["statement"], user)
        self.assertNotIn(uncited["statement"], user)
        for e in gt["equations"]:
            self.assertIn(e["expression"], user)

    def test_prompt_pins_physics_and_legibility_contract(self):
        stub = StubLLM()
        user, system = self._messages(stub)
        self.assertIn("FACTS THE SIMULATION MUST OBEY", user)
        self.assertIn("PHYSICS CONTRACT", user)
        self.assertIn("Never invent physics", user)
        self.assertIn("canvas buffer is fixed 480x320", user)
        self.assertIn("Clean geometry on canvas too", user)
        self.assertIn("Never invent physics facts", system)

    def test_prompt_carries_live_doctrine_examples_and_palette(self):
        # The design context is injected, not held: the prompt must contain the
        # live doctrine document, every example the glob finds, and the exact
        # palette values parsed from zivon.css. The old hand-held token list
        # and the inert "Reference: <path>" line must be gone.
        stub = StubLLM()
        user, _ = self._messages(stub)
        self.assertIn("DESIGN DOCTRINE + EXAMPLES", user)
        doctrine = (REPO_ROOT / "docs" / "frontend" / "design-doctrine.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(doctrine[:400], user)  # the live document, not an excerpt
        self.assertIn(
            "=== design-doctrine-lesson-example.html ===", user
        )  # example content injected, not just named
        self.assertIn("#1F3A9E", user)  # pen-blue, parsed from the stylesheet
        self.assertIn("never copy their", user)  # the medium bridge
        self.assertNotIn("var(--ink), var(--paper), var(--graphite)", user)
        self.assertNotIn("Reference: ", user)

    def test_lint_violations_feed_the_retry_loop(self):
        stub = StubLLM()
        out = self._run(stub)  # {block_id: model output} - the sim is under "b-06"
        self.assertIn("extra_validator", stub.kwargs)
        validator = stub.kwargs["extra_validator"]
        # the fixture sim is lint-clean: no feedback needed
        self.assertEqual(validator(out["b-06"]), [])
        bad = json.loads(json.dumps(out["b-06"]))
        bad["files"]["page.js"] = (
            'ZivonSim.register("b-06", { init: function (ctx) { eval("1+1"); } });'
        )
        hits = validator(bad)
        self.assertTrue(any("eval" in h for h in hits), hits)
        empty = {"id": "b-06", "files": {"page.js": "   "}}
        self.assertTrue(any("non-empty" in h for h in validator(empty)))


if __name__ == "__main__":
    unittest.main()
