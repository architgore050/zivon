"""The clearance register reader (`docs/compliance/decision-log.md`).

`DEC-COMP-001` says verbatim CBSE content may publish only when
`EXAM_VERBATIM_CLEARANCE_ID` names a row in the clearance register, and that
clearance is scoped: permission for Class 12 Physics does not cover Class 10
Science, another language, or another year range.

This module is the machine-readable half of that rule. It parses the register's
Markdown table and answers two questions:

- does a row with this id exist at all (the config gate), and
- does that row's scope actually cover this item (the publish gate)?

Both answers fail closed. An unparseable or partial scope cell refuses rather
than guessing - the register is a legal record, and a parser is not counsel.

Scope cell contract (documented in `docs/content-factory/exam.md` §6): the cell
must name the class, the subject, the year(s) and the language(s), e.g.
`Class 12 / Physics / 2022-2026 / en, hi`. The parser looks for `class <n>`,
the subject string, the year as a number (or inside a `YYYY-YYYY` range) and
the language code. Anything it cannot find is treated as not covered.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CLEARANCE_ID_RE = re.compile(r"^[A-Z][A-Z0-9_-]{2,39}$")
_INSTRUMENTS = ("written_permission", "counsel_opinion")
_YEAR_RANGE_RE = re.compile(r"(\d{4})\s*[-–]\s*(\d{4})")
_CLASS_RE = re.compile(r"class(?:es)?\s*([0-9]{1,2}(?:\s*[,/&]\s*[0-9]{1,2})*)")
_PLACEHOLDER_SCOPE = {"—", "-", "", "none"}


@dataclass(frozen=True)
class ClearanceRow:
    clearance_id: str
    instrument: str
    scope: str
    issued: str
    review: str
    recorded_by: str
    document_ref: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "clearance_id": self.clearance_id,
            "instrument": self.instrument,
            "scope": self.scope,
            "issued": self.issued,
            "review": self.review,
            "recorded_by": self.recorded_by,
            "document_ref": self.document_ref,
        }

    def covers(
        self,
        *,
        class_num: int,
        subject: str,
        year: int,
        language: str,
    ) -> bool:
        """Conservative scope check. Missing evidence means "not covered"."""
        if self.instrument not in _INSTRUMENTS:
            return False
        scope = (self.scope or "").strip().lower()
        if scope in _PLACEHOLDER_SCOPE or "none" == scope:
            return False
        classes: set[int] = set()
        for match in _CLASS_RE.finditer(scope):
            for chunk in re.split(r"\s*[,/&]\s*", match.group(1)):
                if chunk.strip().isdigit():
                    classes.add(int(chunk))
        if class_num not in classes:
            return False
        if subject.strip().lower() not in scope:
            return False
        years: set[int] = set()
        for start, end in _YEAR_RANGE_RE.findall(scope):
            years.update(range(int(start), int(end) + 1))
        years.update(
            int(token)
            for token in re.findall(r"(?<!\d)(\d{4})(?!\d)", scope)
            if 2000 <= int(token) <= 2100
        )
        if year not in years:
            return False
        languages = set(re.findall(r"\b(en|hi|hinglish|hi-latn)\b", scope))
        return language.strip().lower() in languages


def _cells(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return []
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def parse_clearance_register(text: str) -> list[ClearanceRow]:
    """Every real row in the register. The `_(none)_` placeholder is skipped."""
    rows: list[ClearanceRow] = []
    header_seen = False
    for line in text.splitlines():
        cells = _cells(line)
        if not cells:
            # A blank line or a non-table line ends the register table; the
            # document has other tables (counsel questions, takedowns) that
            # must not be read as clearances.
            header_seen = False
            continue
        if cells[0].lower() == "clearance_id":
            header_seen = True
            continue
        if not header_seen:
            continue
        if set("".join(cells)) <= set("-: "):
            continue  # separator row
        clearance_id = cells[0].strip("`*_ ")
        if not CLEARANCE_ID_RE.match(clearance_id):
            continue
        rows.append(
            ClearanceRow(
                clearance_id=clearance_id,
                instrument=cells[1] if len(cells) > 1 else "",
                scope=cells[2] if len(cells) > 2 else "",
                issued=cells[3] if len(cells) > 3 else "",
                review=cells[4] if len(cells) > 4 else "",
                recorded_by=cells[5] if len(cells) > 5 else "",
                document_ref=cells[6] if len(cells) > 6 else "",
            )
        )
    return rows


def load_clearance_register(path: Path) -> list[ClearanceRow]:
    if not path.is_file():
        return []
    return parse_clearance_register(path.read_text(encoding="utf-8"))


def find_clearance(rows: list[ClearanceRow], clearance_id: str) -> ClearanceRow | None:
    wanted = (clearance_id or "").strip()
    if not wanted:
        return None
    for row in rows:
        if row.clearance_id == wanted:
            return row
    return None


__all__ = [
    "CLEARANCE_ID_RE",
    "ClearanceRow",
    "find_clearance",
    "load_clearance_register",
    "parse_clearance_register",
]
