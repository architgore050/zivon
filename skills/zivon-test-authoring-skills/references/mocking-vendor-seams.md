# Mocking vendor seams

Zivon's tests never call Prisma, Timbre, Gemini, an OpenAI-format server, or a
real Postgres in CI. They replace those collaborators at a **seam** — a narrow
interface the production code already exposes — and assert what the code does
with the resulting events. This reference names the seams, the doubles that
already exist, and the rules that keep a fake honest.

## 1. Test-double vocabulary

Use the simplest double that can do the job. The terms are Gerard Meszaros'
(via Martin Fowler's [Test Double](https://martinfowler.com/bliki/TestDouble.html)
summary, accessed 2026-11-14):

| Double | What it does | Use here when |
|---|---|---|
| **Dummy** | Fills a parameter, never used | A constructor needs a collaborator the test never exercises |
| **Stub** | Returns canned answers | A dependency must return a fixed value |
| **Spy** | A stub that records calls | The call itself is part of the observable behaviour |
| **Mock** | Pre-programmed expectations, verified | You are asserting an interaction contract (send one request per segment) |
| **Fake** | A working shortcut implementation | You need realistic flow without the vendor (in-memory transport, SQLite) |

This repo prefers **fakes and scriptable doubles** over deep `unittest.mock`
chains. A fake that implements the real protocol catches shape drift; a
`MagicMock` accepts any call and catches nothing.

## 2. The seams in this repo

| Boundary | Production code | Seam | Existing double | What the double scripts |
|---|---|---|---|---|
| Prisma STT | `voice/stt_client.py` | `SttClient` surface used by `voice/ws_api.py` | `testing/voice/mocks/prisma.py::MockPrisma` | partials, final text/language/confidence, `fail_connect`, `die_after`, final delay |
| Gemini / OpenRouter brain | `voice/brain_client.py` | `BrainClient` transport factory yielding `RawChunk` | `testing/voice/mocks/brain.py::MockBrain` | content lines, thoughts, usage, chunk delay, first-event delay, stall, `fail_times`, `hang_forever`, `closed` (the upstream saw the abort) |
| Timbre TTS | `voice/tts_client.py` | `TtsTransport` protocol (`send`/`recv`/`close`) | `FakeTimbreTransport` in `testing/voice/test_tts_client.py`; `MockTimbre` at the client surface | binary or base64 audio frames, `segment_end`/`complete`, dead stream, abort drain |
| Factory / llm-manager HTTP | `llm_manager/`, `factory/llm.py` | OpenAI-format `/chat/completions` | `testing/content_factory/mocks/openai_mock.py` | SSE deltas, usage, finish reason, 500/400/bad-shape/slow/stall/mid-stream-close/stream-error, disconnect accounting |
| Eval judge | `evals/judges/` via `llm_manager` | `EvalConfig.judge_llm_config()` | `--mock` calibrated fake judge | deterministic verdicts for smoke/calibration |
| Database | `db/engine.py` | `DatabaseEngine.from_url(...)` | SQLite in memory; Postgres 16 service in CI | rows, transactions, migration chain |
| WebSocket endpoint | `voice/ws_api.py` | Starlette `WebSocket` | `FakeWebSocket` in `testing/voice/test_ws_api.py` | inbound frames, query string, origin, outbound capture |
| HTTP app | `backend/`, `dashboard/` | FastAPI `TestClient` | `TestClient(app)` | requests, auth, headers, status codes |
| Clock | `voice/chunker.py`, `voice/tts_client.py`, mocks | injected `clock: Callable[[], float]` | `FakeClock` in the test | monotonic time, flush deadlines, first-audio measurement |
| Environment | config loaders | `os.environ` | `mock.patch.dict(os.environ, ..., clear=False)` | config precedence; restore after the test |

## 3. Rules

1. **Mock at the seam you own, not the thing under test.** Testing
   `TtsClient`? Fake `TtsTransport`, keep `TtsClient` real. Replacing
   `MockTimbre` for a `TtsClient` test would replace the code under test with
   its own double.
2. **The fake implements the real interface.** Use the actual `Protocol` or
   exception type (`TtsTransport`, `TtsUnavailableError`, `BrainHTTPError`).
   If the interface changes, the fake must fail to type-check or fail loudly,
   not quietly accept the old shape.
3. **The fake returns the vendor shape, not the parser's wish.** For example,
   Timbre v3.0 sends base64 audio inside JSON and terminates with `complete`;
   the mock must exercise that shape (`test_realtime_base64_audio_and_complete`),
   not only the convenient binary one.
4. **Script the failure.** A double that can only succeed turns the failure
   path into an untested claim. The repo's doubles already expose the knobs:
   `fail_connect`, `die_after`, `fail_times`, `hang_forever`,
   `__fail500`, `__fail400`, `__badshape`, `__slow`, `__stall`,
   `__midstream_close`, `__stream_error`.
5. **Make recovery provable.** Failure injections are one-shot where the
   behaviour is "retry then recover", so the test can prove the retry worked.
   Always-400 is non-retryable by design; do not "fix" it by adding a retry.
6. **Assert outcomes, not the mock's diary.** Assert the emitted frames, the
   persisted row, the returned typed error, the page state. Assert a call only
   when the call *is* the contract ("one synthesis request per segment").
