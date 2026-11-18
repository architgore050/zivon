"""The safety-core parity guard (agent-and-rag.md §4.1/§5.2, added by PL2).

`personalization.assert_safety_parity` asserts the shared safety-core
sentences are byte-present in BOTH surfaces' prompts:

- the voice tutor: `voice/ws_api.py::TUTOR_SYSTEM_PROMPT`
- personalized learning: `backend/personalized/prompts.py::TEACH_SYSTEM`

so the two can never drift. The voice test module is where the spec pins it
(`testing/voice/test_prompt_safety_parity.py`); the PL prompt is imported
lazily so the voice suite stays runnable without the backend extras.
"""

from __future__ import annotations

import unittest


class PromptSafetyParityTest(unittest.TestCase):
    def test_both_prompts_carry_every_safety_core_sentence(self) -> None:
        from backend.personalized.personalization import (
            SAFETY_CORE,
            assert_safety_parity,
        )

        voice_prompt = _voice_system_prompt()
        from backend.personalized.prompts import TEACH_SYSTEM

        # Raises with the missing sentence when either prompt drifts.
        assert_safety_parity(TEACH_SYSTEM, voice_prompt)
        self.assertTrue(SAFETY_CORE)

    def test_voice_prompt_keeps_the_block_out_of_the_system_slot(self) -> None:
        """§5.2: the voice transport joins every system message into one
        privileged instruction — the personal block must therefore never be
        worded as a system message in the voice prompt's own contract."""
        voice_prompt = _voice_system_prompt()
        self.assertNotIn("STUDENT-AUTHORED PREFERENCES", voice_prompt)

    def test_pl_prompt_grounds_and_bans_official_cbse_claims(self) -> None:
        from backend.personalized.prompts import TEACH_SYSTEM

        self.assertIn("universe of this slice", TEACH_SYSTEM)
        self.assertIn("never official CBSE questions", TEACH_SYSTEM)


def _voice_system_prompt() -> str:
    import inspect

    from voice import ws_api

    source = inspect.getsource(ws_api)
    marker = 'TUTOR_SYSTEM_PROMPT = """'
    start = source.index(marker) + len(marker)
    end = source.index('"""', start)
    return source[start:end]


if __name__ == "__main__":
    unittest.main()
