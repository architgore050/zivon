"""Approved exam-content notices (`docs/compliance/notices.md`).

The strings below are the normative copy. `testing/content_factory/exam/
test_notices.py` parses the Markdown file and fails if a template here drifts
from it by one character, so the doc stays the source of truth and this module
stays the renderer.

Rules enforced here (not notices.md's prose, its contract):

- an unresolved `{{token}}` is a publish error, never a blank;
- a placeholder with no supplied value is a publish error;
- notices are English or Hindi only, and the word-bearing placeholders
  (`subject`, `paper_type`, `paper_ref`, `series_name`) resolve to the language
  of the notice, so a Hindi notice never carries an English label;
- generated-series copy must not claim a paper; `scan_claims` finds the
  forbidden claims and understands a negated sentence ("this is not an
  official CBSE paper") as the approved disclaimer it is.
"""

from __future__ import annotations

import re
from typing import Any

from .errors import ExamCopyError

NOTICE_IDS = ("N-01", "N-02", "N-03", "N-04", "N-05")

# Bump when the approved copy changes; the publish manifest records it so an
# audit can reconstruct which notice version shipped.
NOTICE_VERSION = "1"

NOTICES: dict[str, dict[str, str]] = {
    "N-01": {
        "en": "These practice questions are written by Zivon in the style of the CBSE Class {{class_num}} {{subject}} paper. They are not CBSE questions. Zivon is not affiliated with or endorsed by CBSE.",
        "hi": "ये अभ्यास प्रश्न ज़ीवोन द्वारा CBSE कक्षा {{class_num}} {{subject}} के पेपर की शैली में लिखे गए हैं। ये CBSE के प्रश्न नहीं हैं। ज़ीवोन CBSE से संबद्ध नहीं है और CBSE इसका अनुमोदन नहीं करता।",
    },
    "N-02": {
        "en": "Source: {{source_board}} Class {{class_num}} {{subject}} ({{subject_code}}), {{paper_year}} {{paper_type}}, {{paper_ref}}. Reproduced unchanged from the paper published by CBSE at {{source_url}}. Zivon is not affiliated with or endorsed by CBSE.",
        "hi": "स्रोत: {{source_board}} कक्षा {{class_num}} {{subject}} ({{subject_code}}), {{paper_year}} {{paper_type}}, {{paper_ref}}। CBSE द्वारा {{source_url}} पर प्रकाशित पेपर से बिना किसी बदलाव के प्रस्तुत। ज़ीवोन CBSE से संबद्ध नहीं है और CBSE इसका अनुमोदन नहीं करता।",
    },
    "N-03": {
        "en": "{{series_name}} uses questions from question papers published by CBSE. Every question shows its source. Zivon is an independent practice platform: this is not an official CBSE paper, and Zivon is not affiliated with or endorsed by CBSE. If you believe an item should not be here, write to {{contact_email}} and we will review it.",
        "hi": "{{series_name}} में CBSE द्वारा प्रकाशित प्रश्न-पत्रों के प्रश्न हैं। हर प्रश्न के साथ उसका स्रोत दिया गया है। ज़ीवोन एक स्वतंत्र अभ्यास मंच है: यह CBSE का आधिकारिक पेपर नहीं है, और ज़ीवोन CBSE से संबद्ध नहीं है या उससे अनुमोदित नहीं है। यदि आपको लगता है कि कोई प्रश्न यहाँ नहीं होना चाहिए, तो {{contact_email}} पर लिखें; हम उसकी समीक्षा करेंगे।",
    },
    "N-04": {
        "en": "The answer shown is reproduced from the CBSE marking scheme for the {{paper_year}} {{paper_type}}. The explanation and any extra working are Zivon's own and are not part of the official marking scheme.",
        "hi": "दिखाया गया उत्तर CBSE की {{paper_year}} {{paper_type}} की मार्किंग स्कीम से लिया गया है। व्याख्या और अतिरिक्त हल ज़ीवोन के अपने हैं और आधिकारिक मार्किंग स्कीम का हिस्सा नहीं हैं।",
    },
    "N-05": {
        "en": "If you are a rights holder and believe content on Zivon infringes your rights, write to {{contact_email}} with the page URL, the question or item, and your relationship to the work. We will acknowledge within 2 working days and hide or remove the item while we review it.",
        "hi": "यदि आप किसी कृति के अधिकार धारक हैं और आपको लगता है कि ज़ीवोन पर सामग्री आपके अधिकारों का उल्लंघन करती है, तो {{contact_email}} पर पृष्ठ का URL, प्रश्न और कृति से अपना संबंध लिखकर भेजें। हम 2 कार्य-दिवसों में पुष्टि देंगे और समीक्षा के दौरान उस प्रश्न को हटा देंगे या छिपा देंगे।",
    },
}

NOTICE_PLACEHOLDERS: dict[str, tuple[str, ...]] = {
    "N-01": ("class_num", "subject"),
    "N-02": (
        "source_board",
        "class_num",
        "subject",
        "subject_code",
        "paper_year",
        "paper_type",
        "paper_ref",
        "source_url",
    ),
    "N-03": ("series_name", "contact_email"),
    "N-04": ("paper_year", "paper_type"),
    "N-05": ("contact_email",),
}

# `{{subject}}`: the Physics subject label for each class context. Class 10
# students sit Science; the series rehearses its Physics section, and the
# notice says so rather than implying a standalone Physics paper.
_SUBJECT_LABELS: dict[str, dict[str, str]] = {
    "physics": {"en": "Physics", "hi": "भौतिकी"},
    "science_physics_section": {
        "en": "Science (Physics section)",
        "hi": "विज्ञान (भौतिकी खंड)",
    },
}