7. **Record what the real thing would have seen.** `MockBrain.closed` proves a
   deadline abort actually closed the server side; `MockTimbre.spoken` proves
   the text that would be billed. Use those recordings as evidence.
8. **No global patching.** Patch the narrow seam. Do not patch
   `time.monotonic`, `asyncio.sleep`, or a module-level singleton; inject a
   clock or a fake instead.
9. **Restore everything.** Use `addCleanup`, context managers, and
   `mock.patch.dict(..., clear=False)`; never leave env vars, files, or sockets
   behind.

## 4. Fake clocks

Deadlines are behaviour, so they must be tested without waiting. Inject a
clock and advance it:

```python
class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds
```

```python
clock = FakeClock()
chunker = SentenceChunker(SegmentIds(), clock=clock)
chunker.feed("Pehla vaakya.")
clock.advance(0.3)
chunks = chunker.flush()
```

Rules:

- **Inject, don't patch.** The production classes already take `clock=`
  (`SentenceChunker`, `TtsClient`, `MockBrain`, `MockPrisma`). Use it.
- **Assert virtual time.** `first_audio_s` should equal the clock delta the
  test advanced, not a flaky wall-clock number.
- **`asyncio.wait_for` is a deadlock guard, not a latency assertion.** A short
  timeout is acceptable to stop a hung suite; do not assert a vendor latency
  with it. The latency contract is the CSV sum in
  `testing/voice/test_latency_budget.py`.
- **No `time.sleep`.** If a test needs to wait for a state change, drive the
  event (queue, event, fake clock) or use a web-first assertion in the browser.

## 5. SQLite and Postgres parity

SQLite is the default for unit and backend tests because it is in-process,
fast, and hermetic. It is **not** Postgres. Treat it as a fake for repository
mechanics, not as proof of production database behaviour.

| Difference | What to do |
|---|---|
| Placeholder syntax (`?` vs `%s`) | The repo's `_TransactionCursor` adapts `?` to `%s`; test both dialect branches if you touch it |
| `ON CONFLICT`, `RETURNING`, JSON operators, partial indexes, `FOR UPDATE`, `INTERVAL` | Add a Postgres-gated test; do not assume SQLite accepts it |
| Type affinity and `TIMESTAMPTZ` | Assert the stored value and timezone shape on the dialect you ship |
| Concurrency and locking | SQLite in-memory cannot prove row-lock or transaction-isolation behaviour; use the CI Postgres service or a concurrency test with its own engine |
| Migration chain | The `db-migrations` CI job runs `alembic upgrade head` twice against Postgres 16 and asserts one head == current; a SQLite run is not a substitute |

Pattern for a Postgres-gated test:

```python
import os
import unittest

POSTGRES_URL = os.environ.get("ZIVON_DB_URL", "")


@unittest.skipUnless(
    POSTGRES_URL.startswith("postgresql"), "needs the CI Postgres service"
)
class PostgresDialectTest(unittest.TestCase):
    def test_on_conflict_is_supported(self) -> None: ...
```

The skip is honest: it names the missing dependency and is reported as
skipped, never as passed. In CI the job provides the throwaway Postgres service
and `ZIVON_DB_URL`; locally the test skips unless you provide one.

**Rule of thumb:** if the bug you are fixing is "the SQL works on SQLite but
fails on Postgres", the regression test must run on Postgres. A SQLite test
would be green on the broken code, which is worse than no test.

## 6. Contract tests at a seam

A contract test is a unit-shaped test whose subject is the interface, not the
algorithm. It should survive a refactor of the adapter's internals but fail if
the wire shape, error mapping, or lifecycle changes.

**Checklist for a new adapter or vendor:**

- [ ] The public method signature and return type are asserted (the fake is
      typed against the real `Protocol`).
- [ ] One happy-path payload with the documented fields, types, and enums.
- [ ] One streaming-order assertion: first event before completion, final
      marker last, no frame after `final`.
- [ ] One error mapping: vendor error becomes the repo's typed error; the
      caller can degrade (F1/F2/F4 paths).
- [ ] One lifecycle: close/abort leaves no socket, task, or temp file.
- [ ] One usage/meter assertion if the adapter bills or counts.
- [ ] A dated live-probe note in the owning spec, if the vendor contract is
      still an assumption (for example OQ-03 for Timbre).

## 7. Anti-patterns

| Pattern | Why it fails |
|---|---|
| `MagicMock()` with no spec, asserted by call count | Accepts any shape; proves only that the test called something |
| Patching a private method (`_send`, `_open`) | Couples the test to internals; the refactor breaks the test, not the bug |
| Patching `time.monotonic` globally | Other tests and libraries see the fake; leaks across the suite |
| The mock returns the parser's output shape | The adapter looks correct against a shape the vendor never sends |
| Only the happy path is scripted | Retry/degrade paths are the reason the doubles exist |
| Asserting `mock.assert_called_once()` as the only check | The test would pass if the return value were discarded or wrong |
| A fake that swallows exceptions | Failures look like success; the suite loses its alarm |
| A shared double instance across tests | Order dependence and hidden state |
| A real client with only the HTTP layer faked but real retry sleeps | Slow, nondeterministic, and not a unit test |
