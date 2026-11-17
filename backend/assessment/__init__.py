"""Runtime assessment data layer for practice, speaking, and tests (W4).

This is the **product-runtime** side of assessment content: the SQL read/write
helpers F5 (practice), F6 (speaking), and F7 (tests/series) share. The
build-time content pipeline is a different package (`factory.assessment`) and
never imports this one.

The public entry points are re-exported here so routes depend on one small
surface. Nothing here talks to a model, a vendor, or the network; it is
deterministic SQL plus JSON decoding.
"""

from __future__ import annotations

from .store import (
    DIFFICULTIES,
    HISTORY_LIMIT,
    MAX_QUESTION_IDS,
    MAX_TRANSCRIPT_CHARS,
    PACK_LANGUAGES,
    PRACTICE_MODES,
    QUESTION_TYPES,
    SERIES_KINDS,
    SERVED_STATUSES,
    AnswerCheck,
    AssessmentError,
    Question,
    check_answer,
    complete_practice_session,
    create_practice_session,
    create_test_attempt,
    delete_speaking_attempt,
    fetch_question,
    fetch_questions,
    fetch_speaking_prompt,
    get_practice_session,
    get_series,
    get_speaking_attempt,
    get_test,
    get_test_attempt,
    list_practice_attempts,
    list_practice_history,
    list_series,
    list_speaking_attempts,
    list_speaking_prompts,
    list_test_answers,
    list_test_attempts,
    list_test_questions,
    list_tests,
    record_practice_answer,
    save_speaking_attempt,
    save_test_answer,
    select_question_ids,
    submit_test_attempt,
)

__all__ = [
    "DIFFICULTIES",
    "HISTORY_LIMIT",
    "MAX_QUESTION_IDS",
    "MAX_TRANSCRIPT_CHARS",
    "PACK_LANGUAGES",
    "PRACTICE_MODES",
    "QUESTION_TYPES",
    "SERIES_KINDS",
    "SERVED_STATUSES",
    "AnswerCheck",
    "AssessmentError",
    "Question",
    "check_answer",
    "complete_practice_session",
    "create_practice_session",
    "create_test_attempt",
    "delete_speaking_attempt",
    "fetch_question",
    "fetch_questions",
    "fetch_speaking_prompt",
    "get_practice_session",
    "get_series",
    "get_speaking_attempt",
    "get_test",
    "get_test_attempt",
    "list_practice_attempts",
    "list_practice_history",
    "list_series",
    "list_speaking_attempts",
    "list_speaking_prompts",
    "list_test_answers",
    "list_test_attempts",
    "list_test_questions",
    "list_tests",
    "record_practice_answer",
    "save_speaking_attempt",
    "save_test_answer",
    "select_question_ids",
    "submit_test_attempt",
]
