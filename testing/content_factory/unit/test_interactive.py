"""Unit tests for 05-interactive lint-feedback retry loop wiring.

Note: 05-interactive prompt wording checks were migrated to
`evals/checkers/prompt_contract_checks.py` (`EV-VIS-001`) per
`docs/specs/evals/migration-map.csv` row 21.
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
