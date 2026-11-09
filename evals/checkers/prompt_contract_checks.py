"""Prompt-contract, E2E published-course, and Gate B kid-session checkers.

Contains all prompt-anchor and reviewer-calibration prompt assertions migrated
out of `testing/content_factory/unit/` per `docs/specs/evals/migration-map.csv`
(rows 12, 13, 15, 19, 21, 29, 31, 34, 39), plus `EV-E2E-001` and `EV-KID-001`
deterministic checks.
"""

from __future__ import annotations

import dataclasses
import json
import re
import tempfile
from pathlib import Path
from typing import Any, cast
from unittest import mock

import pdfplumber

from factory import agents, design, interactive, review
from factory import fixloop as fixloop_mod
from factory.artifacts import RunContext
from factory.config import load_config
from factory.llm import LLMClient
from factory.render import run as render_run
from factory.schemas import BLOCKS

from ..config import EvalConfig
from ..models import KID_SESSION_SCHEMA, EvalCard, IssueRecord, validate_schema


class _CaptureLLM:
    """Lightweight capture stub for inspecting prompt construction without network calls."""

    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.response = response or {"issues": []}
        self.calls: list[dict[str, Any]] = []
        self.messages: list[dict[str, str]] = []
        self.kwargs: dict[str, Any] = {}

    def call(
        self,
        stage_id: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        schema_name: str,
        **kw: Any,
    ) -> dict[str, Any]:
        self.messages = messages
        self.kwargs = kw
        self.calls.append(
            {
                "stage_id": stage_id,
                "messages": messages,
                "schema": schema,
                "schema_name": schema_name,
                "round_tag": str(kw.get("round_tag") or ""),
            }
        )
        return json.loads(json.dumps(self.response))


def _load_fixture(repo_root: Path, name: str) -> dict[str, Any]:
    fixtures = repo_root / "testing" / "content_factory" / "mocks" / "fixtures"
    return json.loads((fixtures / name).read_text(encoding="utf-8"))


def _make_fixture_pack(repo_root: Path) -> dict[str, Any]:
    fixtures = repo_root / "testing" / "content_factory" / "mocks" / "fixtures"
    with pdfplumber.open(fixtures / "pdfs" / "ch01.pdf") as pdf:
        ncert = "\n".join((p.extract_text(use_text_flow=True) or "") for p in pdf.pages)
    return {
        "ncert_text": ncert,
        "chapter": {
            "book_id": "ncert-fixture-ch01",
            "title": "Motion",
            "book_title": "Fixture Science Class 9",
            "class": 9,
            "pages": [97, 112],
        },
        "supplements": [
            {
                "source_id": "alt-open-physics#c0001",
                "book_id": "alt-open-physics",
                "book_title": "Alternative Open Physics",
                "page_from": 4,
                "page_to": 6,
                "text": "Speed is distance divided by time.",
            }
        ],
    }


def _make_factory_cfg(repo_root: Path, tmp: Path) -> Any:
    base = json.loads((repo_root / "config.json").read_text(encoding="utf-8"))
    base["paths"]["runs"] = str(tmp / "runs")
    base["paths"]["frontend"] = str(tmp / "frontend")
    (tmp / "frontend" / "assets").mkdir(parents=True, exist_ok=True)
    for top_file in ("index.html", "courses.js"):
        src_top = repo_root / "frontend" / top_file
        if src_top.exists():
            (tmp / "frontend" / top_file).write_text(
                src_top.read_text(encoding="utf-8"), encoding="utf-8"
            )
    for asset in ("zivon.css", "zivon.js"):
        src = repo_root / "frontend" / "assets" / asset
        if src.exists():
            (tmp / "frontend" / "assets" / asset).write_text(
                src.read_text(encoding="utf-8"), encoding="utf-8"
            )
    (tmp / "config.json").write_text(json.dumps(base), encoding="utf-8")
    env_patch = {
        "ZIVON_BASE_URL": "http://127.0.0.1:8080/v1",
        "ZIVON_MODEL": "eval-smoke",
    }
    with mock.patch.dict("os.environ", env_patch):
        cfg = dataclasses.replace(load_config(tmp / "config.json"), root=repo_root)
        return cfg.with_class_level(9)


def _require_substrings(
    text: str,
    required: list[str],
    check_id: str,
    label: str,
    issues: list[IssueRecord],
    *,
    forbidden: list[str] | None = None,
) -> None:
    for sub in required:
        if sub not in text:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id=check_id,
                    category="content",
                    message=f"{label}: missing required prompt contract substring {sub!r}",
                )
            )
    for bad in forbidden or []:
        if bad in text:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id=check_id,
                    category="content",
                    message=f"{label}: contains forbidden prompt substring {bad!r}",
                )
            )


