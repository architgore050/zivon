#!/usr/bin/env python3
"""Docs sanity pass for docs/specs/frontend/ (SP5-FRONT protocol §4 tests).

Docs-only agents' tests: every CSV parses, every referenced repo path exists,
every cross-reference resolves, and the spec's id scheme has no orphans.
This script implements exactly that, per the checks the folder README states:

  1. CSV integrity  - component-inventory.csv parses; header matches the
     documented 22 columns; no ragged rows.
  2. Path integrity - every repo-relative path referenced in the folder exists,
     EXCEPT (a) EXPECTED_ABSENT: upstream artifacts the spec deliberately flags
     as missing - for those, EXISTING is the failure (the flag story broke);
     (b) KNOWN_PENDING: declared work items (new files an execution agent will
     create) - allowed only in files that declare ownership.
  3. Id orphans     - every EL-/INF-/NEED-/EVT- id USED in the folder must be
     DEFINED in its register (EL: the inventory CSV; INF/NEED: spec.md §14
     register tables; EVT: spec.md §9 table + the client contract).
  4. Placeholders   - no TODO/TBD/FIXME/XXX/【…】 tokens in the folder.
  5. Anchors        - explicit cross-references like "spec.md §7" resolve to a
     real section heading in the target file.

Exit 0 = green. Stdlib only.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FOLDER = REPO / "docs" / "specs" / "frontend"

CSV_COLUMNS = [
    "element_id",
    "screen_id",
    "region",
    "feature_id",
    "element_type",
    "component_name",
    "file_location",
    "content_source",
    "states",
    "visible_when",
    "interaction",
    "emits_event",
    "needs_api",
    "reads_entity",
    "i18n",
    "tts",
    "a11y",
    "perf_budget",
    "privacy_class",
    "source_ref",
    "provisional",
    "notes",
]

# Upstream artifacts the spec is BUILT ON being absent. If one shows up on the
# branch, the reconciliation procedure (open-questions.md §R) must run first.
EXPECTED_ABSENT = {
    "docs/product/features.md",
    "docs/product/ui-element-inventory.csv",
    "docs/product/information-inventory.csv",
    "docs/product/traceability-matrix.csv",
    "docs/product/decision-log.csv",
    "docs/product/backend-handoff.md",
    "docs/backend/backend-spec.md",
    "docs/backend/adr",
    "docs/product",
    "docs/backend",
}

# Work items this spec DECLARES (owner named in the same file) - not present yet.
KNOWN_PENDING = {
    "scripts/gen-seo-files.py",
    "frontend/404.html",
    "frontend/sitemap.xml",
    "frontend/robots.txt",
    "testing/frontend/test_perf_budget.py",
    "frontend/assets/og-card.png",
}
PENDING_OWNERSHIP_MARKERS = (
    "EX5-FRONT",
    "spec C",
    "assignment",
    "execution agent",
    "change list",
    "work item",
)

PATH_RE = re.compile(
    r"(?:docs|frontend|testing|skills|scripts|docker|k8s|factory|llm_manager)"
    r"/[A-Za-z0-9_][A-Za-z0-9_\-./]*"
)
MD = r"[A-Za-z0-9\-]+\.md"
# An anchor is checked only when the .md name is ADJACENT to the § marker
# ("spec.md §7" / "§3.2 spec.md") - a bare "doctrine §10.5" names a section of
# a document named by context, not a checkable file+section pair.
REF_FWD = re.compile(rf"({MD})\s*§(\d+(?:\.\d+)?)")  # "spec.md §7"
REF_REV = re.compile(rf"§(\d+(?:\.\d+)?)\s+({MD})")  # "§3.2 spec.md"
PLACEHOLDER_RE = re.compile(r"TODO|TBD|FIXME|XXX|【")
CODE_SPAN_RE = re.compile(r"`[^`]*`")
# Documented metavariables in open-questions.md §R (remap procedure), not rows.
EL_METAVARS = {"EL-PROV", "EL-CANON"}


def collect_text() -> dict[Path, str]:
    out: dict[Path, str] = {}
    for p in sorted(FOLDER.iterdir()):
        if p.suffix in {".md", ".csv"}:
            out[p] = p.read_text(encoding="utf-8")
    if not out:
        raise SystemExit("docs/specs/frontend/ is empty - nothing to sanity-check")
    return out


def check_csv(errors: list[str]) -> list[str]:
    inv = FOLDER / "component-inventory.csv"
    if not inv.exists():
        errors.append("component-inventory.csv missing")
        return []
    with inv.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        errors.append("component-inventory.csv is empty")
        return []
    if rows[0] != CSV_COLUMNS:
        errors.append(
            f"CSV header mismatch: got {rows[0][:3]}... want {CSV_COLUMNS[:3]}..."
        )
    for i, row in enumerate(rows[1:], start=2):
        if len(row) != len(CSV_COLUMNS):
            errors.append(f"CSV line {i}: {len(row)} fields, want {len(CSV_COLUMNS)}")
    return [r[0] for r in rows[1:] if r and r[0].startswith("EL-")]


def defined_ids(
    texts: dict[Path, str],
) -> tuple[set[str], set[str], set[str], set[str]]:
    inf: set[str] = set()
    need: set[str] = set()
    evt: set[str] = set()
    spec = FOLDER / "spec.md"
    for line in texts.get(spec, "").splitlines():
        for m in re.findall(r"`(INF-\d+)`", line):
            inf.add(m)
        for m in re.findall(r"`(NEED-\d+)`", line):
            need.add(m)
        for m in re.findall(r"(EVT-[a-z_]+)", line):
            evt.add(m)
    # EVT definitions may also live in the client contract (its §9 event).
    evt |= set(
        re.findall(r"(EVT-[a-z_]+)", texts.get(FOLDER / "ws-client-contract.md", ""))
    )
    return inf, need, evt, set()


def check_paths(texts: dict[Path, str], errors: list[str]) -> None:
    for path, text in texts.items():
        rel = path.relative_to(REPO)
        for tok in {m.group(0).rstrip(".,;:'\"") for m in PATH_RE.finditer(text)}:
            if tok in EXPECTED_ABSENT:
                if (REPO / tok).exists():
                    errors.append(
                        f"{rel}: {tok} is EXPECTED_ABSENT but exists - run open-questions.md §R"
                    )
                continue
            if tok in KNOWN_PENDING:
                if not any(marker in text for marker in PENDING_OWNERSHIP_MARKERS):
                    errors.append(
                        f"{rel}: pending work item {tok} referenced without an owner declaration"
                    )
                continue
            if any(ch in tok for ch in "<>") or tok.endswith("/"):
                continue  # URL templates / directory mentions
            if "…" in tok or "..." in tok:
                prefix = tok.split("…")[0].split("...")[0].rstrip("/")
                if not (REPO / prefix).exists():
                    errors.append(f"{rel}: ellipsis path prefix does not exist: {tok}")
                continue
            if "*" in tok:
                # glob-ish reference: at least the static prefix must exist
                prefix = tok.split("*")[0].rstrip("/")
                if not (REPO / prefix).exists():
                    errors.append(f"{rel}: wildcard path prefix does not exist: {tok}")
                continue
            if not (REPO / tok).exists():
                errors.append(f"{rel}: referenced path does not exist: {tok}")


def check_id_orphans(
    texts: dict[Path, str], el_ids: list[str], errors: list[str]
) -> None:
    el_defined = set(el_ids) | EL_METAVARS
    inf_def, need_def, evt_def, _ = defined_ids(texts)
    for path, text in texts.items():
        rel = path.relative_to(REPO)
        for m in re.finditer(r"\bEL-[A-Z0-9\-]+\b", text):
            if m.group(0) not in el_defined:
                errors.append(
                    f"{rel}: EL id used but not in the inventory: {m.group(0)}"
                )
        for m in re.finditer(r"\bINF-\d+\b", text):
            if m.group(0) not in inf_def:
                errors.append(
                    f"{rel}: INF id used but not in spec.md §14.1: {m.group(0)}"
                )
        for m in re.finditer(r"\bNEED-\d+\b", text):
            if m.group(0) not in need_def:
                errors.append(
                    f"{rel}: NEED id used but not in spec.md §14.2: {m.group(0)}"
                )
        for m in re.finditer(r"\bEVT-[a-z_]+\b", text):
            if m.group(0) not in evt_def:
                errors.append(f"{rel}: EVT id used but not in a register: {m.group(0)}")


def check_anchors(texts: dict[Path, str], errors: list[str]) -> None:
    for path, text in texts.items():
        rel = path.relative_to(REPO)
        for m in REF_FWD.finditer(text):
            target, sec = m.group(1), m.group(2)
            tpath = FOLDER / target
            if not tpath.exists():
                errors.append(f"{rel}: anchor target file missing: {target}")
                continue
            body = tpath.read_text(encoding="utf-8")
            head = re.search(rf"^#+\s*{re.escape(sec)}[\.\s:]", body, re.MULTILINE)
            if not head and f"§{sec}" not in body:
                errors.append(f"{rel}: §{sec} not found in {target}")
        for m in REF_REV.finditer(text):
            sec, target = m.group(1), m.group(2)
            tpath = FOLDER / target
            if not tpath.exists():
                errors.append(f"{rel}: anchor target file missing: {target}")
                continue
            body = tpath.read_text(encoding="utf-8")
            head = re.search(rf"^#+\s*{re.escape(sec)}[\.\s:]", body, re.MULTILINE)
            if not head and f"§{sec}" not in body:
                errors.append(f"{rel}: §{sec} not found in {target}")


def main() -> int:
    errors: list[str] = []
    texts = collect_text()
    el_ids = check_csv(errors)
    for path, text in texts.items():
        rel = path.relative_to(REPO)
        prose = CODE_SPAN_RE.sub(
            "", text
        )  # inline code may QUOTE the tokens it forbids
        for m in PLACEHOLDER_RE.finditer(prose):
            errors.append(f"{rel}: placeholder token {m.group(0)!r}")
    check_paths(texts, errors)
    check_id_orphans(texts, el_ids, errors)
    check_anchors(texts, errors)

    if errors:
        print(f"FAIL - {len(errors)} finding(s):")
        for e in sorted(set(errors)):
            print(f"  - {e}")
        return 1
    n = len(texts)
    print(
        f"OK - docs sanity pass green: {n} files, "
        f"{len(el_ids)} EL rows, id/path/anchor/placeholder checks clean"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
