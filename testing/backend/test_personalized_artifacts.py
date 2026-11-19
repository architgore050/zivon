"""PL3 artifact tests (backend/personalized/artifacts.py + the API-PL-13/14
routes + the D-PL-07 builder seam).

Layers per the test-authoring skill: pure-function unit tests for validation,
hashing and lint; an integration slice for the ensure_artifact pipeline with a
FakeBuilder at the model seam (no network, no key, no live model); and API
contract tests over the real app with SQLite in memory. The headless render
gate and the sandbox escape test are exercised by EV-PL-003; the browser-run
assertions live there (honest SKIP without Chromium), while this module owns
the deterministic contracts.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar
from unittest.mock import patch

from backend.personalized.artifact_prompt import (
    MAX_BUILD_ROUNDS,
    ArtifactDesignContext,
    LLMManagerArtifactBuilder,
)
from backend.personalized.artifacts import (
    MAX_CONTROLS,
    MAX_DOM_NODES,
    ArtifactBuildError,
    ArtifactQuotaError,
    ArtifactSpecError,
    ArtifactStore,
    compute_artifact_id,
    ensure_artifact,
    ensure_no_student_text,
    lint_artifact_html,
    normalize_fallback,
    validate_artifact_spec,
)
from backend.personalized.quota import QuotaCaps, QuotaService
from backend.personalized.store import PersonalizedStore
from db.engine import DatabaseEngine
from llm_manager import LLMConfig
from testing.backend.web_auth_support import PASSWORD, WebAuthSupport

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDENS = REPO_ROOT / "evals" / "goldens" / "personalized" / "artifacts"

# A lint-clean document (the EV-PL-003 golden) for pipeline tests.
GOLDEN_HTML = (GOLDENS / "good-concave-mirror.html").read_text(encoding="utf-8")

_CANARY_WEAKNESS = "PII_CANARY_7f3a why does the image flip"
_CANARY_INSTRUCTIONS = "PII_CANARY_9d2e always mention my school"

_CLAIMS = {
    "c-03": {
        "id": "c-03",
        "statement": "A concave mirror forms a real, inverted image when the "
        "object is beyond the focal point",
        "locator": "NCERT light chapter, reflection section",
    },
    "c-07": {
        "id": "c-07",
        "statement": "The mirror equation 1/v = 1/f - 1/u relates the object "
        "and image distances",
        "locator": "NCERT light chapter, mirror formula",
    },
}


def _spec() -> dict[str, Any]:
    return {
        "kind": "simulation",
        "title": "Concave mirror: move the object",
        "learning_goal": "See how the image moves as the object crosses the focus",
        "controls": [
            {
                "id": "u",
                "label": "Object distance (cm)",
                "min": 5,
                "max": 60,
                "step": 1,
                "initial": 30,
            }
        ],
        "cited_claim_ids": ["c-03", "c-07"],
        "why": "treats the image as always real",
    }


def _db() -> DatabaseEngine:
    return DatabaseEngine.from_url("sqlite:///:memory:", auto_migrate=True)


class FakeBuilder:
    """The model seam (data-and-api.md §6): records what it was given, returns
    what the test configures — no network, no key."""

    def __init__(
        self,
        html: str = GOLDEN_HTML,
        error: ArtifactBuildError | None = None,
    ) -> None:
        self.html = html
        self.error = error
        self.calls = 0
        self.seen_specs: list[dict[str, Any]] = []
        self.seen_claims: list[list[dict[str, Any]]] = []

    def build(
        self, spec: dict[str, Any], claims: list[dict[str, Any]]
    ) -> tuple[str, int, int | None, str | None]:
        self.calls += 1
        self.seen_specs.append(spec)
        self.seen_claims.append(claims)
        if self.error is not None:
            raise self.error
        return self.html, 0, 42, "fake-model-1"


class _PipelineHarness:
    """One SQLite engine with the migrations + a tiny quota, per test."""

    def __init__(self, caps: QuotaCaps | None = None) -> None:
        self.db = _db()
        self.db.execute(
            "INSERT INTO users (user_id, email, display_name) "
            "VALUES ('user-1', 'learner@example.com', 'Learner One')"
        )
        self.store = PersonalizedStore(self.db)
        self.session = self.store.create_session(
            user_id="user-1",
            chapter_id="class-10-light",
            class_level=10,
            title="Light · mirrors",
            weakness_text=_CANARY_WEAKNESS,
        )
        self.quota = QuotaService(
            self.db,
            caps
            or QuotaCaps(
                turns_per_user_per_day=40,
                turn_concurrency=2,
                sessions_per_user_per_day=5,
                artifacts_per_user_per_day=12,
                turns_global_per_day=1500,
                artifacts_global_per_day=300,
            ),
        )


def _ensure(harness: _PipelineHarness, builder: Any, **overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "db": harness.db,
        "quota": harness.quota,
        "user_id": "user-1",
        "session_id": harness.session["session_id"],
        "turn_index": 0,
        "raw_spec": _spec(),
        "available_claims": _CLAIMS,
        "forbidden_texts": [_CANARY_WEAKNESS, _CANARY_INSTRUCTIONS],
        "fallback": {"kind": "diagram", "svg": "<svg viewBox='0 0 2 2'></svg>"},
        "builder": builder,
        "doctrine_hash": "a" * 64,
    }
    kwargs.update(overrides)
    return ensure_artifact(**kwargs)


class ArtifactSpecValidationTest(unittest.TestCase):
    """§2 request contract: allow-listed fields, ranges, caps, grounding."""

    def test_valid_simulation_spec_returns_clean_spec(self) -> None:
        spec, weak = validate_artifact_spec(_spec(), available_claim_ids=set(_CLAIMS))
        self.assertFalse(weak)
        self.assertEqual(spec["kind"], "simulation")
        self.assertEqual(len(spec["controls"]), 1)
        self.assertEqual(spec["controls"][0]["id"], "u")

    def test_unexpected_field_is_rejected(self) -> None:
        smuggled = {**_spec(), "weakness_text": _CANARY_WEAKNESS}
        with self.assertRaises(ArtifactSpecError):
            validate_artifact_spec(smuggled)

    def test_unexpected_control_field_is_rejected(self) -> None:
        spec = _spec()
        spec["controls"][0]["value_note"] = "student text"
        with self.assertRaises(ArtifactSpecError):
            validate_artifact_spec(spec)

    def test_too_many_controls_rejected(self) -> None:
        spec = _spec()
        spec["controls"] = [
            {
                "id": f"c{i}",
                "label": f"Control {i}",
                "min": 0,
                "max": 1,
                "step": 1,
                "initial": 0,
            }
            for i in range(MAX_CONTROLS + 1)
        ]
        with self.assertRaises(ArtifactSpecError):
            validate_artifact_spec(spec)

    def test_diagram_with_controls_rejected(self) -> None:
        spec = _spec()
        spec["kind"] = "diagram"
        with self.assertRaises(ArtifactSpecError):
            validate_artifact_spec(spec)

    def test_diagram_without_controls_validates(self) -> None:
        spec = _spec()
        spec["kind"] = "diagram"
        spec["controls"] = []
        spec["cited_claim_ids"] = ["c-03"]
        clean, weak = validate_artifact_spec(spec, available_claim_ids={"c-03"})
        self.assertEqual(clean["kind"], "diagram")
        self.assertEqual(clean["controls"], [])
        self.assertFalse(weak)

    def test_control_ranges_validated(self) -> None:
        cases: list[dict[str, Any]] = [
            {"min": 5, "max": 5},  # min == max
            {"min": 10, "max": 5},  # min > max
            {"min": 5, "max": 60, "step": 0},  # zero step
            {"min": 5, "max": 60, "step": -1},  # negative step
            {"min": 5, "max": 60, "initial": 70},  # initial outside
            {"min": 5, "max": 60, "initial": 2},  # initial below
        ]
        for overrides in cases:
            spec = _spec()
            spec["controls"][0].update(overrides)
            with (
                self.subTest(overrides=overrides),
                self.assertRaises(ArtifactSpecError),
            ):
                validate_artifact_spec(spec)

    def test_control_id_pattern_enforced(self) -> None:
        for bad in ("U", "1u", "has space", "x" * 17, ""):
            spec = _spec()
            spec["controls"][0]["id"] = bad
            with (
                self.subTest(control_id=bad),
                self.assertRaises(ArtifactSpecError),
            ):
                validate_artifact_spec(spec)

    def test_unknown_claims_dropped_marks_weak_grounding(self) -> None:
        spec = _spec()
        spec["cited_claim_ids"] = ["c-99", "c-42"]
        clean, weak = validate_artifact_spec(spec, available_claim_ids=set(_CLAIMS))
        self.assertEqual(clean["cited_claim_ids"], [])
        self.assertTrue(weak)

    def test_title_and_goal_caps_enforced(self) -> None:
        spec = _spec()
        spec["title"] = "x" * 121
        with self.assertRaises(ArtifactSpecError):
            validate_artifact_spec(spec)
        spec = _spec()
        spec["learning_goal"] = "y" * 201
        with self.assertRaises(ArtifactSpecError):
            validate_artifact_spec(spec)

    def test_no_student_text_guard_rejects_quoting_spec(self) -> None:
        spec, _ = validate_artifact_spec(_spec(), available_claim_ids=set(_CLAIMS))
        quoting = {**spec, "why": f"the student said: {_CANARY_WEAKNESS}"}
        with self.assertRaises(ArtifactSpecError):
            ensure_no_student_text(quoting, [_CANARY_WEAKNESS])

    def test_no_student_text_guard_allows_clean_spec(self) -> None:
        spec, _ = validate_artifact_spec(_spec(), available_claim_ids=set(_CLAIMS))
        ensure_no_student_text(spec, [_CANARY_WEAKNESS, _CANARY_INSTRUCTIONS])


class ArtifactContentAddressingTest(unittest.TestCase):
    """§7 key formula: deterministic, `why`-excluded, version-pinned."""

    def test_same_spec_same_id(self) -> None:
        spec, _ = validate_artifact_spec(_spec())
        id_a, hash_a = compute_artifact_id(spec, doctrine_hash="a" * 64)
        id_b, hash_b = compute_artifact_id(spec, doctrine_hash="a" * 64)
        self.assertEqual(id_a, id_b)
        self.assertEqual(hash_a, hash_b)
        self.assertEqual(len(id_a), 32)
        self.assertEqual(len(hash_a), 64)

    def test_why_excluded_from_identity(self) -> None:
        spec, _ = validate_artifact_spec(_spec())
        with_why = {**spec, "why": "one label"}
        with_other = {**spec, "why": "a different label"}
        self.assertEqual(
            compute_artifact_id(with_why, doctrine_hash="a" * 64)[0],
            compute_artifact_id(with_other, doctrine_hash="a" * 64)[0],
        )

    def test_doctrine_change_invalidates_cache(self) -> None:
        spec, _ = validate_artifact_spec(_spec())
        self.assertNotEqual(
            compute_artifact_id(spec, doctrine_hash="a" * 64)[0],
            compute_artifact_id(spec, doctrine_hash="b" * 64)[0],
        )

    def test_prompt_version_change_invalidates_cache(self) -> None:
        spec, _ = validate_artifact_spec(_spec())
        self.assertNotEqual(
            compute_artifact_id(
                spec, prompt_version="pl-art-1", doctrine_hash="a" * 64
            )[0],
            compute_artifact_id(
                spec, prompt_version="pl-art-2", doctrine_hash="a" * 64
            )[0],
        )

    def test_lint_version_change_invalidates_cache(self) -> None:
        spec, _ = validate_artifact_spec(_spec())
        self.assertNotEqual(
            compute_artifact_id(
                spec, lint_version="pl-artifact-1", doctrine_hash="a" * 64
            )[0],
            compute_artifact_id(
                spec, lint_version="pl-artifact-2", doctrine_hash="a" * 64
            )[0],
        )


class ArtifactLintTest(unittest.TestCase):
    """§3 step 3: the hard lint. Every hit is a failure, never a warning."""

    def test_golden_artifact_passes_clean(self) -> None:
        self.assertEqual(lint_artifact_html(GOLDEN_HTML), [])

    def _defect_rules(self) -> dict[str, str]:
        return {
            "external-fetch": "LINT_NETWORK_FETCH",
            "eval": "LINT_EVAL",
            "localstorage": "LINT_STORAGE",
            "form": "LINT_FORM",
            "topnav-link": "LINT_ANCHOR",
            "oversized": "LINT_SIZE",
            "missing-label": "LINT_LABEL_MISSING",
        }

    def test_seeded_defects_fail_with_expected_rules(self) -> None:
        for name, rule in self._defect_rules().items():
            path = GOLDENS / "defects" / f"{name}.html"
            with self.subTest(defect=name):
                self.assertTrue(path.is_file(), f"{name}.html missing")
                rules = {
                    h.split("[")[-1].rstrip("]")
                    for h in lint_artifact_html(path.read_text(encoding="utf-8"))
                }
                self.assertIn(rule, rules)

    def _wrap(self, body: str) -> str:
        """A minimal otherwise-valid document carrying `body` as the script."""
        return (
            "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<style></style></head><body><main aria-labelledby='t'>"
            "<h1 id='t'>t</h1><p aria-live='polite'>x</p></main>"
            f"<script>{body}</script></body></html>"
        )

    def test_self_navigation_apis_rejected(self) -> None:
        for body in (
            "location.href = 'x';",
            "window.location = 'x';",
            "location.assign('x');",
            "location.replace('x');",
            "history.pushState({}, '', 'x');",
            "window.open('x');",
        ):
            with self.subTest(body=body):
                rules = self._rules(self._wrap(body))
                self.assertTrue(
                    {"LINT_SELFNAV", "LINT_POPUP"} & rules,
                    f"expected a self-nav/popup hit for: {body}",
                )

    def test_parent_access_beyond_harness_rejected(self) -> None:
        rules = self._rules(self._wrap("var t = window.parent.document.title;"))
        self.assertIn("LINT_PARENT", rules)
        rules = self._rules(self._wrap("window.top.postMessage('x', '*');"))
        self.assertIn("LINT_PARENT", rules)

    def test_foreign_postmessage_rejected(self) -> None:
        rules = self._rules(self._wrap("window.postMessage({a: 1}, '*');"))
        self.assertIn("LINT_POSTMESSAGE", rules)

    def test_harness_channel_allowed(self) -> None:
        doc = self._wrap(
            "window.parent.postMessage({source: 'zivon-artifact', v: 1,"
            " type: 'ready'}, '*');"
        )
        self.assertEqual(lint_artifact_html(doc), [])

    def test_storage_clipboard_fullscreen_notification_rejected(self) -> None:
        cases = {
            "localStorage.getItem('x');": "LINT_STORAGE",
            "document.cookie = 'x';": "LINT_STORAGE",
            "navigator.clipboard.readText();": "LINT_CLIPBOARD",
            "document.documentElement.requestFullscreen();": "LINT_FULLSCREEN",
            "new Notification('x');": "LINT_NOTIFICATION",
        }
        for body, rule in cases.items():
            with self.subTest(body=body):
                self.assertIn(rule, self._rules(self._wrap(body)))

    def test_html_attacks_rejected(self) -> None:
        cases = {
            "<meta http-equiv='refresh' content='1'>": "LINT_META_REFRESH",
            "<base href='/x/'>": "LINT_BASE",
            "<iframe src='x'></iframe>": "LINT_IFRAME",
            "<a href='javascript:void(0)'>x</a>": "LINT_JS_URL",
            "<img src='https://x.test/a.png'>": "LINT_EXTERNAL_URL",
            "<a href='data:text/html,x'>y</a>": "LINT_DATA_HTML",
            "<div onclick='x()'>y</div>": "LINT_ONHANDLER",
        }
        for snippet, rule in cases.items():
            with self.subTest(snippet=snippet):
                doc = GOLDEN_HTML.replace(
                    '<h1 id="art-title">Concave mirror: move the object</h1>',
                    '<h1 id="art-title">Concave mirror: move the object</h1>\n'
                    + snippet,
                    1,
                )
                self.assertIn(rule, self._rules(doc))

    def test_exactly_one_script_block(self) -> None:
        two_scripts = GOLDEN_HTML.replace(
            "</body>", "<script>var x = 1;</script></body>", 1
        )
        self.assertIn("LINT_SCRIPT_COUNT", self._rules(two_scripts))
        external = GOLDEN_HTML.replace(
            "</body>", "<script src='x.js'></script></body>", 1
        )
        self.assertIn("LINT_SCRIPT_SRC", self._rules(external))

    def test_dom_node_cap(self) -> None:
        padded = GOLDEN_HTML.replace(
            '<h1 id="art-title">Concave mirror: move the object</h1>',
            '<h1 id="art-title">Concave mirror: move the object</h1>'
            + ("<span>s</span>" * (MAX_DOM_NODES + 10)),
            1,
        )
        self.assertIn("LINT_DOM_NODES", self._rules(padded))

    def test_css_external_fetch_rejected(self) -> None:
        doc = GOLDEN_HTML.replace(
            "<style>",
            "<style>@import url('https://x.test/f.css');",
            1,
        )
        self.assertIn("LINT_CSS_IMPORT", self._rules(doc))

    def _rules(self, html: str) -> set[str]:
        return {h.split("[")[-1].rstrip("]") for h in lint_artifact_html(html)}


class ArtifactFallbackTest(unittest.TestCase):
    """§8: the stored fallback is always honest."""

    def test_safe_diagram_survives(self) -> None:
        out = normalize_fallback(
            {"kind": "diagram", "svg": "<svg viewBox='0 0 2 2'><circle r='1'/></svg>"}
        )
        self.assertEqual(out["kind"], "diagram")

    def test_unsafe_svg_downgrades_to_text(self) -> None:
        for svg in (
            "<svg><script>alert(1)</script></svg>",
            "<svg onload='x'></svg>",
            "<svg><a xlink:href='https://x.test'>y</a></svg>",
            "<svg><script>1</script></svg>",
            # Script schemes are not "external URLs", but the fallback is
            # injected raw into the app-origin page (server-side `| safe`),
            # so a click-activated scheme is a code-execution vector there.
            "<svg><a href='javascript:alert(1)'>x</a></svg>",
            "<svg><a xlink:href='JAVASCRIPT:alert(1)'>x</a></svg>",
            "<svg><a href='vbscript:msgbox(1)'>x</a></svg>",
            "<svg><a href='data:text/html,<script>1</script>'>x</a></svg>",
            # The factory diagram-svg rule's extra bans (style / embeds /
            # not starting with <svg) apply too — one source of truth.
            "<svg><style>*{fill:red}</style><circle r='1'/></svg>",
            "<svg><image href='x.png'/></svg>",
            "<div><svg><circle r='1'/></svg></div>",
        ):
            with self.subTest(svg=svg[:30]):
                self.assertEqual(
                    normalize_fallback({"kind": "diagram", "svg": svg})["kind"],
                    "text",
                )

    def test_text_fallback_passthrough(self) -> None:
        self.assertEqual(normalize_fallback({"kind": "text"}), {"kind": "text"})
        self.assertEqual(normalize_fallback(None), {"kind": "text"})


class ArtifactPipelineTest(unittest.TestCase):
    """`ensure_artifact` end to end with the FakeBuilder at the model seam."""

    def setUp(self) -> None:
        self.h = _PipelineHarness()

    def test_build_reaches_ready_with_quota_committed(self) -> None:
        builder = FakeBuilder()
        handle = _ensure(self.h, builder)
        self.assertEqual(handle.status, "ready")
        self.assertFalse(handle.cache_hit)
        self.assertEqual(handle.fallback["kind"], "diagram")
        row = ArtifactStore(self.h.db).get(handle.artifact_id)
        assert row is not None
        self.assertEqual(row["status"], "ready")
        self.assertEqual(row["model"], "fake-model-1")
        self.assertEqual(row["render_ms"], 42)
        usage = self.h.quota.get_usage("user-1")
        self.assertEqual(usage["artifacts"]["used"], 1)
        # The builder received the cited claims only — never student text.
        self.assertEqual([c["id"] for c in builder.seen_claims[0]], ["c-03", "c-07"])

    def test_cache_hit_costs_zero_model_calls_and_zero_quota(self) -> None:
        builder = FakeBuilder()
        first = _ensure(self.h, builder)
        usage_after_build = self.h.quota.get_usage("user-1")["artifacts"]["used"]
        second = _ensure(self.h, builder)
        self.assertEqual(builder.calls, 1)
        self.assertTrue(second.cache_hit)
        self.assertEqual(second.artifact_id, first.artifact_id)
        self.assertEqual(
            self.h.quota.get_usage("user-1")["artifacts"]["used"], usage_after_build
        )

    def test_lint_failure_marks_row_failed_and_commits_quota(self) -> None:
        dirty = GOLDEN_HTML.replace(
            "requestAnimationFrame(frame);",
            "eval('bad'); requestAnimationFrame(frame);",
            1,
        )
        builder = FakeBuilder(html=dirty)
        with self.assertRaises(ArtifactBuildError) as ctx:
            _ensure(self.h, builder)
        self.assertEqual(ctx.exception.failure_reason, "lint")
        row = ArtifactStore(self.h.db).get(self._last_row_id())
        assert row is not None
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["failure_reason"], "lint")
        self.assertEqual(self.h.quota.get_usage("user-1")["artifacts"]["used"], 1)
        self.assertEqual(ctx.exception.extra["fallback"]["kind"], "diagram")

    def _last_row_id(self) -> str:
        row = self.h.db.fetchone(
            "SELECT artifact_id FROM personalized_artifact ORDER BY created_at DESC LIMIT 1"
        )
        assert row is not None
        return str(row["artifact_id"])

    def test_route_failure_releases_quota_and_allows_rebuild(self) -> None:
        builder = FakeBuilder(error=ArtifactBuildError("route", "transport down"))
        with self.assertRaises(ArtifactBuildError) as ctx:
            _ensure(self.h, builder)
        self.assertEqual(ctx.exception.failure_reason, "route")
        self.assertEqual(self.h.quota.get_usage("user-1")["artifacts"]["used"], 0)
        # A transient route error is the one reason a rebuild is allowed.
        builder.error = None
        handle = _ensure(self.h, builder)
        self.assertEqual(handle.status, "ready")
        self.assertEqual(builder.calls, 2)

    def test_deterministic_failure_is_never_rebuilt(self) -> None:
        builder = FakeBuilder(error=ArtifactBuildError("lint", "nope", lint_hits=3))
        with self.assertRaises(ArtifactBuildError):
            _ensure(self.h, builder)
        calls = builder.calls
        handle = _ensure(self.h, builder)
        self.assertEqual(handle.status, "failed")
        self.assertEqual(handle.failure_reason, "lint")
        self.assertEqual(builder.calls, calls)

    def test_builder_missing_fails_closed_before_any_row(self) -> None:
        with self.assertRaises(ArtifactBuildError) as ctx:
            _ensure(self.h, None)
        self.assertEqual(ctx.exception.failure_reason, "route")
        count = self.h.db.fetchone("SELECT COUNT(*) AS c FROM personalized_artifact")
        assert count is not None
        self.assertEqual(int(count["c"]), 0)

    def test_quota_exhaustion_is_honest(self) -> None:
        harness = _PipelineHarness(
            caps=QuotaCaps(
                turns_per_user_per_day=40,
                turn_concurrency=2,
                sessions_per_user_per_day=5,
                artifacts_per_user_per_day=1,
                turns_global_per_day=1500,
                artifacts_global_per_day=300,
            )
        )
        _ensure(harness, FakeBuilder())
        other_spec = _spec()
        other_spec["title"] = "Convex mirror: move the object"
        with self.assertRaises(ArtifactQuotaError):
            _ensure(harness, FakeBuilder(), raw_spec=other_spec)

    def test_spec_rejection_writes_rejected_usage_and_no_row(self) -> None:
        with self.assertRaises(ArtifactSpecError):
            _ensure(self.h, FakeBuilder(), raw_spec={**_spec(), "kind": "video"})
        count = self.h.db.fetchone("SELECT COUNT(*) AS c FROM personalized_artifact")
        assert count is not None
        self.assertEqual(int(count["c"]), 0)
        usage = self.h.db.fetchone(
            "SELECT outcome FROM personalized_usage ORDER BY created_at DESC LIMIT 1"
        )
        assert usage is not None
        self.assertEqual(usage["outcome"], "rejected")

    def test_canary_never_reaches_builder_or_document(self) -> None:
        """DET-PL03-NO-STUDENT, pipeline level: the shared cache is
        cross-student, so the weakness text must be absent from everything."""
        builder = FakeBuilder()
        _ensure(self.h, builder)
        spec = builder.seen_specs[0]
        blob = f"{spec}{builder.seen_claims[0]}{builder.html}"
        self.assertNotIn(_CANARY_WEAKNESS, blob)
        self.assertNotIn(_CANARY_INSTRUCTIONS, blob)
        self.assertNotIn("PII_CANARY", str(builder.html))


class ArtifactStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.h = _PipelineHarness()
        self.store = ArtifactStore(self.h.db)

    def _ready_artifact(self) -> str:
        spec, _ = validate_artifact_spec(_spec())
        artifact_id, content_hash = compute_artifact_id(spec, doctrine_hash="a" * 64)
        self.store.create_pending(
            artifact_id=artifact_id,
            content_hash=content_hash,
            spec=spec,
            fallback={"kind": "text"},
            doctrine_hash="a" * 64,
        )
        self.store.mark_ready(artifact_id, html=GOLDEN_HTML, model="m", render_ms=5)
        return artifact_id

    def _reference(self, artifact_id: str, user_id: str = "user-1") -> None:
        session = self.h.store.create_session(
            user_id=user_id,
            chapter_id="class-10-light",
            class_level=10,
            title="Light · mirrors",
        )
        self.h.store.append_message(
            session_id=session["session_id"],
            role="tutor",
            kind="artifact_ref",
            payload={
                "artifact_id": artifact_id,
                "src": f"/v1/personalized/artifacts/{artifact_id}",
            },
        )

    def test_reference_check_is_owner_scoped(self) -> None:
        artifact_id = self._ready_artifact()
        self._reference(artifact_id, user_id="user-1")
        self.assertTrue(self.store.is_referenced_for_user(artifact_id, "user-1"))
        self.assertFalse(self.store.is_referenced_for_user(artifact_id, "user-2"))

    def test_touch_last_used_updates_the_purge_input(self) -> None:
        artifact_id = self._ready_artifact()
        before = ArtifactStore(self.h.db).get(artifact_id)
        assert before is not None
        self.store.touch_last_used(artifact_id)
        after = ArtifactStore(self.h.db).get(artifact_id)
        assert after is not None
        self.assertGreaterEqual(str(after["last_used_at"]), str(before["last_used_at"]))

    def test_purge_marks_referencing_messages_missing(self) -> None:
        artifact_id = self._ready_artifact()
        self._reference(artifact_id)
        self.assertTrue(self.store.purge(artifact_id))
        self.assertIsNone(self.store.get(artifact_id))
        msg = self.h.db.fetchone(
            "SELECT payload FROM personalized_message WHERE kind = 'artifact_ref' LIMIT 1"
        )
        assert msg is not None
        self.assertIn("artifact_missing", str(msg["payload"]))
        # Purging again is an honest no-op.
        self.assertFalse(self.store.purge(artifact_id))


class ArtifactApiTest(WebAuthSupport):
    """API-PL-13/14: auth, reference authorization, sandbox headers, 409s."""

    config_overrides: ClassVar[dict[str, Any]] = {
        "admin_token": "test-admin-token",
        "rate_limit_personalized_read_per_min": 500,
        "rate_limit_personalized_ip_per_min": 500,
    }

    def setUp(self) -> None:
        super().setUp()
        # The routes read the APP's engine: rows land in self.db so the
        # reference check sees them. The app is booted without a builder
        # seam value (fetch/status never build).
        self.db = self.app.state.db
        self.hstore = PersonalizedStore(self.db)
        self.store = ArtifactStore(self.db)
        self.app.state.personalized_artifact_builder = None

    def _ready_artifact(
        self, *, user_id: str = "user-1", reference: bool = True
    ) -> str:
        spec, _ = validate_artifact_spec(_spec())
        artifact_id, content_hash = compute_artifact_id(spec, doctrine_hash="a" * 64)
        self.store.create_pending(
            artifact_id=artifact_id,
            content_hash=content_hash,
            spec=spec,
            fallback={"kind": "text"},
            doctrine_hash="a" * 64,
        )
        if reference:
            session = self.hstore.create_session(
                user_id=self._current_user_id(),
                chapter_id="class-10-light",
                class_level=10,
                title="Light · mirrors",
            )
            self.hstore.append_message(
                session_id=session["session_id"],
                role="tutor",
                kind="artifact_ref",
                payload={
                    "artifact_id": artifact_id,
                    "src": f"/v1/personalized/artifacts/{artifact_id}",
                },
            )
        self.store.mark_ready(artifact_id, html=GOLDEN_HTML, model="m", render_ms=5)
        return artifact_id

    def _current_user_id(self) -> str:
        row = self.db.fetchone("SELECT user_id FROM users ORDER BY created_at LIMIT 1")
        assert row is not None
        return str(row["user_id"])

    def _pending_artifact(
        self, *, status: str = "pending", reason: str | None = None
    ) -> str:
        spec, _ = validate_artifact_spec(_spec())
        artifact_id, content_hash = compute_artifact_id(spec, doctrine_hash="a" * 64)
        self.store.create_pending(
            artifact_id=artifact_id,
            content_hash=content_hash,
            spec=spec,
            fallback={"kind": "text"},
            doctrine_hash="a" * 64,
        )
        if status == "failed":
            assert reason is not None
            self.store.mark_failed(artifact_id, failure_reason=reason)
        return artifact_id

    def test_guest_is_401(self) -> None:
        artifact_id = self._ready_artifact(reference=False)
        self.assertEqual(
            self.client.get(f"/v1/personalized/artifacts/{artifact_id}").status_code,
            401,
        )
        self.assertEqual(
            self.client.get(
                f"/v1/personalized/artifacts/{artifact_id}/status"
            ).status_code,
            401,
        )

    def test_unreferenced_artifact_is_404_for_its_owner(self) -> None:
        self.register_via_api()
        artifact_id = self._ready_artifact(reference=False)
        self.assertEqual(
            self.client.get(f"/v1/personalized/artifacts/{artifact_id}").status_code,
            404,
        )

    def test_referenced_artifact_serves_with_sandbox_headers(self) -> None:
        self.register_via_api()
        artifact_id = self._ready_artifact()
        response = self.client.get(f"/v1/personalized/artifacts/{artifact_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/html; charset=utf-8")
        csp = response.headers["content-security-policy"]
        self.assertIn("sandbox allow-scripts", csp)
        self.assertIn("default-src 'none'", csp)
        self.assertIn("connect-src 'none'", csp)
        self.assertIn("frame-ancestors 'self'", csp)
        self.assertIn("form-action 'none'", csp)
        self.assertIn("base-uri 'none'", csp)
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        self.assertEqual(
            response.headers["cache-control"], "private, max-age=86400, immutable"
        )
        self.assertIn("noindex", response.headers["x-robots-tag"])
        self.assertEqual(
            response.headers["cross-origin-resource-policy"], "same-origin"
        )
        self.assertEqual(response.text, GOLDEN_HTML)

    def test_never_allow_same_origin_in_the_csp(self) -> None:
        self.register_via_api()
        artifact_id = self._ready_artifact()
        response = self.client.get(f"/v1/personalized/artifacts/{artifact_id}")
        self.assertNotIn(
            "allow-same-origin", response.headers["content-security-policy"]
        )

    def test_pending_artifact_answers_409_with_status(self) -> None:
        self.register_via_api()
        pending_id = self._pending_artifact()
        session = self.hstore.create_session(
            user_id=self._current_user_id(),
            chapter_id="class-10-light",
            class_level=10,
            title="t",
        )
        self.hstore.append_message(
            session_id=session["session_id"],
            role="tutor",
            kind="artifact_ref",
            payload={"artifact_id": pending_id, "src": f"/x/{pending_id}"},
        )
        response = self.client.get(f"/v1/personalized/artifacts/{pending_id}")
        self.assertEqual(response.status_code, 409)
        body = response.json()
        self.assertEqual(body["status"], "pending")
        self.assertEqual(body["code"], "E-CONFLICT")

    def test_failed_artifact_answers_409_with_failure_reason(self) -> None:
        self.register_via_api()
        failed_id = self._pending_artifact(status="failed", reason="lint")
        session = self.hstore.create_session(
            user_id=self._current_user_id(),
            chapter_id="class-10-light",
            class_level=10,
            title="t",
        )
        self.hstore.append_message(
            session_id=session["session_id"],
            role="tutor",
            kind="artifact_ref",
            payload={"artifact_id": failed_id, "src": f"/x/{failed_id}"},
        )
        response = self.client.get(f"/v1/personalized/artifacts/{failed_id}")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["failure_reason"], "lint")

    def test_status_endpoint_reports_state_without_html(self) -> None:
        self.register_via_api()
        artifact_id = self._ready_artifact()
        response = self.client.get(f"/v1/personalized/artifacts/{artifact_id}/status")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ready")
        self.assertEqual(body["kind"], "simulation")
        self.assertNotIn("html", body)
        # The poll flow's contract with the viewer (data-and-api.md §4.8: the
        # src is the only URL the viewer uses; no client-side construction):
        # a ready response carries the server-issued src and never the HTML.
        self.assertEqual(body["src"], f"/v1/personalized/artifacts/{artifact_id}")

    def test_status_pending_payload_has_no_src(self) -> None:
        self.register_via_api()
        pending_id = self._pending_artifact()
        session = self.hstore.create_session(
            user_id=self._current_user_id(),
            chapter_id="class-10-light",
            class_level=10,
            title="t",
        )
        self.hstore.append_message(
            session_id=session["session_id"],
            role="tutor",
            kind="artifact_ref",
            payload={"artifact_id": pending_id, "src": f"/x/{pending_id}"},
        )
        response = self.client.get(f"/v1/personalized/artifacts/{pending_id}/status")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "pending")
        self.assertNotIn("src", body)
        self.assertNotIn("html", body)

    def test_serving_touches_last_used(self) -> None:
        self.register_via_api()
        artifact_id = self._ready_artifact()
        before = self.store.get(artifact_id)
        assert before is not None
        self.client.get(f"/v1/personalized/artifacts/{artifact_id}")
        after = self.store.get(artifact_id)
        assert after is not None
        self.assertGreaterEqual(str(after["last_used_at"]), str(before["last_used_at"]))

    def test_other_users_reference_is_404(self) -> None:
        """DET-PL05-ARTIFACT-REF: the shared cache never becomes a proxy."""
        self.register_via_api()
        artifact_id = self._ready_artifact()
        guest = type(self.client)(app=self.app, base_url="https://testserver")
        guest.post(
            "/v1/auth/register",
            json={"email": "other@example.com", "password": PASSWORD},
        )
        self.assertEqual(
            guest.get(f"/v1/personalized/artifacts/{artifact_id}").status_code, 404
        )
        self.assertEqual(
            guest.get(f"/v1/personalized/artifacts/{artifact_id}/status").status_code,
            404,
        )

    def test_admin_token_can_fetch_for_inspection(self) -> None:
        artifact_id = self._ready_artifact(reference=False)
        response = self.client.get(
            f"/v1/personalized/artifacts/{artifact_id}",
            headers={"X-Admin-Token": "test-admin-token"},
        )
        self.assertEqual(response.status_code, 200)

    def test_unknown_artifact_id_is_404(self) -> None:
        self.register_via_api()
        self.assertEqual(
            self.client.get("/v1/personalized/artifacts/deadbeef00").status_code, 404
        )


def _golden_payload() -> str:
    return json.dumps({"html": GOLDEN_HTML})


def _dirty_payload() -> str:
    dirty = GOLDEN_HTML.replace(
        "requestAnimationFrame(frame);",
        "eval('bad'); requestAnimationFrame(frame);",
        1,
    )
    return json.dumps({"html": dirty})


class _FakeLLMManager:
    """The llm_manager seam: scripted per-call responses, no network.

    The real `run_validation_rounds` loop runs unchanged above it, so the
    engine's lint-in-retry contract is exercised for real."""

    responses: ClassVar[list[str]] = []
    transcripts: ClassVar[list[list[dict[str, str]]]] = []

    @classmethod
    def script(cls, responses: list[str]) -> None:
        cls.responses = responses
        cls.transcripts = []

    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    def complete(
        self, transcript: list[dict[str, str]], *, temperature: float | None = None
    ) -> Any:
        del temperature
        _FakeLLMManager.transcripts.append([dict(m) for m in transcript])
        idx = min(
            len(_FakeLLMManager.transcripts) - 1, len(_FakeLLMManager.responses) - 1
        )
        return SimpleNamespace(
            text=_FakeLLMManager.responses[idx],
            finish_reason=None,
            model="fake-model-9",
        )