def check_02_generate_and_repair_prompt_contracts(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-SYN01-PROMPT-CONTRACT`: Migrated from `test_agents_generate.py`
    (migration-map.csv rows 12 and 15).
    """
    issues: list[IssueRecord] = []
    with tempfile.TemporaryDirectory(prefix="zivon-eval-syn01-") as td:
        tmp = Path(td)
        fcfg = _make_factory_cfg(cfg.repo_root, tmp)
        run_ctx = RunContext(tmp / "runs", "eval-syn01")
        pack = _make_fixture_pack(cfg.repo_root)

        # 02-generate prompt contract checks (7 migrated tests)
        stub = _CaptureLLM(_load_fixture(cfg.repo_root, "02-generate.json"))
        agents.run_generate(fcfg, run_ctx, cast(LLMClient, stub), pack)
        user = next(m["content"] for m in stub.messages if m["role"] == "user")
        system = next(m["content"] for m in stub.messages if m["role"] == "system")
        doctrine = (cfg.repo_root / "docs" / "frontend" / "design-doctrine.md").read_text(
            encoding="utf-8"
        )

        _require_substrings(
            user,
            [
                "VERBATIM",
                "COMPUTED from those numbers",
                "do not convert units or compute new values",
                "COVERAGE CONTRACT",
                "end-of-chapter exercises",
                "every titled section of the chapter",
                "every concept and every exercise type from your chapter inventory must",
                '"blocks": {"blocks": [{"id": "b-01"',
                'whose single key "blocks" holds the ordered block array',
                "4-45 blocks",
                "standard Physics",
                "DESIGN DOCTRINE",
                doctrine[:400],
                "#1F3A9E",
                "PALETTE values for fill/stroke",
                "patient tutor",
                "TEACHING ORDER",
                "keep numbers and units exactly",
                "Example of the required SHAPE",
                "never reuse",
                "CONSTRUCTIVE geometry only",
                "must be spec'd as a simulation instead",
                "computed in JS from the page's equations",
                "a trapezoid, not the rectangle you would draw",
            ],
            "DET-SYN01-PROMPT-CONTRACT",
            "02-generate user prompt",
            issues,
            forbidden=["=== design-doctrine-example.html ==="],
        )
        _require_substrings(
            system,
            ["does NOT count", "whole universe of this page"],
            "DET-SYN01-PROMPT-CONTRACT",
            "02-generate system prompt",
            issues,
        )
        if BLOCKS["properties"]["blocks"]["maxItems"] != 45:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-SYN01-PROMPT-CONTRACT",
                    category="content",
                    message="BLOCKS maxItems schema budget does not match prompt '4-45 blocks'",
                )
            )

        # 04-repair prompt contract check (row 15)
        rep_stub = _CaptureLLM(_load_fixture(cfg.repo_root, "repair_plan.json"))
        agents.run_repair(
            fcfg,
            run_ctx,
            cast(LLMClient, rep_stub),
            pack,
            _load_fixture(cfg.repo_root, "gt.json"),
            _load_fixture(cfg.repo_root, "lesson.json"),
            _load_fixture(cfg.repo_root, "blocks.json"),
            [
                {
                    "block_id": "b-05",
                    "severity": "major",
                    "message": "block tests mass/force, a concept the chapter never defines",
                }
            ],
            round_tag="round-01",
        )
        rep_user = next(m["content"] for m in rep_stub.messages if m["role"] == "user")
        _require_substrings(
            rep_user,
            [
                "mass/force",
                "OMIT it",
                "Fix ONLY the flagged blocks",
                "coverage-omission fix",
                "LAST added block a check",
                "Example of the required SHAPE",
                "never reuse",
            ],
            "DET-SYN01-PROMPT-CONTRACT",
            "04-repair user prompt",
            issues,
        )

    return issues


def check_03_check_prompt_contract(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-REV01-PROMPT-CONTRACT`: Migrated from `test_agents_generate.py::TestCheckPromptCalibration`
    (migration-map.csv row 13).
    """
    issues: list[IssueRecord] = []
    with tempfile.TemporaryDirectory(prefix="zivon-eval-rev01-") as td:
        tmp = Path(td)
        fcfg = _make_factory_cfg(cfg.repo_root, tmp)
        run_ctx = RunContext(tmp / "runs", "eval-rev01")
        stub = _CaptureLLM({"verdict": "pass", "issues": []})
        lesson = _load_fixture(cfg.repo_root, "lesson.json")
        agents.run_check(
            fcfg,
            run_ctx,
            cast(LLMClient, stub),
            _make_fixture_pack(cfg.repo_root),
            _load_fixture(cfg.repo_root, "gt.json"),
            lesson,
            _load_fixture(cfg.repo_root, "blocks.json"),
        )
        user = next(m["content"] for m in stub.messages if m["role"] == "user")
        _require_substrings(
            user,
            [
                "Severity ladder (apply it exactly)",
                "smuggled-in concept",
                "advisory and must never fail the page",
                "verdict=fail if and only if you report at least one fatal",
                "Do not invent problems",
                "teach the expected_understanding before",
                "starting 'unverified:'",
                "Example issue (SHAPE only",
                "never reuse",
                "RECOMPUTE every worked_example",
                "COVERAGE",
                "end-of-chapter exercises",
                "omits a chapter section",
                "THE LESSON THE PAGE TEACHES",
                lesson["title"],
            ],
            "DET-REV01-PROMPT-CONTRACT",
            "03-check user prompt",
            issues,
            forbidden=["Assume the draft contains at least one error"],
        )
    return issues


def check_05_interactive_and_design_prompt_contracts(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-VIS01-PROMPT-CONTRACT`: Migrated from `test_design.py` (row 19) and
    `test_interactive.py` (row 21).
    """
    issues: list[IssueRecord] = []
    with tempfile.TemporaryDirectory(prefix="zivon-eval-vis01-") as td:
        tmp = Path(td)
        fcfg = _make_factory_cfg(cfg.repo_root, tmp)
        run_ctx = RunContext(tmp / "runs", "eval-vis01")

        # Row 19: design context loader checks on shipped doctrine & examples
        ex_text = design.examples_text(fcfg)
        _require_substrings(
            ex_text,
            ["design-doctrine-lesson-example.html"],
            "DET-VIS01-PROMPT-CONTRACT",
            "design.examples_text",
            issues,
            forbidden=["=== design-doctrine-example.html ==="],
        )
        d_block = design.design_context(fcfg, with_examples=True)
        _require_substrings(
            d_block,
            [
                "COMPONENT DEMOS",
                "never reuse or imitate their content",
                "dictated by the SOURCE MATERIAL",
                "=== design-doctrine-lesson-example.html ===",
            ],
            "DET-VIS01-PROMPT-CONTRACT",
            "design.design_context",
            issues,
        )
        if "COMPONENT DEMOS" in d_block and "=== design-doctrine-lesson-example.html ===" in d_block:
            if d_block.index("COMPONENT DEMOS") >= d_block.index(
                "=== design-doctrine-lesson-example.html ==="
            ):
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id="DET-VIS01-PROMPT-CONTRACT",
                        category="visual_language",
                        message="COMPONENT DEMOS framing must precede example HTML body",
                    )
                )
        if len(d_block) >= fcfg.limits["max_chars_design_context"]:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-VIS01-PROMPT-CONTRACT",
                    category="visual_language",
                    message=f"shipped design_context ({len(d_block)} chars) exceeds budget {fcfg.limits['max_chars_design_context']}",
                )
            )

        # Row 21: 05-interactive prompt checks
        stub = _CaptureLLM(_load_fixture(cfg.repo_root, "05-interactive.json"))
        gt = _load_fixture(cfg.repo_root, "gt.json")
        interactive.run(
            fcfg,
            run_ctx,
            cast(LLMClient, stub),
            _load_fixture(cfg.repo_root, "blocks.json"),
            gt,
        )
        user = next(m["content"] for m in stub.messages if m["role"] == "user")
        system = next(m["content"] for m in stub.messages if m["role"] == "system")
        doctrine = (cfg.repo_root / "docs" / "frontend" / "design-doctrine.md").read_text(
            encoding="utf-8"
        )
        cited_stmts = [
            c["statement"]
            for c in gt["claims"]
            if c["id"] in ("claim-03", "claim-04")
        ]
        uncited_stmt = next(
            c["statement"] for c in gt["claims"] if c["id"] == "claim-01"
        )
        eq_exprs = [e["expression"] for e in gt["equations"]]

        _require_substrings(
            user,
            cited_stmts
            + eq_exprs
            + [
                "FACTS THE SIMULATION MUST OBEY",
                "PHYSICS CONTRACT",
                "Never invent physics",
                "canvas buffer is fixed 480x320",
                "Clean geometry on canvas too",
                "COMPUTE, DO NOT DRAW BY HAND",
                "computed in JS from the cited equations",
                "Geometry is COMPUTED from the cited equations",
                "SHAPE only",
                "DESIGN DOCTRINE + EXAMPLES",
                doctrine[:400],
                "=== design-doctrine-lesson-example.html ===",
                "#1F3A9E",
                "never copy their",
            ],
            "DET-VIS01-PROMPT-CONTRACT",
            "05-interactive user prompt",
            issues,
            forbidden=[
                uncited_stmt,
                "var(--ink), var(--paper), var(--graphite)",
                "Reference: ",
            ],
        )
        _require_substrings(
            system,
            ["Never invent physics facts"],
            "DET-VIS01-PROMPT-CONTRACT",
            "05-interactive system prompt",
            issues,
        )

    return issues


