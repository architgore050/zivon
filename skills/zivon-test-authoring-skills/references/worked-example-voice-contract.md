# Worked example: a streaming contract test for the voice TTS client

This is the full workflow on a real seam. The code is illustrative — the test is
not added by this bundle — but every path, class, and method named here exists
in the repo at the evidence date.

## 1. Name the behaviour and the failure

**Behaviour:** `voice.tts_client.TtsClient.speak()` is a streaming async
generator. The first audio frame must be yielded as soon as it arrives, before
the segment's `segment_end`/`complete` marker. `meters.first_audio_s` is
measured from `start_turn()`.

**Failure if it breaks:** a refactor that accumulates frames and yields them
only at `segment_end` turns a streaming tutor into a batch one. The student
waits for the full answer before hearing anything, and Gate C's
end-of-speech → first-audio budget collapses. The existing tests that drain the
whole iterator and check the final list stay green, so the regression is
invisible.

**Why it matters:** Gate C is < ~4 s end-of-speech → first spoken audio. The
streaming contract is the mechanism that makes the budget possible.

## 2. Choose the layer and the seam

- **Layer:** contract/unit. No browser, no network, no model.
- **Seam:** `TtsTransport` (`send`/`recv`/`close`), injected through the
  `connect_factory` argument. `TtsClient` stays real; the vendor transport is
  the double.
- **Why not `MockTimbre`:** `MockTimbre` replaces the client surface. Using it
  here would replace the code under test with its double.
- **Clock:** inject a `FakeClock` so `first_audio_s` is exact and the test does
  not wait.

## 3. Build the fixture

The fixture is a transport whose `recv()` blocks until the test releases a
frame. That is what makes "the first frame arrived before the segment ended"
observable: the segment cannot end until the test says so.

```python
from __future__ import annotations

import asyncio
import unittest

from voice.config import VoiceSettings
from voice.tts_client import TtsClient, TtsTransport


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


class GatedTransport:
    """A TtsTransport whose recv() waits until the test releases a frame."""

    def __init__(self) -> None:
        self.sent: list[str | bytes] = []
        self.frames: asyncio.Queue[str | bytes] = asyncio.Queue()
        self.closed = False

    async def send(self, data: str | bytes) -> None:
        self.sent.append(data)

    async def recv(self) -> str | bytes:
        return await self.frames.get()

    async def close(self) -> None:
        self.closed = True
```

There is no file fixture and no network. The queue is the fixture; the fake
clock is the time source.

## 4. Write the test

```python
class TtsStreamingContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_first_frame_is_yielded_before_segment_end(self) -> None:
        clock = FakeClock()
        transport = GatedTransport()

        async def connect() -> TtsTransport:
            return transport

        settings = VoiceSettings(
            tts_url="wss://timbre.invalid",
            gnani_tts_api_key="test-key",
        )
        client = TtsClient(settings, connect, clock=clock)
        await client.start_turn()
        iterator = client.speak("Pehla vaakya.", 1)

        clock.advance(0.25)
        await transport.frames.put(b"frame-1")
        first = await asyncio.wait_for(anext(iterator), timeout=1.0)

        self.assertEqual(first.data, b"frame-1")
        self.assertFalse(first.final)
        self.assertEqual(len(transport.sent), 1)
        self.assertEqual(client.meters.first_audio_s, 0.25)

        await transport.frames.put(b"frame-2")
        await transport.frames.put('{"type": "segment_end"}')
        rest = [frame async for frame in iterator]

        self.assertEqual([frame.data for frame in rest], [b"frame-2", b""])
        self.assertTrue(rest[-1].final)
```

What the test asserts, and why:

- **First frame, not the final list.** `anext(iterator)` must return while the
  segment is still open. A buffering implementation blocks here.
- **The request was sent.** `len(transport.sent) == 1` proves the synthesis
  request went out before the first frame, so the test is not accidentally
  observing a pre-queued fake.
- **The meter's source.** `first_audio_s == 0.25` is the virtual clock delta
  from `start_turn`, not a wall-clock approximation.
- **The end of the stream.** The final marker is last and `final=True`; the
  client did not drop the tail after the first frame.

