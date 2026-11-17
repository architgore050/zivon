"""Practice session policy for the F5 player (REQUIREMENTS §10.6–§10.8).

The SQL lives in `backend.assessment`; the answer key stays there too. This
package owns the *player's* rules: how a chapter drill / Daily 5 / weak-topic
drill / retry set is selected, which language the questions are served in, what
a session state looks like with the key withheld, and what the post-answer
feedback and summary contain.

Nothing here talks to a model or a vendor, and nothing here accepts a
correctness verdict from a client: `record_practice_answer` grades from the
stored key, and this layer only reports the result.
"""

from __future__ import annotations

from .service import (
    CHAPTER_COUNT_DEFAULT,
    CHAPTER_COUNT_MAX,
    CHAPTER_COUNT_MIN,
    DAILY_COUNT,
    PACK_LANGUAGE_BY_LOCALE,
    RETRY_COUNT,
    PracticeUser,
    complete_session,
    create_session,
    history,
    pack_language,
    practice_user,
    session_state,
    session_summary,
    submit_answer,
)

__all__ = [
    "CHAPTER_COUNT_DEFAULT",
    "CHAPTER_COUNT_MAX",
    "CHAPTER_COUNT_MIN",
    "DAILY_COUNT",
    "PACK_LANGUAGE_BY_LOCALE",
    "RETRY_COUNT",
    "PracticeUser",
    "complete_session",
    "create_session",
    "history",
    "pack_language",
    "practice_user",
    "session_state",
    "session_summary",
    "submit_answer",
]
