"""Unit tests for the PL5 eval checkers (`EV-PL-004`/`EV-PL-005`).

Two layers:

1. **Registration and drift** — the cards load, their check ids match the
   contract in `docs/specs/personalized-learning/evals.md`, and every check
   passes key-free on the shipped goldens (the full sweep lives in
   `test_checkers.py`; the count pin is there).
2. **Fault detection** — the mutation proofs: a tampered golden, a weakened
   save-time screen, a merged system/personal message, and a softened
   precedence each turn the matching checker fatal. A checker that cannot
   fail is not a checker (test-authoring rule 7).
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from evals.checkers import run_deterministic_check
from evals.checkers.personalized_checks import (
    check_injection_precedence,
    check_instructions_contact_screen,
    check_instructions_normalization,
    check_no_answer_key_in_payload,
    check_no_paywall,
    check_quota_race,
    check_safe_next_only,
    check_safety_parity,
    check_saved_chat_privacy,
    check_security_headers,
)
from evals.config import EvalConfig
from evals.models import load_all_cards

REPO_ROOT = Path(__file__).resolve().parents[2]

PL5_CHECK_IDS = {
    "EV-PL-004": (
        "DET-PL04-NORMALIZE",
        "DET-PL04-PII",
        "DET-PL04-KEY",
        "DET-PL04-INJECT",
        "DET-PL04-PARITY",
        "DET-PL04-SAVE-PRIVACY",
    ),
    "EV-PL-005": (
        "DET-PL05-QUOTA",
        "DET-PL05-RATE",
        "DET-PL05-CSRF",
        "DET-PL05-IDOR",
        "DET-PL05-ARTIFACT-REF",
        "DET-PL05-DELETE",
        "DET-PL05-EXPORT",
        "DET-PL05-LOGS",
        "DET-PL05-HEADERS",
        "DET-PL05-NO-PAYWALL",
        "DET-PL05-NEXT",
        "DET-PL05-SECRETS",
    ),
}


class CardRegistration(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = EvalConfig.from_env({})
        self.cards = load_all_cards(self.cfg.cards_dir)

    def test_pl5_cards_load_with_the_contracted_check_ids(self) -> None:
        for card_id, expected_ids in PL5_CHECK_IDS.items():
            card = self.cards[card_id]
            with self.subTest(card=card_id):
                self.assertEqual(
                    tuple(chk.id for chk in card.deterministic_checks),
                    expected_ids,
                )
                self.assertEqual(card.llm_judge, None)
                self.assertIn("smoke", card.suites)
                self.assertEqual(card.cost_budget["smoke_model_calls"], 0)

    def test_pl5_stages_are_in_the_closed_enum(self) -> None:
        self.assertEqual(self.cards["EV-PL-004"].stage, "PL1-preferences")
        self.assertEqual(self.cards["EV-PL-005"].stage, "PL1-quota")

    def test_pl5_cards_run_green_key_free_on_shipped_goldens(self) -> None:
        for card_id in ("EV-PL-004", "EV-PL-005"):
            card = self.cards[card_id]
            for chk in card.deterministic_checks:
                ctx: dict[str, Any] = {}
                issues = run_deterministic_check(chk.entrypoint, self.cfg, card, ctx)
                blocking = [i for i in issues if i.severity in ("fatal", "major")]
                self.assertEqual(
                    blocking,
                    [],
                    f"{card_id}/{chk.id} reported blocking issues: {blocking}",
                )
                self.assertNotIn(chk.id, ctx.get("skipped_checks", {}))

    def test_fixture_corpus_shape(self) -> None:
        fixtures = json.loads(
            (self.cfg.goldens_dir / "personalized/quota/scenarios.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(len(fixtures["scenarios"]), 6)
        instruction_count = len(
            list(
                (self.cfg.goldens_dir / "personalized/instructions").glob("INS-*.json")
            )
        )
        self.assertEqual(instruction_count, 15)


def _tampered_goldens_cfg(mutator) -> EvalConfig:
    """A config whose goldens_dir holds a mutated copy of the PL goldens."""
    tmp = tempfile.mkdtemp()
    goldens = Path(tmp) / "goldens"
    shutil.copytree(REPO_ROOT / "evals" / "goldens", goldens)
    mutator(goldens)
    cfg = EvalConfig.from_env({"ZIVON_EVAL_GOLDENS_DIR": str(goldens)})
    cfg.__dict__["_tmp"] = tmp  # keep the dir alive for the assertion
    return cfg


class FaultDetection(unittest.TestCase):
    """Mutations that must turn the matching checker red."""

    def setUp(self) -> None:
        self.cards = load_all_cards(EvalConfig.from_env({}).cards_dir)

    def test_wrong_fixture_outcome_turns_normalize_fatal(self) -> None:
        def mutate(goldens: Path) -> None:
            path = goldens / "personalized/instructions/INS-06-contact_details.json"
            fixture = json.loads(path.read_text(encoding="utf-8"))
            fixture["expected_outcome"] = "accept"
            path.write_text(json.dumps(fixture), encoding="utf-8")

        cfg = _tampered_goldens_cfg(mutate)
        issues = check_instructions_normalization(cfg, self.cards["EV-PL-004"], {})
        self.assertTrue(
            any("INS-06" in i.message for i in issues),
            f"a tampered fixture outcome must be caught: {issues}",
        )

    def test_contact_fixture_marked_system_instruction_turns_pii_fatal(self) -> None:
        def mutate(goldens: Path) -> None:
            path = goldens / "personalized/instructions/INS-06-contact_details.json"
            fixture = json.loads(path.read_text(encoding="utf-8"))
            fixture["expected_reason"] = "system_instruction"
            path.write_text(json.dumps(fixture), encoding="utf-8")

        cfg = _tampered_goldens_cfg(mutate)
        issues = check_instructions_contact_screen(cfg, self.cards["EV-PL-004"], {})
        # The tamper removes the only contact_details fixture, so the checker
        # reports the corpus gap (fatal) — either way the drift is caught.
        self.assertTrue(
            issues and all(i.severity == "fatal" for i in issues),
            f"a wrong privacy reason must be caught: {issues}",
        )

    def test_missing_instruction_corpus_is_a_skip_not_a_pass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = EvalConfig.from_env({"ZIVON_EVAL_GOLDENS_DIR": td})
            context: dict[str, Any] = {}
            issues = check_instructions_normalization(
                cfg, self.cards["EV-PL-004"], context
            )
            self.assertEqual(issues, [])
            self.assertIn("DET-PL04-NORMALIZE", context["skipped_checks"])

    def test_weakened_save_screen_is_caught_by_the_pii_checker(self) -> None:
        """Mutation: a re-implementation that truncates instead of rejecting."""
        from backend.personalized import personalization as pz

        original = pz.validate_instructions

        def weak_validate(text: str) -> str:
            normalized = pz.normalize_instructions(text)
            if len(normalized) > pz.MAX_INSTRUCTION_CHARS:
                raise pz.PreferencesRejected("too_long")
            return normalized  # contact/system screens silently dropped

        try:
            pz.validate_instructions = weak_validate  # type: ignore[assignment]
            issues = check_instructions_contact_screen(
                EvalConfig.from_env({}), self.cards["EV-PL-004"], {}
            )
        finally:
            pz.validate_instructions = original  # type: ignore[assignment]
        self.assertTrue(
            any("contact-detail" in i.message for i in issues),
            f"a screen that stops rejecting contact details must fail the "
            f"checker: {issues}",
        )

    def test_merged_personal_block_into_the_safety_message_is_caught(self) -> None:
        """Mutation: prompt assembly that concatenates the personal block into
        the safety system message (the §5.2 precedence break)."""
        from backend.personalized import prompts as pl_prompts

        original = pl_prompts.teach_messages

        def merged_teach(**kwargs: Any) -> list[dict[str, str]]:
            messages = original(**kwargs)
            instructions = kwargs.get("personal_instructions")
            if instructions and len(messages) >= 3:
                messages[0] = dict(messages[0])
                messages[0]["content"] += "\n" + messages[1]["content"]
                messages.pop(1)
            return messages

        try:
            pl_prompts.teach_messages = merged_teach  # type: ignore[assignment]
            issues = check_injection_precedence(
                EvalConfig.from_env({}), self.cards["EV-PL-004"], {}
            )
        finally:
            pl_prompts.teach_messages = original  # type: ignore[assignment]
        self.assertTrue(
            any("second system message" in i.message for i in issues),
            f"a merged personal block must be caught: {issues[:3]}",
        )

    def test_weakened_parity_is_caught(self) -> None:
        """Mutation: a teach prompt that drops a safety-core sentence."""
        from backend.personalized import personalization as pz
        from backend.personalized import prompts as pl_prompts

        original = pl_prompts.TEACH_SYSTEM
        dropped = pz.SAFETY_CORE[0]
        try:
            pl_prompts.TEACH_SYSTEM = original.replace(dropped, "[weaked away]")
            issues = check_safety_parity(
                EvalConfig.from_env({}), self.cards["EV-PL-004"], {}
            )
        finally:
            pl_prompts.TEACH_SYSTEM = original
        self.assertTrue(
            issues, "a teach prompt missing a safety-core sentence must fail parity"
        )

    def test_saved_chat_export_leak_is_caught(self) -> None:
        """Mutation: an export serializer that re-includes the answer_key."""
        from backend.personalized.store import PersonalizedStore

        original = PersonalizedStore.export_session

        def leaky_export(self_store: PersonalizedStore, user_id: str, sid: str):
            payload = original(self_store, user_id, sid)
            if payload is not None:
                payload["messages"][0]["answer_key"] = "B"
            return payload

        try:
            PersonalizedStore.export_session = leaky_export  # type: ignore[assignment]
            issues = check_saved_chat_privacy(
                EvalConfig.from_env({}), self.cards["EV-PL-004"], {}
            )
        finally:
            PersonalizedStore.export_session = original  # type: ignore[assignment]
        self.assertTrue(
            any("key" in i.message for i in issues),
            f"an export leaking the key must be caught: {issues}",
        )

    def test_quota_scenario_drift_is_caught(self) -> None:
        def mutate(goldens: Path) -> None:
            path = goldens / "personalized/quota/scenarios.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            for scenario in payload["scenarios"]:
                if scenario["scenario_id"] == "user_exhausted":
                    scenario["expected"]["reason"] = "global_turn_cap"
            path.write_text(json.dumps(payload), encoding="utf-8")

        cfg = _tampered_goldens_cfg(mutate)
        issues = check_quota_race(cfg, self.cards["EV-PL-005"], {})
        self.assertTrue(
            any("user-exhausted" in i.message for i in issues),
            f"a drifted golden expectation must be caught: {issues}",
        )

    def test_missing_quota_golden_is_a_skip_not_a_pass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = EvalConfig.from_env({"ZIVON_EVAL_GOLDENS_DIR": td})
            context: dict[str, Any] = {}
            issues = check_quota_race(cfg, self.cards["EV-PL-005"], context)
            self.assertEqual(issues, [])
            self.assertIn("DET-PL05-QUOTA", context["skipped_checks"])

    def test_answer_key_leak_into_client_payloads_is_caught(self) -> None:
        """Mutation: a message serializer that re-includes the server-side
        `answer_key` column in client-bound rows. The rebindings below are the
        deliberate mutations, hence the targeted type ignores."""
        from backend.personalized.store import PersonalizedStore

        original = PersonalizedStore._message_out

        def leaky_out(row: dict[str, Any]) -> dict[str, Any]:
            payload = original(row)
            payload["answer_key"] = row.get("answer_key")
            return payload

        PersonalizedStore._message_out = staticmethod(leaky_out)  # type: ignore[method-assign,misc]
        try:
            issues = check_no_answer_key_in_payload(
                EvalConfig.from_env({}), self.cards["EV-PL-005"], {}
            )
        finally:
            # `_message_out` is a staticmethod: restore it AS a staticmethod,
            # otherwise the plain function binds as an instance method and
            # bleeds into later tests.
            PersonalizedStore._message_out = staticmethod(original)  # type: ignore[method-assign,misc]
        self.assertTrue(
            any("persisted client payload" in i.message for i in issues),
            f"a serializer carrying the key must be caught: {issues}",
        )

    def test_no_paywall_catches_a_new_banned_table(self) -> None:
        """Mutation: register a plan-shaped table name."""
        import db.schema as db_schema

        original = db_schema.ALL_TABLES
        try:
            db_schema.ALL_TABLES = (*original, "subscription_plan")  # type: ignore[misc]
            issues = check_no_paywall(
                EvalConfig.from_env({}), self.cards["EV-PL-005"], {}
            )
        finally:
            db_schema.ALL_TABLES = original  # type: ignore[misc]
        self.assertTrue(
            any("subscription_plan" in i.message for i in issues),
            f"a paywall table must be caught: {issues}",
        )

    def test_no_paywall_catches_an_upgrade_route_on_the_json_api(self) -> None:
        """Mutation: a personalized JSON route grows a `/v1/upgrade` path."""
        with tempfile.TemporaryDirectory() as td:
            fake_repo = Path(td)
            route_dir = fake_repo / "backend" / "personalized"
            route_dir.mkdir(parents=True)
            (route_dir / "router_paywall_probe.py").write_text(
                '@router.post("/v1/personalized/upgrade")\n',
                encoding="utf-8",
            )
            cfg = dataclasses.replace(EvalConfig.from_env({}), repo_root=fake_repo)
            issues = check_no_paywall(cfg, self.cards["EV-PL-005"], {})
        self.assertTrue(
            any("upgrade" in i.message for i in issues),
            f"a paywall-shaped JSON route must be caught: {issues}",
        )

    def test_no_paywall_catches_upgrade_copy_on_the_web_surface(self) -> None:
        """Mutation: the PL4 HTML route module grows upgrade copy."""
        with tempfile.TemporaryDirectory() as td:
            fake_repo = Path(td)
            routes = fake_repo / "web" / "routes"
            routes.mkdir(parents=True)
            (routes / "personalized.py").write_text(
                '# probe\nHUB_NOTE = "Upgrade to Pro for more turns"\n',
                encoding="utf-8",
            )
            cfg = dataclasses.replace(EvalConfig.from_env({}), repo_root=fake_repo)
            issues = check_no_paywall(cfg, self.cards["EV-PL-005"], {})
        self.assertTrue(
            any("upgrade to pro" in i.message for i in issues),
            f"paywall copy on the web surface must be caught: {issues}",
        )

    def test_dropped_shell_header_is_caught_by_the_headers_checker(self) -> None:
        """Mutation: the shared shell `page_headers()` stops returning
        `no-store` (PL4 landed the hub/session surfaces the checker grades)."""
        import web.render as web_render

        original = web_render.page_headers

        def headers_without_cache_control() -> dict[str, str]:
            headers = dict(original())
            headers.pop("Cache-Control")
            return headers

        try:
            web_render.page_headers = (  # type: ignore[assignment]
                headers_without_cache_control
            )
            issues = check_security_headers(
                EvalConfig.from_env({}), self.cards["EV-PL-005"], {}
            )
        finally:
            web_render.page_headers = original  # type: ignore[assignment]
        self.assertTrue(
            any("no-store" in i.message for i in issues),
            f"a shell page losing no-store must fail the checker: {issues[:3]}",
        )

    def test_lost_sse_buffering_contract_is_caught(self) -> None:
        """Mutation: the SSE response headers drop `X-Accel-Buffering`."""
        from backend.personalized import turn_router

        original = turn_router.SSE_HEADERS
        weakened = {
            key: value for key, value in original.items() if key != "X-Accel-Buffering"
        }
        try:
            turn_router.SSE_HEADERS = weakened  # type: ignore[assignment]
            issues = check_security_headers(
                EvalConfig.from_env({}), self.cards["EV-PL-005"], {}
            )
        finally:
            turn_router.SSE_HEADERS = original  # type: ignore[assignment]
        self.assertTrue(
            any("no-buffering" in i.message for i in issues),
            f"a drifted SSE contract must fail the checker: {issues}",
        )

    def test_next_guard_losing_the_backslash_rejection_is_caught(self) -> None:
        """Mutation: `safe_next_path` stops rejecting backslashes — browsers
        read `/\\host` as `//host`, so the checker's hostile probe must turn
        fatal even though the returned string carries no `//`."""
        import backend.auth.service as auth_service

        original = auth_service.safe_next_path

        def backslash_permitting(value: object, default: str = "/app") -> str:
            candidate = str(value or "").strip()
            if not candidate.startswith("/") or candidate.startswith("//"):
                return default
            return candidate  # the backslash/control rejection is "removed"

        try:
            auth_service.safe_next_path = (  # type: ignore[assignment]
                backslash_permitting
            )
            issues = check_safe_next_only(
                EvalConfig.from_env({}), self.cards["EV-PL-005"], {}
            )
        finally:
            auth_service.safe_next_path = original  # type: ignore[assignment]
        self.assertTrue(
            any("hostile next" in i.message for i in issues),
            f"a next guard that lets `/\\\\host` through must fail the "
            f"checker: {issues}",
        )


if __name__ == "__main__":
    unittest.main()