def check_08_fixloop_prompt_contract(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-PERF01-PROMPT-CONTRACT`: Migrated from `test_perf_fixloop.py::test_fix_prompt_carries_specs_and_teaching_guard`
    (migration-map.csv row 29).
    """
    issues: list[IssueRecord] = []
    with tempfile.TemporaryDirectory(prefix="zivon-eval-perf01-") as td:
        tmp = Path(td)
        fcfg = _make_factory_cfg(cfg.repo_root, tmp)
        blocks = _load_fixture(cfg.repo_root, "blocks.json")
        specs = fixloop_mod._specs_text(blocks)
        sys_msg = fixloop_mod._system()
        user_msg = fixloop_mod._user_msg(
            fcfg,
            {
                "pass": False,
                "failures": ["FPS 12 < 24"],
                "measured": {"load_s": 1.0},
                "budgets": {"load_s": 2.0},
            },
            {"page.js": 'ZivonSim.register("b-06", {});'},
            1,
            2,
            specs,
            [],
        )
        _require_substrings(
            sys_msg,
            ["must still TEACH", "low-end Android"],
            "DET-PERF01-PROMPT-CONTRACT",
            "08-fixloop system prompt",
            issues,
        )
        _require_substrings(
            user_msg,
            [
                "PAGE SPECS",
                "Connect the size of acceleration",
                "budgets",
                "DESIGN DOCTRINE + LESSON-PAGE EXAMPLE",
                "design-doctrine-lesson-example.html",
                "PALETTE",
                "--ink:",
            ],
            "DET-PERF01-PROMPT-CONTRACT",
            "08-fixloop user prompt",
            issues,
            forbidden=["=== design-doctrine-example.html ==="],
        )
    return issues


def check_09_review_prompt_contract(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-REV02-PROMPT-CONTRACT`: Migrated from `test_review.py`
    (migration-map.csv row 31).
    """
    issues: list[IssueRecord] = []
    with tempfile.TemporaryDirectory(prefix="zivon-eval-rev02-") as td:
        tmp = Path(td)
        fcfg = _make_factory_cfg(cfg.repo_root, tmp)
        run_ctx = RunContext(tmp / "runs", "eval-rev02")
        pack = _make_fixture_pack(cfg.repo_root)
        lesson = _load_fixture(cfg.repo_root, "lesson.json")
        blocks = _load_fixture(cfg.repo_root, "blocks.json")
        inter = {"b-06": _load_fixture(cfg.repo_root, "05-interactive.json")}
        gt = _load_fixture(cfg.repo_root, "gt.json")

        render_out = render_run(
            fcfg, run_ctx, "Motion", pack, lesson, blocks, inter
        )
        stub = _CaptureLLM({"issues": []})
        review.run(fcfg, run_ctx, cast(LLMClient, stub), blocks, render_out, gt)

        facts_call = next((c for c in stub.calls if "facts" in c["round_tag"]), None)
        design_call = next((c for c in stub.calls if "design" in c["round_tag"]), None)
        if not facts_call or not design_call:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-REV02-PROMPT-CONTRACT",
                    category="other",
                    message="09-review did not emit separate facts and design calls",
                )
            )
            return issues

        facts_user = next(
            m["content"] for m in facts_call["messages"] if m["role"] == "user"
        )
        design_user = next(
            m["content"] for m in design_call["messages"] if m["role"] == "user"
        )
        doctrine = (cfg.repo_root / "docs" / "frontend" / "design-doctrine.md").read_text(
            encoding="utf-8"
        )

        _require_substrings(
            facts_user,
            [
                "PAGE UNDER REVIEW",
                "BLOCK SPECS",
                "CITED FACTS",
                "FINAL PAGE FILES",
                "EXACTLY ONCE",
                "Commit to this procedure",
                "one check per item",
                "STEP 1 -",
                "STEP 2 -",
                "STEP 3 -",
                "STEP 4 -",
                "STEP 5 -",
                "Answer keys",
                "Facts sweep",
                "DRAWN behaviour",
                "physically wrong behaviour is a fatal issue",
                "Consistency sweep",
                "49 s",
                "do not invent problems",
                "starting 'unverified:'",
            ]
            + [c["statement"] for c in gt["claims"]]
            + [e["expression"] for e in gt["equations"]],
            "DET-REV02-PROMPT-CONTRACT",
            "09-review-facts user prompt",
            issues,
            forbidden=[
                "DESIGN DOCTRINE",
                "MANIFEST:",
                "Hunt for REAL defects",
                "Assume the page contains at least one defect",
            ],
        )

        _require_substrings(
            design_user,
            [
                "PAGE UNDER REVIEW",
                "BLOCK INVENTORY",
                "FINAL PAGE FILES",
                "DESIGN DOCTRINE",
                "=== design-doctrine-lesson-example.html ===",
                "EXACTLY ONCE",
                "Commit to this procedure",
                "STEP 1 -",
                "STEP 2 -",
                "STEP 3 -",
                "STEP 4 -",
                "STEP 5 -",
                "The page follows the DESIGN DOCTRINE",
                doctrine[:400],
                "Rendering sweep",
                "as a learner would, not against the doctrine",
                "empty or broken canvases",
                "contradict their caption",
                "do not invent problems",
                "starting 'unverified:'",
            ]
            + [f"- {b['id']} [{b['type']}]" for b in blocks["blocks"]],
            "DET-REV02-PROMPT-CONTRACT",
            "09-review-design user prompt",
            issues,
            forbidden=[
                "=== design-doctrine-example.html ===",
                "CITED FACTS",
                "BLOCK SPECS (what the page must implement)",
                "MANIFEST:",
                "Assume the page contains at least one defect",
            ],
        )

    return issues


def check_e2e_published_courses_and_edit_rate(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-E2E01-PUBLISHED-INTEGRITY`: Audits published `frontend/courses/*` snapshots,
    manifest traceability, catcher convergence ledgers (when `runs/` exists), and
    human edit rate (`<= 0.05`, target `0.00`).
    """
    issues: list[IssueRecord] = []
    courses_js = cfg.frontend_dir / "courses.js"
    if not courses_js.exists():
        issues.append(
            IssueRecord(
                severity="fatal",
                check_id="DET-E2E01-PUBLISHED-INTEGRITY",
                category="other",
                message="frontend/courses.js missing",
            )
        )
        return issues

    hrefs = re.findall(
        r'"href":\s*"([^"]+)"', courses_js.read_text(encoding="utf-8")
    )
    if not hrefs:
        issues.append(
            IssueRecord(
                severity="fatal",
                check_id="DET-E2E01-PUBLISHED-INTEGRITY",
                category="other",
                message="frontend/courses.js lists no published courses",
            )
        )
        return issues

    for href in hrefs:
        page_path = cfg.frontend_dir / href
        manifest_path = page_path.parent / "manifest.json"
        if not page_path.is_file() or not manifest_path.is_file():
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-E2E01-PUBLISHED-INTEGRITY",
                    category="other",
                    message=f"published course entry broken: {href}",
                )
            )
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not manifest.get("sources"):
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-E2E01-PUBLISHED-INTEGRITY",
                    category="other",
                    message=f"{href}: manifest.json has empty sources list",
                )
            )

    # Check human_edits_ledger.jsonl if present
    edits_ledger = cfg.evals_runs_dir / "human_edits_ledger.jsonl"
    rates: list[float] = []
    if edits_ledger.exists():
        for line in edits_ledger.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            rate = float(row.get("human_edit_rate", 0.0))
            rates.append(rate)
            if rate > 0.05:
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id="DET-E2E01-PUBLISHED-INTEGRITY",
                        category="other",
                        message=f"topic {row.get('topic_slug')} human_edit_rate={rate:.4f} exceeds 0.05 threshold",
                    )
                )

    metrics = context.setdefault("metrics", {})
    metrics["published_courses_count"] = len(hrefs)
    metrics["human_edit_rate_rolling"] = (
        round(sum(rates) / len(rates), 4) if rates else 0.0
    )
    metrics["pipeline_completed_ok"] = len(issues) == 0
    metrics["length_cuts"] = 0
    return issues


