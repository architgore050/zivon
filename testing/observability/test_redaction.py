"""Redaction guarantees (spec.md §4, logging-api.md §6) — the tests ARE the
guarantee: every denylist key pattern, every value-regex kind, the
sanctioned reference-field allow, the violation-event shape, and the
per-call-site dedup. A PR that weakens these fails review by the tests lens.
"""

from __future__ import annotations

import unittest

from logging_manager import ErrorClass, Severity
from logging_manager.redact import redact_fields, redact_text

from .support import ObservabilityTest


class KeyDenylistTests(ObservabilityTest):
    def test_exact_matches_are_denied(self) -> None:
        for key in (
            "text",
            "content",
            "prompt",
            "messages",
            "response",
            "completion",
            "answer",
            "page_html",
            "code",
            "patch",
            "wav",
            "pcm",
            "cookie",
            "token",
            "secret",
            "key",
            "authorization",
        ):
            with self.subTest(key=key):
                clean, violations = redact_fields({key: "value"})
                self.assertEqual(clean[key], "[REDACTED:key-denylist]")
                self.assertEqual(violations, [(key, "key-denylist")])

    def test_exact_match_is_case_insensitive(self) -> None:
        for key in ("Text", "CONTENT", "Prompt", "Secret", "AUTHORIZATION"):
            clean, _ = redact_fields({key: "value"})
            self.assertEqual(clean[key], "[REDACTED:key-denylist]")

    def test_prefix_patterns_catch_suffixes(self) -> None:
        for key in (
            "transcript",
            "transcript_raw",
            "audio",
            "audio_url",
            "speech",
            "utterance_1",
        ):
            clean, _ = redact_fields({key: "value"})
            self.assertEqual(clean[key], "[REDACTED:key-denylist]", key)

    def test_reference_fields_are_allowed(self) -> None:
        """The sanctioned way to log a REFERENCE (never content): these ride
        through even though `transcript*` would otherwise eat transcript_row_id."""
        fields = {
            "transcript_row_id": 12345,
            "artifact_path": "runs/motion-c9/02-generate/output.json",
            "block_id": "block-04",
            "topic": "Motion",
            "chapter": "Motion",
        }
        clean, violations = redact_fields(dict(fields))
        self.assertEqual(clean, fields)
        self.assertEqual(violations, [])

    def test_near_misses_are_not_over_blocked(self) -> None:
        """Exact-match semantics: `context` contains 'text' as a substring but
        is a different field; counts and ids are legitimate payload."""
        fields = {
            "blocks": 14,
            "elapsed_s": 51.2,
            "language_mix": "hi-en",
            "block_id": "b-1",
            "reason_code": "gate_fail",
        }
        clean, violations = redact_fields(dict(fields))
        self.assertEqual(clean, fields)
        self.assertEqual(violations, [])


class ValueRegexTests(ObservabilityTest):
    def test_emails_are_scrubbed(self) -> None:
        self.assertEqual(
            redact_text("contact a.b@email.in for access"),
            "contact [REDACTED:email] for access",
        )

    def test_indian_phone_numbers_are_scrubbed(self) -> None:
        self.assertEqual(redact_text("call +919876543210"), "call [REDACTED:phone]")
        self.assertEqual(
            redact_text("call 9876543210 now"), "call [REDACTED:phone] now"
        )

    def test_aadhaar_shape_is_scrubbed_only_with_context(self) -> None:
        # context words are required for DETECTION (a bare 12-digit number is
        # not a redaction hit); the scrubbed span includes the label
        self.assertEqual(
            redact_text("aadhaar number 1234 5678 9012"),
            "[REDACTED:aadhaar]",
        )
        self.assertEqual(redact_text("uid 1234-5678-9012"), "[REDACTED:aadhaar]")
        self.assertNotIn("REDACTED", redact_text("reference 123456789012"))

    def test_api_keys_are_scrubbed(self) -> None:
        self.assertEqual(
            redact_text("key sk-abcdefghij1234567890"), "key [REDACTED:api_key]"
        )
        self.assertEqual(redact_text("ZIVON_" + "a" * 24), "[REDACTED:api_key]")

    def test_bearer_headers_are_scrubbed(self) -> None:
        self.assertEqual(
            redact_text("Authorization: Bearer abc.def-ghi_123"),
            "Authorization: [REDACTED:bearer]",
        )

    def test_jwt_shapes_are_scrubbed(self) -> None:
        jwt = (
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV"
        )
        self.assertEqual(redact_text(f"token {jwt}"), "token [REDACTED:jwt]")

    def test_base64_audio_smuggle_is_scrubbed(self) -> None:
        blob = "QUJD" * 200  # 800 chars of base64-shaped text
        scrubbed = redact_text(f"data={blob}")
        self.assertTrue(scrubbed.startswith("data=[REDACTED:base64]"))

    def test_scrubbing_applies_inside_arrays(self) -> None:
        clean, _ = redact_fields({"attempts": ["ok", "mail me x@y.com"]})
        self.assertEqual(clean["attempts"], ["ok", "mail me [REDACTED:email]"])

    def test_input_dict_is_not_mutated(self) -> None:
        fields = {"transcript": "words"}
        clean, _ = redact_fields(fields)
        self.assertEqual(fields["transcript"], "words")
        self.assertEqual(clean["transcript"], "[REDACTED:key-denylist]")