class ArtifactBuilderEngineTest(unittest.TestCase):
    """`LLMManagerArtifactBuilder.build` — lint-in-retry over the real
    `run_validation_rounds`, the exhaustion → `lint` mapping, and the
    single-emission-point telemetry contract (the builder seam itself emits
    only `personalized.artifact.retry`)."""

    def _engine(self) -> LLMManagerArtifactBuilder:
        return LLMManagerArtifactBuilder(
            LLMConfig(base_url="http://127.0.0.1:9", model="fake", api_key="unused"),
            ArtifactDesignContext(
                doctrine_block="", palette_block="", doctrine_hash="h"
            ),
            render_gate=None,  # the headless gate is EV-PL-003's job
        )

    def test_clean_first_round_builds_without_builder_events(self) -> None:
        _FakeLLMManager.script([_golden_payload()])
        engine = self._engine()
        with (
            patch("backend.personalized.artifact_prompt.LLMManager", _FakeLLMManager),
            patch("backend.personalized.artifact_prompt.log_event") as events,
        ):
            html, lint_hits, render_ms, model = engine.build(_spec(), [])
        self.assertEqual(html, GOLDEN_HTML)
        self.assertEqual(lint_hits, 0)
        self.assertIsNone(render_ms)  # no render gate wired → NULL, recorded
        self.assertEqual(model, "fake-model-9")
        self.assertEqual(len(_FakeLLMManager.transcripts), 1)
        # One emission point: ensure_artifact owns requested/ready/failed.
        events.assert_not_called()

    def test_lint_violation_is_fed_back_and_second_round_builds(self) -> None:
        _FakeLLMManager.script([_dirty_payload(), _golden_payload()])
        engine = self._engine()
        with (
            patch("backend.personalized.artifact_prompt.LLMManager", _FakeLLMManager),
            patch("backend.personalized.artifact_prompt.log_event") as events,
        ):
            html, lint_hits, _, model = engine.build(_spec(), [])
        self.assertEqual(html, GOLDEN_HTML)
        self.assertEqual(lint_hits, 0)
        self.assertEqual(model, "fake-model-9")
        self.assertEqual(len(_FakeLLMManager.transcripts), 2)
        feedback = _FakeLLMManager.transcripts[1][-1]
        self.assertEqual(feedback["role"], "user")
        self.assertIn("eval() is forbidden", feedback["content"])
        # The rejected round is observable exactly once, as the retry event.
        self.assertEqual(events.call_count, 1)
        name, kwargs = events.call_args[0][0], events.call_args[0][1]
        self.assertEqual(name, "personalized.artifact.retry")
        self.assertEqual(kwargs["reason_code"], "lint")
        self.assertEqual(kwargs["round"], 1)

    def test_exhausted_rebuilds_map_to_a_lint_failure(self) -> None:
        _FakeLLMManager.script([_dirty_payload()])
        engine = self._engine()
        with (
            patch("backend.personalized.artifact_prompt.LLMManager", _FakeLLMManager),
            self.assertRaises(ArtifactBuildError) as ctx,
        ):
            engine.build(_spec(), [])
        self.assertEqual(ctx.exception.failure_reason, "lint")
        self.assertGreaterEqual(ctx.exception.lint_hits, 1)
        # §3.2: the first build plus at most 2 rebuilds.
        self.assertEqual(len(_FakeLLMManager.transcripts), MAX_BUILD_ROUNDS)


if __name__ == "__main__":
    unittest.main()