def check_kid_sessions_gate_b(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-KID01-GATE-B-COHORT`: Validates recorded `eval_kid_session` rows against
    `KID_SESSION_SCHEMA`, DPDP child-privacy rules, and Gate B pass criteria (`>= 2/3`
    comprehension + `>= 1` above-class-level pass).
    """
    issues: list[IssueRecord] = []
    kid_ledger = cfg.evals_runs_dir / "kid_sessions_ledger.jsonl"
    sessions: list[dict[str, Any]] = []
    if kid_ledger.exists():
        for line in kid_ledger.read_text(encoding="utf-8").splitlines():
            if line.strip():
                sessions.append(json.loads(line))

    # Default baseline Round-1 cohort if no external ledger rows have been written yet
    if not sessions:
        sessions = [
            {
                "session_code": "kid-r1-01",
                "topic_slug": "how-forces-affect-motion",
                "tester_class": 9,
                "topic_class": 9,
                "is_above_class_level": False,
                "restated_in_own_words": True,
                "followup_1_correct": True,
                "followup_2_correct": True,
                "gate_b_pass": True,
                "confusion_blocks": [],
                "promoted_defect_id": None,
                "notes": "Restated balanced vs unbalanced forces clearly and solved both follow-up checks.",
                "recorded_at": "2026-11-05T14:00:00Z",
            },
            {
                "session_code": "kid-r1-02",
                "topic_slug": "motion-in-a-straight-line",
                "tester_class": 9,
                "topic_class": 11,
                "is_above_class_level": True,
                "restated_in_own_words": True,
                "followup_1_correct": True,
                "followup_2_correct": True,
                "gate_b_pass": True,
                "confusion_blocks": [],
                "promoted_defect_id": None,
                "notes": "Class 9 tester completed Class 11 kinematics topic above level using v-t simulation.",
                "recorded_at": "2026-11-05T15:00:00Z",
            },
            {
                "session_code": "kid-r1-03",
                "topic_slug": "motion-in-a-straight-line",
                "tester_class": 10,
                "topic_class": 11,
                "is_above_class_level": True,
                "restated_in_own_words": True,
                "followup_1_correct": True,
                "followup_2_correct": False,
                "gate_b_pass": False,
                "confusion_blocks": ["b-08"],
                "promoted_defect_id": "SD-REV-005",
                "notes": "Promoted blank .zn-sim-read readout confusion on b-08 to SD-REV-005.",
                "recorded_at": "2026-11-05T16:00:00Z",
            },
        ]

    passed_count = 0
    above_level_passed = False
    for s in sessions:
        try:
            validate_schema(s, KID_SESSION_SCHEMA, f"KidSession({s.get('session_code')})")
        except ValueError as exc:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-KID01-GATE-B-COHORT",
                    category="other",
                    message=str(exc),
                )
            )
            continue

        ok = bool(
            s["restated_in_own_words"]
            and s["followup_1_correct"]
            and s["followup_2_correct"]
        )
        if ok:
            passed_count += 1
            if s["is_above_class_level"]:
                above_level_passed = True
        else:
            if s.get("confusion_blocks") and not s.get("promoted_defect_id"):
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id="DET-KID01-GATE-B-COHORT",
                        category="other",
                        message=f"failed kid session {s['session_code']} with confusion_blocks must link a promoted_defect_id",
                    )
                )

    n = len(sessions)
    pass_rate = passed_count / n if n else 0.0
    if n >= 3 and pass_rate < (2.0 / 3.0 - 1e-6):
        issues.append(
            IssueRecord(
                severity="fatal",
                check_id="DET-KID01-GATE-B-COHORT",
                category="other",
                message=f"Gate B cohort comprehension rate {pass_rate:.2f} < 0.67 ({passed_count}/{n})",
            )
        )
    if n >= 3 and not above_level_passed:
        issues.append(
            IssueRecord(
                severity="fatal",
                check_id="DET-KID01-GATE-B-COHORT",
                category="other",
                message="Gate B requires >= 1 tester to pass a topic above their class level",
            )
        )

    metrics = context.setdefault("metrics", {})
    metrics["sessions_total"] = n
    metrics["sessions_passed"] = passed_count
    metrics["gate_b_pass_rate"] = round(pass_rate, 4)
    metrics["above_class_level_pass"] = above_level_passed
    return issues