`asyncio.wait_for(..., timeout=1.0)` is a **deadlock guard**, not a latency
assertion. The timeout is generous and exists only so a broken implementation
fails the test instead of hanging CI.

## 5. Prove it can fail

Mutate `TtsClient.speak()` in a scratch copy to buffer before yielding:

```python
# Mutation: collect everything, then yield.
frames: list[TtsAudio] = []
while True:
    raw = await self._ws.recv()
    # ... parse into `audio` ...
    frames.append(audio)
    if final:
        break
for frame in frames:
    yield frame
```

Run the test. `asyncio.wait_for` raises `TimeoutError` because the first frame
is not yielded until `segment_end`, which the test has not sent. The test is
red for the right reason. Restore the code and it is green.

For a real regression fix, run the new test against the base commit first. It
must fail there; then apply the fix and watch it pass.

## 6. Run the checks

```bash
python -m unittest testing.voice.test_tts_client
python -m unittest discover -s testing/voice -t .
ruff check testing/voice/test_tts_client.py
ruff format --check testing/voice/test_tts_client.py
mypy --ignore-missing-imports testing/voice voice
```

If the test is added to the shared suite, run the whole voice set; a new fake
should not disturb the existing `FakeTimbreTransport` tests.

## 7. Review it against the checklist

| Check | Result |
|---|---|
| Right layer | Contract test at the transport seam; no browser, no network |
| Seam | `TtsClient` real; `TtsTransport` faked; `MockTimbre` deliberately not used |
| Determinism | Queue + fake clock; `wait_for` is a deadlock guard only |
| Fault detection | The buffering mutation turns it red |
| Refactor resilience | Asserts frames, request count, and meter; not private methods |
| Failure clarity | The test name states the contract; the timeout is the symptom |
| Hygiene | No file fixture; no cleanup needed beyond the client's own close |
| Docs | The voice spec §13 owns the TTS contract suite; add a row only if you treat first-frame ordering as a new contract |

## 8. What this test deliberately does not prove

- **The vendor wire shape.** That is
  `test_realtime_base64_audio_and_complete` (base64 audio inside JSON,
  terminated by `complete`) and the OQ-03 live probe.
- **The latency budget.** That is
  `testing/voice/test_latency_budget.py`, which asserts the CSV sum, not a
  wall-clock measurement.
- **Audio quality or pronunciation.** That is a manual/live check with Gnani
  voices, not a deterministic test.
- **Barge-in drain.** That is
  `test_abort_drains_old_segment_before_next_turn`; it belongs to the abort
  path, not the first-frame path.

A test that tries to prove all of these at once is slow, flaky, and hard to
diagnose. Split by contract.

## 9. The same pattern elsewhere

- **WebSocket ordering.** `testing/voice/test_ws_api.py` proves the highlight
  message is emitted before the first audio frame and that the first chunk is
  dispatched while the brain is still streaming. The `FakeWebSocket` is a
  queue-backed Starlette double; the endpoint coroutine is real.
- **Chunker flush deadline.** `testing/voice/test_chunker.py` injects a fake
  clock and advances it past 250 ms; it never sleeps.
- **Brain first-event deadline.** `testing/voice/test_brain_client.py` scripts
  a delay before the first event and asserts the typed failure, using the mock
  brain's timing knobs.

## 10. Anti-patterns in this area

| Pattern | Why it fails |
|---|---|
| `MockTimbre` used to test `TtsClient` | Replaces the code under test with its double |
| `await asyncio.sleep(0.1)` then check a list | Slow, flaky, and does not prove the order |
| `mock.patch("voice.tts_client.time.monotonic")` | Global clock patch leaks into other tests; inject the clock |
| Asserting the full JSON request as a snapshot | Every unrelated field change reddens the test; assert the contract fields |
| Draining the iterator, then `frames[0]` | The buffering regression still passes |
| Asserting `transport.sent` only | Proves a request was sent, not that audio streamed back |
| A timeout used as the latency assertion | Runner speed decides the verdict; assert the virtual clock or the budget CSV |
| A fake that returns a different shape than the vendor | The adapter looks correct against a shape Timbre never sends |