_PAPER_TYPE_LABELS: dict[str, dict[str, str]] = {
    "main": {"en": "main exam paper", "hi": "मुख्य परीक्षा पेपर"},
    "compartment": {
        "en": "compartment exam paper",
        "hi": "कम्पार्टमेंट परीक्षा पेपर",
    },
    "sample": {"en": "sample paper", "hi": "नमूना प्रश्न-पत्र"},
}

_SERIES_NAMES: dict[str, dict[str, str]] = {
    "past_year": {
        "en": "Past-year questions (CBSE)",
        "hi": "पिछले वर्षों के प्रश्न (CBSE)",
    },
}

_TOKEN_RE = re.compile(r"\{\{([a-z_]+)\}\}")

# Forbidden positive claims on a *generated* exam-style surface
# (`cbse-exam-content.md` §8, FEATURE-MAP SER-14). The patterns are deliberately
# narrow: they match claims, not the subject matter.
_CLAIM_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bofficial\s+cbse\b", "official_cbse"),
    (r"\bcbse[\s-]*approved\b", "cbse_approved"),
    (r"\bapproved\s+by\s+cbse\b", "cbse_approved"),
    (r"\bcbse[\s-]*affiliated\b", "cbse_affiliated"),
    (r"\baffiliated\s+(?:with|to)\s+cbse\b", "cbse_affiliated"),
    (r"\bin\s+partnership\s+with\s+cbse\b", "cbse_partnership"),
    (r"\bprevious[\s-]+year\s+questions?\b", "previous_year_claim"),
    (r"\bpast\s+papers?\b", "past_paper_claim"),
    (r"\bpyqs?\b", "pyq_claim"),
    (r"\bexact\s+cbse\b", "exact_cbse_claim"),
    (r"\bactual\s+board\s+paper\b", "actual_board_paper_claim"),
    (r"\bexact\s+reproduction\b", "exact_reproduction_claim"),
)

_NEGATION_RE = re.compile(
    r"\b(?:not|never|no|isn't|aren't|doesn't|don't|cannot|can't)\b[^.\n]{0,30}$",
    re.IGNORECASE,
)


def subject_label(subject: str, language: str) -> str:
    key = "science_physics_section" if "science" in subject.lower() else "physics"
    return _SUBJECT_LABELS[key][language]


def paper_type_label(paper_type: str, language: str) -> str:
    try:
        return _PAPER_TYPE_LABELS[paper_type][language]
    except KeyError as exc:  # pragma: no cover - callers pass validated enums
        raise ExamCopyError(
            f"no approved {language!r} label for paper type {paper_type!r}"
        ) from exc


def paper_ref(set_code: str | None, question_no: str, language: str) -> str:
    """`Set 55/1/1, Question 23` / `Question 12`, localized."""
    if set_code:
        return (
            f"Set {set_code}, Question {question_no}"
            if language == "en"
            else f"सेट {set_code}, प्रश्न {question_no}"
        )
    return f"Question {question_no}" if language == "en" else f"प्रश्न {question_no}"


def series_name(name: str, language: str) -> str:
    return _SERIES_NAMES[name][language]


def notice_placeholders(notice_id: str) -> tuple[str, ...]:
    try:
        return NOTICE_PLACEHOLDERS[notice_id]
    except KeyError as exc:
        raise ExamCopyError(f"unknown notice id {notice_id!r}") from exc


def render_notice(notice_id: str, language: str, values: dict[str, Any]) -> str:
    """Render one approved notice, or raise. Never returns a partial string."""
    if notice_id not in NOTICES:
        raise ExamCopyError(f"unknown notice id {notice_id!r}")
    if language not in NOTICES[notice_id]:
        raise ExamCopyError(
            f"{notice_id}: language {language!r} is not approved "
            f"(approved: {sorted(NOTICES[notice_id])})"
        )
    template = NOTICES[notice_id][language]
    missing = [
        token
        for token in _TOKEN_RE.findall(template)
        if values.get(token) in (None, "")
    ]
    if missing:
        raise ExamCopyError(
            f"{notice_id}/{language}: unresolved placeholder(s) {sorted(set(missing))}"
        )
    rendered = _TOKEN_RE.sub(lambda m: str(values[m.group(1)]), template)
    if "{{" in rendered or "}}" in rendered:
        raise ExamCopyError(f"{notice_id}/{language}: unresolved placeholder left")
    return rendered


def scan_claims(text: str, *, allow_negated: bool = True) -> list[dict[str, str]]:
    """Find forbidden claims in a piece of copy.

    Returns one record per hit: `{reason, phrase, context}`. A negated sentence
    ("this is not an official CBSE paper") is the approved disclaimer and does
    not count when `allow_negated` is true; pass false to audit the raw phrases.
    """
    findings: list[dict[str, str]] = []
    lowered = str(text)
    for pattern, reason in _CLAIM_PATTERNS:
        for match in re.finditer(pattern, lowered, re.IGNORECASE):
            if allow_negated and _NEGATION_RE.search(
                lowered[max(0, match.start() - 40) : match.start()]
            ):
                continue
            start = max(0, match.start() - 30)
            end = min(len(lowered), match.end() + 30)
            findings.append(
                {
                    "reason": reason,
                    "phrase": match.group(0),
                    "context": lowered[start:end].replace("\n", " ").strip(),
                }
            )
    return findings


__all__ = [
    "NOTICES",
    "NOTICE_IDS",
    "NOTICE_PLACEHOLDERS",
    "NOTICE_VERSION",
    "notice_placeholders",
    "paper_ref",
    "paper_type_label",
    "render_notice",
    "scan_claims",
    "series_name",
    "subject_label",
]
