"""Deterministic checkers for `EV-CUR-001` (Curator stage `00-ingest..02-generate.ground_truth`).

Reuses `factory.ingest`, `factory.locate`, `factory.textops`, `factory.checks`,
and `factory.schemas` to verify source provenance, title-line matching, ruled-table
and symbol-font extraction, ground-truth citations, and boundary-aware verbatim numerals.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any
from unittest import mock

from factory import checks, retrieval
from factory.artifacts import RunContext
from factory.config import load_config
from factory.ingest import _extract_pages
from factory.ingest import run as ingest_run
from factory.locate import run as locate_run
from factory.retrieval import FixtureEmbedder
from factory.schemas import GROUND_TRUTH
from factory.textops import clean_pdf_text

from ..config import EvalConfig
from ..models import EvalCard, IssueRecord, validate_schema


def check_title_provenance(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-CUR01-PROVENANCE`: Verify `matched_via == 'title_line'` on all golden
    topics and verify the `kinem-ch02` vs `kinem-ch04` body-phrase trap resolves
    to `ch02.pdf` with `matched_via == 'title_line'`.
    """
    issues: list[IssueRecord] = []

    # 1. Verify golden topic metadata and expected.json provenance
    for topic_rel in card.golden_inputs.get("topics", []):
        tdir = cfg.repo_root / topic_rel
        exp_path = tdir / "expected.json"
        meta_path = tdir / "source_pack_meta.json"
        if not exp_path.exists() or not meta_path.exists():
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-CUR01-PROVENANCE",
                    category="fact",
                    message=f"missing golden files in {topic_rel}",
                )
            )
            continue
        exp = json.loads(exp_path.read_text(encoding="utf-8"))
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if exp["source_provenance"].get("matched_via") != "title_line":
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-CUR01-PROVENANCE",
                    category="fact",
                    message=f"{exp['golden_id']} expected.json matched_via != 'title_line'",
                )
            )
        if meta.get("matched_via") != "title_line":
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-CUR01-PROVENANCE",
                    category="fact",
                    message=f"{exp['golden_id']} source_pack_meta.json matched_via != 'title_line'",
                )
            )

    # 2. Run the kinem-ch02 vs kinem-ch04 contamination-pair verification
    pdfs_dir = (
        cfg.repo_root / "testing" / "content_factory" / "mocks" / "fixtures" / "pdfs"
    )
    if (pdfs_dir / "kinem-ch02.pdf").exists() and (
        pdfs_dir / "kinem-ch04.pdf"
    ).exists():
        with tempfile.TemporaryDirectory(prefix="zivon-eval-cur-") as td:
            tmp = Path(td)
            dest = tmp / "pdfs" / "fixture-kinem-9"
            dest.mkdir(parents=True, exist_ok=True)
            urls: dict[str, str] = {}
            for src, dst in [
                ("prelims.pdf", "prelims.pdf"),
                ("kinem-ch02.pdf", "ch02.pdf"),
                ("kinem-ch04.pdf", "ch04.pdf"),
            ]:
                shutil.copy(pdfs_dir / src, dest / dst)
                urls[dst] = (dest / dst).as_uri()
            alt_dest = tmp / "pdfs" / "alt-open-physics"
            alt_dest.mkdir(parents=True, exist_ok=True)
            shutil.copy(
                pdfs_dir / "alt-open-physics.pdf", alt_dest / "alt-open-physics.pdf"
            )
            alt_uri = (alt_dest / "alt-open-physics.pdf").as_uri()

            catalog = {
                "version": 1,
                "books": [
                    {
                        "id": "fixture-kinem-9",
                        "class": 9,
                        "subject": "science",
                        "title": "Fixture Kinematics Class 9",
                        "publisher": "fixture",
                        "license": "test",
                        "is_ncert": True,
                        "download": "auto",
                        "prelims_url": urls["prelims.pdf"],
                        "chapter_url_template": urls["ch02.pdf"].replace(
                            "ch02.pdf", "ch{nn}.pdf"
                        ),
                        "chapter_numbers": [2, 4],
                        "chapters_verified": True,
                        "class_evidence": ["class 9"],
                    },
                    {
                        "id": "alt-open-physics",
                        "class": 9,
                        "subject": "physics",
                        "title": "Open Physics Notes",
                        "publisher": "fixture",
                        "license": "CC-BY",
                        "is_ncert": False,
                        "download": "auto",
                        "prelims_url": alt_uri,
                        "chapter_url_template": alt_uri,
                        "chapter_numbers": [1],
                        "chapters_verified": True,
                        "class_evidence": [],
                    },
                ],
            }
            (tmp / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
            base_cfg = json.loads(
                (cfg.repo_root / "config.json").read_text(encoding="utf-8")
            )
            base_cfg["paths"]["pdf_cache"] = str(tmp / "pdfs")
            base_cfg["paths"]["text_cache"] = str(tmp / "cache")
            base_cfg["paths"]["runs"] = str(tmp / "runs")
            base_cfg["paths"]["catalog"] = str(tmp / "catalog.json")
            (tmp / "config.json").write_text(json.dumps(base_cfg), encoding="utf-8")

            env_patch = {
                "ZIVON_BASE_URL": "http://127.0.0.1:8080/v1",
                "ZIVON_MODEL": "eval-smoke",
            }
            with (
                mock.patch.dict("os.environ", env_patch),
                mock.patch.object(
                    retrieval, "get_embedder", lambda _c: FixtureEmbedder()
                ),
            ):
                fcfg = load_config(tmp / "config.json")
                run_ctx = RunContext(tmp / "runs", "eval-kinem")
                run_ctx.save_stage_output("00-ingest", ingest_run(fcfg, run_ctx))
                pack = locate_run(fcfg, run_ctx, "MOTION IN A STRAIGHT LINE", 9)
                if pack["chapter"].get("matched_via") != "title_line" or not pack[
                    "chapter"
                ]["file"].endswith("ch02.pdf"):
                    issues.append(
                        IssueRecord(
                            severity="fatal",
                            check_id="DET-CUR01-PROVENANCE",
                            category="fact",
                            message=f"kinem trap failed: resolved to {pack['chapter']}",
                        )
                    )

    return issues


def check_table_and_glyph_extraction(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-CUR01-TABLE-GLYPHS`: Verify `clean_pdf_text` strips/decodes `U+F0XX`
    symbol-font glyphs and `_extract_pages` reconstructs ruled tables as `[table]` rows.
    """
    issues: list[IssueRecord] = []

    # 1. Verify U+F0XX private-use symbol decoding in clean_pdf_text
    raw_symbol = "Class \uf039 Science \uf02d Motion"
    cleaned = clean_pdf_text(raw_symbol)
    if any(0xF000 <= ord(ch) <= 0xF0FF for ch in cleaned):
        issues.append(
            IssueRecord(
                severity="fatal",
                check_id="DET-CUR01-TABLE-GLYPHS",
                category="fact",
                message="clean_pdf_text left private-use U+F0XX glyphs in text",
            )
        )

    # 2. Check all seeded 03-check source packs contain zero U+F0XX glyphs
    defects_dir = cfg.goldens_dir / "defects" / "03-check"
    if defects_dir.is_dir():
        for p in sorted(defects_dir.glob("*.json")):
            data = json.loads(p.read_text(encoding="utf-8"))
            ncert_text = (
                data.get("inputs", {}).get("source_pack", {}).get("ncert_text", "")
            )
            if any(0xF000 <= ord(ch) <= 0xF0FF for ch in ncert_text):
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id="DET-CUR01-TABLE-GLYPHS",
                        category="fact",
                        message=f"{p.name} ncert_text contains U+F0XX private-use glyphs",
                    )
                )

    # 3. Verify ruled-table extraction on a synthetic 1-page PDF
    from testing.content_factory.unit.test_ingest import _make_table_page_pdf

    with tempfile.TemporaryDirectory(prefix="zivon-eval-tbl-") as td:
        pdf_path = Path(td) / "table.pdf"
        _make_table_page_pdf(pdf_path)
        pages = _extract_pages(pdf_path)
        text = pages[0]["text"]
        if "[table]" not in text or "Quantity | Symbol | Unit" not in text:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-CUR01-TABLE-GLYPHS",
                    category="fact",
                    message="ruled PDF table did not extract as explicit [table] pipe rows",
                )
            )

    return issues


def check_ground_truth_citations(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-CUR01-CITATIONS`: Validate `GROUND_TRUTH` schema and citation provenance."""
    issues: list[IssueRecord] = []

    samples = [
        cfg.goldens_dir / "defects" / "03-check" / "SD-CHK-007.json",
        cfg.goldens_dir / "defects" / "03-check" / "SD-CHK-008.json",
    ]
    for spath in samples:
        if not spath.exists():
            continue
        data = json.loads(spath.read_text(encoding="utf-8"))
        inputs = data["inputs"]
        gt = inputs["ground_truth"]
        pack = inputs["source_pack"]
        blocks = inputs["blocks"]["blocks"]
        try:
            validate_schema(gt, GROUND_TRUTH, f"{spath.name}:ground_truth")
        except ValueError as exc:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-CUR01-CITATIONS",
                    category="fact",
                    message=str(exc),
                )
            )
            continue

        allowed_sources = {"ncert"}
        if pack.get("chapter", {}).get("book_id"):
            allowed_sources.add(pack["chapter"]["book_id"])
        for s in pack.get("supplements", []):
            if s.get("source_id"):
                allowed_sources.add(s["source_id"])
            if s.get("book_id"):
                allowed_sources.add(s["book_id"])

        for section_key in ("claims", "key_terms", "equations", "misconceptions"):
            for item in gt.get(section_key, []):
                cits = item.get("citations", [])
                if not cits:
                    issues.append(
                        IssueRecord(
                            severity="fatal",
                            check_id="DET-CUR01-CITATIONS",
                            category="fact",
                            message=f"{spath.name}: {section_key} item missing citations",
                        )
                    )
                for c in cits:
                    if c.get("source_id") not in allowed_sources:
                        issues.append(
                            IssueRecord(
                                severity="fatal",
                                check_id="DET-CUR01-CITATIONS",
                                category="fact",
                                message=f"{spath.name}: unknown source_id {c.get('source_id')!r}",
                            )
                        )

        cit_issues = checks.rule_citations(blocks, gt, pack)
        for ci in cit_issues:
            issues.append(
                IssueRecord(
                    severity=ci["severity"],
                    check_id="DET-CUR01-CITATIONS",
                    block_id=ci.get("block_id"),
                    category="fact",
                    message=ci["message"],
                )
            )

    return issues


def check_verbatim_numbers_in_claims(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-CUR01-NUMBERS`: Verify every numeral in `ground_truth.claims[*].statement`
    and block problem statements appears in the source pack corpus (`_number_in_corpus`).
    """
    issues: list[IssueRecord] = []
    samples = [
        cfg.goldens_dir / "defects" / "03-check" / "SD-CHK-007.json",
        cfg.goldens_dir / "defects" / "03-check" / "SD-CHK-008.json",
    ]
    for spath in samples:
        if not spath.exists():
            continue
        data = json.loads(spath.read_text(encoding="utf-8"))
        inputs = data["inputs"]
        gt = inputs["ground_truth"]
        pack = inputs["source_pack"]
        blocks = inputs["blocks"]["blocks"]
        corpus = " ".join(
            [pack.get("ncert_text", "")]
            + [s.get("text", "") for s in pack.get("supplements", [])]
        )
        for claim in gt.get("claims", []):
            for num in re.findall(r"\d+(?:\.\d+)?", claim.get("statement", "")):
                if not checks._number_in_corpus(num, corpus):
                    issues.append(
                        IssueRecord(
                            severity="fatal",
                            check_id="DET-CUR01-NUMBERS",
                            category="fact",
                            message=f"{spath.name}: claim {claim['id']} numeral {num} not in source corpus",
                        )
                    )
        num_issues = checks.rule_numbers(blocks, gt, pack)
        for ni in num_issues:
            issues.append(
                IssueRecord(
                    severity=ni["severity"],
                    check_id="DET-CUR01-NUMBERS",
                    block_id=ni.get("block_id"),
                    category="fact",
                    message=ni["message"],
                )
            )
    return issues
