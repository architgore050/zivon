"""Unit tests for the standalone llm_manager package (vs the mock server).

Covers the 2026-11-07 streaming semantics: streaming happy path with usage /
finish_reason / first_token_s / chunks, transport retry after a 500, the
non-retryable 400 (with the server's words AND the copy-pasteable hint), the
mid-stream deadline abort (with proof the server observed the disconnect),
the inactivity timeout triggering a retry, the bad-shape response error, the
server-reported mid-stream failure (HTTP 200 + SSE error payload), the
non-streaming path, LLMConfig.from_env() coverage + validation, the
validation-round loop (incl. transcript trimming), and the package isolation
rule (llm_manager must never import factory/).
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from llm_manager import (
    BadServerResponseError,
    ChatResult,
    LLMConfig,
    LLMConfigError,
    LLMManager,
    NonRetryableHTTPError,
    TransportError,
    ValidationExhaustedError,
    run_validation_rounds,
)
from testing.content_factory.mocks.openai_mock import start_mock

MARKER = "[ZIVON STAGE: 02-generate] test"
MESSAGES = [
    {"role": "system", "content": MARKER},
    {"role": "user", "content": "go"},
]
GOOD = '{"topic": "x", "claims": []}'

_ALL_ENV_KEYS = (
    "ZIVON_BASE_URL",
    "ZIVON_MODEL",
    "ZIVON_API_KEY",
    "ZIVON_JSON_MODE",
    "ZIVON_TEMPERATURE",
    "ZIVON_TIMEOUT_S",
    "ZIVON_CONNECT_TIMEOUT_S",
    "ZIVON_CALL_DEADLINE_S",
    "ZIVON_MAX_ATTEMPTS",
    "ZIVON_BACKOFF_BASE_S",
    "ZIVON_VALIDATION_ROUNDS",
    "ZIVON_STREAM",
    "ZIVON_STREAM_USAGE",
    "ZIVON_HEARTBEAT_S",
    "ZIVON_MAX_TOKENS",  # must stay ignored by from_env
)


def _silent_config(**over) -> LLMConfig:
    """A fast, quiet config for transport tests (no 60s heartbeat stalls)."""
    defaults: dict = {
        "heartbeat_s": 1000.0,
        "backoff_base_s": 0.1,
    }
    defaults.update(over)
    return LLMConfig(**defaults)


class TestStreamingClient(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.fixtures = self.tmp / "fixtures"
        self.fixtures.mkdir()

    def _fixture(self, name: str, payload) -> None:
        (self.fixtures / name).write_text(
            payload if isinstance(payload, str) else json.dumps(payload)
        )

    def _start(self):
        self.server, self.url, self.state = start_mock(self.fixtures)
        self.addCleanup(self.server.shutdown)

    def test_streaming_happy_path_full_chat_result(self):
        self._fixture("02-generate.json", {"topic": "x", "claims": []})
        self._start()
        result = LLMManager(
            _silent_config(base_url=self.url, model="mock-model")
        ).complete(MESSAGES, temperature=0.2)
        self.assertIsInstance(result, ChatResult)
        self.assertEqual(result.text, GOOD)
        self.assertEqual(result.finish_reason, "stop")
        self.assertEqual(result.usage["prompt_tokens"], 10)
        self.assertEqual(result.usage["completion_tokens"], 10)
        self.assertEqual(result.model, "mock-model")
        self.assertGreater(result.chunks_received, 1)
        self.assertIsNotNone(result.first_token_s)
        # first token cannot land after the call finished (rounding slack)
        self.assertLessEqual(result.first_token_s, result.latency_s + 0.01)
        # the wire request really streamed and asked for usage stats
        self.assertTrue(self.state.served[0]["stream"])
        self.assertEqual(
            self.state.served[0]["stream_options"], {"include_usage": True}
        )

    def test_transport_retry_after_500_then_success(self):
        self._fixture("02-generate.json", {"topic": "x"})
        self._fixture("02-generate__fail500.json", {"error": "overloaded"})
        self._start()
        result = LLMManager(
            _silent_config(base_url=self.url, model="m", max_attempts=3)
        ).complete(MESSAGES)
        self.assertEqual(result.text, '{"topic": "x"}')
        self.assertEqual(len(self.state.served), 2, "500 must be retried once")

    def test_transport_5xx_exhaustion_raises_transport_error(self):
        self._fixture("02-generate.json", {"topic": "x"})
        self._fixture("02-generate__fail500.json", {"error": "overloaded"})
        self._start()
        with self.assertRaises(TransportError) as ctx:
            LLMManager(
                _silent_config(base_url=self.url, model="m", max_attempts=1)
            ).complete(MESSAGES)
        self.assertIn("HTTP 500 on all 1 tries", str(ctx.exception))
        self.assertIn("overloaded", str(ctx.exception))

    def test_non_retryable_400_fails_immediately_with_hint(self):
        self._fixture("02-generate.json", {"topic": "x"})
        self._fixture(
            "02-generate__fail400.json",
            {"error": {"message": "response_format json_object not supported"}},
        )
        self._start()
        with self.assertRaises(NonRetryableHTTPError) as ctx:
            LLMManager(
                _silent_config(base_url=self.url, model="m", max_attempts=3)
            ).complete(MESSAGES)
        message = str(ctx.exception)
        self.assertIn("HTTP 400", message)
        self.assertIn("response_format json_object not supported", message)
        self.assertIn("set ZIVON_JSON_MODE=false", message)
        self.assertEqual(
            len(self.state.served), 1, "a 400 must never be retried (one request)"
        )

    def test_midstream_error_payload_maps_to_transport_error(self):
        # HTTP 200 + an SSE error payload INSIDE the stream: llama.cpp reports
        # context overflow this way, and the llm-manager node relays its own
        # exhausted upstream to callers exactly like this. The OpenAI SDK
        # raises a bare openai.APIError for such a payload; llm_manager maps
        # it to TransportError with the server's own words preserved (they
        # already name the fix) and does NOT retry - "the server says it
        # failed" is terminal.
        self._fixture("02-generate.json", {"topic": "x"})
        self._fixture(
            "02-generate__stream_error.json", {"message": "context limit exceeded"}
        )
        self._start()
        with self.assertRaises(TransportError) as ctx:
            LLMManager(
                _silent_config(base_url=self.url, model="m", max_attempts=3)
            ).complete(MESSAGES)
        self.assertIn("reported an error mid-call", str(ctx.exception))
        self.assertIn("context limit exceeded", str(ctx.exception))
        self.assertEqual(
            len(self.state.served), 1, "server-reported failure is terminal - no retry"
        )

    def test_deadline_abort_closes_stream_and_server_notices(self):
        self._fixture("02-generate.json", {"topic": "x"})
        self._fixture(
            "02-generate__slow.json",
            {"content": "SLOW" * 20, "chunks": 30, "delay_s": 0.05},
        )
        self._start()
        with self.assertRaises(TransportError) as ctx:
            LLMManager(
                _silent_config(
                    base_url=self.url, model="m", call_deadline_s=0.4, max_attempts=1
                )
            ).complete(MESSAGES)
        message = str(ctx.exception)
        self.assertIn("exceeded call_deadline_s=0.4s", message)
        self.assertIn("aborted so the server stops generating", message)
        # the abort closes the connection mid-generation: the server must SEE
        # the disconnect (that is what frees its slot for the next try)
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not self.state.disconnected:
            time.sleep(0.05)
        self.assertIn("02-generate", self.state.disconnected)

    def test_inactivity_timeout_triggers_retry_then_recovers(self):
        self._fixture("02-generate.json", {"topic": "x"})
        self._fixture("02-generate__stall.json", {"content": "late", "stall_s": 2.0})
        self._start()
        result = LLMManager(
            _silent_config(base_url=self.url, model="m", timeout_s=1.0, max_attempts=2)
        ).complete(MESSAGES)
        self.assertEqual(result.text, '{"topic": "x"}')
        self.assertEqual(len(self.state.served), 2, "the stalled attempt must retry")

    def test_inactivity_timeout_exhaustion_raises_transport_error(self):
        self._fixture("02-generate.json", {"topic": "x"})
        self._fixture("02-generate__stall.json", {"content": "late", "stall_s": 2.0})
        self._start()
        with self.assertRaises(TransportError) as ctx:
            LLMManager(
                _silent_config(
                    base_url=self.url, model="m", timeout_s=1.0, max_attempts=1
                )
            ).complete(MESSAGES)
        self.assertIn("could not reach inference server at", str(ctx.exception))
        self.assertIn("ZIVON_BASE_URL", str(ctx.exception))

    def test_bad_shape_response_raises_bad_server_response_error(self):
        self._fixture("02-generate.json", {"topic": "x"})
        self._fixture("02-generate__badshape.json", {"hello": "world"})
        self._start()
        with self.assertRaises(BadServerResponseError) as ctx:
            LLMManager(
                _silent_config(base_url=self.url, model="m", stream=False)
            ).complete(MESSAGES)
        self.assertIn("chat-completions shape", str(ctx.exception))

    def test_non_streaming_path_still_works_end_to_end(self):
        self._fixture("02-generate.json", {"topic": "x", "claims": []})
        self._start()
        result = LLMManager(
            _silent_config(base_url=self.url, model="m", stream=False)
        ).complete(MESSAGES)
        self.assertEqual(result.text, GOOD)
        self.assertEqual(result.finish_reason, "stop")
        self.assertEqual(result.chunks_received, 0)
        self.assertIsNone(result.first_token_s)
        self.assertEqual(result.usage["total_tokens"], 20)
        self.assertFalse(self.state.served[0]["stream"])

    def test_stream_yields_deltas_and_stream_events_yield_usage(self):
        self._fixture("02-generate.json", {"topic": "x", "claims": []})
        self._start()
        manager = LLMManager(_silent_config(base_url=self.url, model="m"))
        deltas = list(manager.stream(MESSAGES))
        self.assertEqual("".join(deltas), GOOD)
        self.assertGreater(len(deltas), 1)

        events = list(manager.stream_events(MESSAGES))
        deltas2 = [e.delta for e in events if e.delta is not None]
        self.assertEqual("".join(deltas2), GOOD)
        finishes = [e.finish_reason for e in events if e.finish_reason is not None]
        usages = [e.usage for e in events if e.usage is not None]
        self.assertEqual(finishes, ["stop"])
        self.assertEqual(usages[0]["prompt_tokens"], 10)


class TestLLMConfigFromEnv(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in _ALL_ENV_KEYS}
        for key in _ALL_ENV_KEYS:
            os.environ.pop(key, None)

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _set_required(self) -> None:
        os.environ["ZIVON_BASE_URL"] = "http://127.0.0.1:8080/v1"
        os.environ["ZIVON_MODEL"] = "test-model"

    def test_missing_required_vars_name_the_export_example(self):
        with self.assertRaises(LLMConfigError) as ctx:
            LLMConfig.from_env()
        message = str(ctx.exception)
        self.assertIn("ZIVON_BASE_URL", message)
        self.assertIn("ZIVON_MODEL", message)
        self.assertIn("export ZIVON_BASE_URL=", message)

    def test_every_default_value(self):
        self._set_required()
        cfg = LLMConfig.from_env()
        self.assertEqual(cfg.base_url, "http://127.0.0.1:8080/v1")
        self.assertEqual(cfg.model, "test-model")
        self.assertIsNone(cfg.api_key)
        self.assertEqual(cfg.temperature, 0.2)
        self.assertTrue(cfg.json_mode)
        self.assertEqual(cfg.timeout_s, 3600.0)
        self.assertEqual(cfg.connect_timeout_s, 10.0)
        self.assertEqual(cfg.call_deadline_s, 0.0)
        self.assertEqual(cfg.max_attempts, 3)
        self.assertEqual(cfg.backoff_base_s, 2.0)
        self.assertEqual(cfg.validation_rounds, 5)
        self.assertTrue(cfg.stream)
        self.assertTrue(cfg.stream_usage)
        self.assertEqual(cfg.heartbeat_s, 60.0)
        self.assertIsNone(cfg.max_tokens)

    def test_every_new_env_var_is_read(self):
        self._set_required()
        os.environ["ZIVON_API_KEY"] = "k"
        os.environ["ZIVON_TEMPERATURE"] = "0.7"
        os.environ["ZIVON_JSON_MODE"] = "false"
        os.environ["ZIVON_TIMEOUT_S"] = "600"
        os.environ["ZIVON_CONNECT_TIMEOUT_S"] = "3"
        os.environ["ZIVON_CALL_DEADLINE_S"] = "7200"
        os.environ["ZIVON_MAX_ATTEMPTS"] = "5"
        os.environ["ZIVON_BACKOFF_BASE_S"] = "1.5"
        os.environ["ZIVON_VALIDATION_ROUNDS"] = "7"
        os.environ["ZIVON_STREAM"] = "false"
        os.environ["ZIVON_STREAM_USAGE"] = "false"
        os.environ["ZIVON_HEARTBEAT_S"] = "30"
        cfg = LLMConfig.from_env()
        self.assertEqual(cfg.api_key, "k")
        self.assertEqual(cfg.temperature, 0.7)
        self.assertFalse(cfg.json_mode)
        self.assertEqual(cfg.timeout_s, 600.0)
        self.assertEqual(cfg.connect_timeout_s, 3.0)
        self.assertEqual(cfg.call_deadline_s, 7200.0)
        self.assertEqual(cfg.max_attempts, 5)
        self.assertEqual(cfg.backoff_base_s, 1.5)
        self.assertEqual(cfg.validation_rounds, 7)
        self.assertFalse(cfg.stream)
        self.assertFalse(cfg.stream_usage)
        self.assertEqual(cfg.heartbeat_s, 30.0)

    def test_max_tokens_has_no_env_var(self):
        # The factory never sets a completion cap (founder decision
        # 2026-11-04): an env value must be ignored, only code may set it.
        self._set_required()
        os.environ["ZIVON_MAX_TOKENS"] = "999"
        self.assertIsNone(LLMConfig.from_env().max_tokens)
        self.assertEqual(
            LLMConfig(base_url="http://x/v1", model="m", max_tokens=999).max_tokens, 999
        )

    def test_sanity_ranges_rejected_loudly(self):
        self._set_required()
        cases = [
            ("ZIVON_MAX_ATTEMPTS", "0"),
            ("ZIVON_VALIDATION_ROUNDS", "0"),
            ("ZIVON_TIMEOUT_S", "4"),
            ("ZIVON_TEMPERATURE", "9"),
            ("ZIVON_CALL_DEADLINE_S", "-1"),
            ("ZIVON_CONNECT_TIMEOUT_S", "0"),
            ("ZIVON_BACKOFF_BASE_S", "-2"),
            ("ZIVON_HEARTBEAT_S", "0"),
            ("ZIVON_TIMEOUT_S", "huge"),
            ("ZIVON_STREAM", "maybe"),
            ("ZIVON_MAX_ATTEMPTS", "2.5"),
        ]
        for key, value in cases:
            os.environ[key] = value
            with self.assertRaises(LLMConfigError, msg=f"{key}={value}"):
                LLMConfig.from_env()
            os.environ.pop(key)

    def test_base_url_scheme_guarded(self):
        os.environ["ZIVON_BASE_URL"] = "127.0.0.1:8080/v1"
        os.environ["ZIVON_MODEL"] = "m"
        with self.assertRaises(LLMConfigError) as ctx:
            LLMConfig.from_env()
        self.assertIn("http://", str(ctx.exception))


class TestValidationRounds(unittest.TestCase):
    def test_success_after_failures_with_errors_fed_back(self):
        outputs = ["not json at all", '{"topic": 42}', '{"topic": "fixed"}']
        schema = {
            "type": "object",
            "required": ["topic"],
            "properties": {"topic": {"type": "string"}},
        }
        transcripts: list[list[dict]] = []
        rejects: list[tuple[int, str]] = []

        def call_fn(round_no, transcript):
            transcripts.append([dict(m) for m in transcript])
            return outputs[round_no - 1], "stop"

        parsed = run_validation_rounds(
            call_fn,
            [{"role": "user", "content": "go"}],
            schema,
            "test",
            rounds=5,
            on_reject=lambda no, err: rejects.append((no, err)),
        )
        self.assertEqual(parsed, {"topic": "fixed"})
        self.assertEqual(len(transcripts), 3)
        # round 2's transcript carries the parse failure fed back
        self.assertIn("JSON parse failure", transcripts[1][-1]["content"])
        # round 3's transcript carries the schema violation fed back
        self.assertIn("Schema validation failed", transcripts[2][-1]["content"])
        self.assertIn("at 'topic'", transcripts[2][-1]["content"])
        self.assertEqual(rejects[0][0], 1)
        self.assertIn("not valid JSON", rejects[0][1])

    def test_finish_reason_length_is_a_validation_failure(self):
        schema = {"type": "object", "properties": {}}

        def call_fn(round_no, transcript):
            return '{"a": 1}', "length" if round_no == 1 else "stop"

        parsed = run_validation_rounds(
            call_fn, [{"role": "user", "content": "go"}], schema, "t", rounds=3
        )
        self.assertEqual(parsed, {"a": 1})

    def test_extra_validator_problems_are_fed_back(self):
        schema = {"type": "object", "properties": {"topic": {"type": "string"}}}
        outputs = ['{"topic": "bad-rule"}', '{"topic": "x"}']

        def call_fn(round_no, transcript):
            return outputs[round_no - 1], "stop"

        def validator(parsed):
            return ["[auto] invented figure"] if parsed["topic"] == "bad-rule" else []

        parsed = run_validation_rounds(
            call_fn,
            [{"role": "user", "content": "go"}],
            schema,
            "t",
            rounds=3,
            extra_validator=validator,
        )
        self.assertEqual(parsed, {"topic": "x"})

    def test_exhaustion_raises_validation_exhausted_error(self):
        schema = {
            "type": "object",
            "required": ["topic"],
            "properties": {"topic": {"type": "string"}},
        }

        def call_fn(round_no, transcript):
            return '{"topic": 42}', "stop"

        with self.assertRaises(ValidationExhaustedError) as ctx:
            run_validation_rounds(
                call_fn,
                [{"role": "user", "content": "go"}],
                schema,
                "my-schema",
                rounds=2,
            )
        message = str(ctx.exception)
        self.assertIn("my-schema", message)
        self.assertIn("all 2 validation rounds", message)
        self.assertIn("at 'topic'", message)

    def test_only_latest_rejected_output_stays_full(self):
        schema = {
            "type": "object",
            "required": ["topic"],
            "properties": {"topic": {"type": "string"}},
        }
        long_bad = "x" * 3000
        outputs = [long_bad, long_bad, long_bad, '{"topic": "ok"}']
        transcripts: list[list[dict]] = []

        def call_fn(round_no, transcript):
            transcripts.append([dict(m) for m in transcript])
            return outputs[round_no - 1], "stop"

        run_validation_rounds(
            call_fn, [{"role": "user", "content": "go"}], schema, "t", rounds=4
        )
        # round 4's transcript: round-1 and round-2 assistant outputs trimmed,
        # round-3 (the latest rejected) still full
        final = transcripts[3]
        assistant_contents = [m["content"] for m in final if m["role"] == "assistant"]
        self.assertEqual(len(assistant_contents), 3)
        self.assertEqual(
            len(assistant_contents[0]),
            1200
            + len(
                "\n... [earlier rejected output trimmed; the full text is in the "
                "attempt artifacts]"
            ),
        )
        self.assertIn("attempt artifacts", assistant_contents[0])
        self.assertIn("attempt artifacts", assistant_contents[1])
        self.assertEqual(assistant_contents[2], long_bad)


class TestPackageIsolation(unittest.TestCase):
    def test_llm_manager_never_imports_factory(self):
        # Standalone contract: the package (and its service) must be usable
        # without the factory. Checked in a fresh interpreter.
        code = (
            "import sys\n"
            "import llm_manager\n"
            "import llm_manager.service.app\n"
            "bad = [m for m in sys.modules if m == 'factory' or m.startswith('factory.')]\n"
            "assert not bad, bad\n"
            "print('ISOLATED')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ISOLATED", result.stdout)


if __name__ == "__main__":
    unittest.main()