class ShapeGuardTests(ObservabilityTest):
    def test_nested_dicts_are_replaced_whole(self) -> None:
        clean, violations = redact_fields({"nested": {"deeper": {"text": "hi"}}})
        self.assertEqual(clean["nested"], "[REDACTED:shape]")
        self.assertEqual(violations, [("nested", "shape")])

    def test_flat_scalar_arrays_pass(self) -> None:
        clean, violations = redact_fields({"ids": [1, 2, 3], "flags": [True, False]})
        self.assertEqual(clean, {"ids": [1, 2, 3], "flags": [True, False]})
        self.assertEqual(violations, [])

    def test_list_of_lists_is_replaced(self) -> None:
        clean, violations = redact_fields({"grid": [[1, 2], [3, 4]]})
        self.assertEqual(clean["grid"], "[REDACTED:shape]")
        self.assertEqual(violations, [("grid", "shape")])


class ViolationEventTests(ObservabilityTest):
    def test_violation_event_carries_key_and_kind_never_payload(self) -> None:
        import logging_manager

        logging_manager.log_event(
            "factory.stage.ok", {"transcript": "the child said words", "blocks": 1}
        )
        violation = self.last_event("log.redaction_violation")
        self.assertEqual(violation["severity"], "WARNING")
        self.assertEqual(violation["error_class"], ErrorClass.PRIVACY_VIOLATION.value)
        self.assertEqual(
            violation["fields"],
            {
                "event_ref": "factory.stage.ok",
                "key": "transcript",
                "kind": "key-denylist",
            },
        )
        self.assertNotIn("the child said", str(violation))

    def test_event_payload_itself_is_redacted(self) -> None:
        import logging_manager

        logging_manager.log_event("factory.stage.ok", {"transcript": "words"})
        emitted = self.last_event("factory.stage.ok")
        self.assertEqual(emitted["fields"]["transcript"], "[REDACTED:key-denylist]")

    def test_dedup_first_plus_every_hundredth(self) -> None:
        import logging_manager

        for _ in range(150):
            logging_manager.log_event("factory.stage.ok", {"token": "leak"})
        self.assertEqual(len(self.of_event("log.redaction_violation")), 2)


class SeverityTests(ObservabilityTest):
    def test_severity_derived_from_map(self) -> None:
        import logging_manager

        logging_manager.log_event(
            "factory.stage.fail", {"reason_code": "x", "attempt": 1}
        )
        self.assertEqual(self.last_event("factory.stage.fail")["severity"], "ERROR")

    def test_explicit_override_for_the_error_boundary(self) -> None:
        import logging_manager

        logging_manager.log_event(
            "factory.stage.ok", {"blocks": 0, "attempts": 0}, severity=Severity.ERROR
        )
        self.assertEqual(self.last_event("factory.stage.ok")["severity"], "ERROR")


if __name__ == "__main__":
    unittest.main()
