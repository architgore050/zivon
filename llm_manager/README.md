# llm_manager

The shared, generalized OpenAI-format model-call module. One package, two
faces:

1. **A library** (`llm_manager` itself): streaming chat calls with honest
   timeout semantics, a per-call wall-clock deadline that can abort a runaway
   generation mid-stream, transport retries, and reusable validation rounds
   with errors fed back to the model.
2. **A service node** (`llm_manager/service/`): the same package behind a
   small FastAPI app, shipped as its own image (`Dockerfile.llm-manager`) and
   running as an isolated K8s **Deployment + Service** (`k8s/16-llm-manager.yaml`).
   Every consumer talks to THIS node over plain OpenAI chat-completions HTTP;
   the node is the only thing that talks to the inference server (through the
   dev inference router in container/cluster setups). The factory's Job points
   its `ZIVON_BASE_URL` at the node's Service; a future translation service
   would do exactly the same.

Who uses it today: the content factory (`factory/llm.py` is a thin adapter;
all stage call sites are untouched). Tomorrow: the translator, or any service
that needs model calls without hand-rolled HTTP. The voice agent is
deliberately OUT of scope - voice streaming is a different domain (real-time
audio chunking, barge-in, partial transcripts), not this request/response
contract.

## Why streaming is the default

A non-streaming response sends zero bytes until generation ends, so a read
timeout cannot distinguish "thinking" from "dead" from "rambling forever" -
and a runaway generation is unkillable (the 2026-11-07 incident: 3,592 s per
attempt, 77,921 -> 131,445 -> 199,056 tokens across three tries, the client
read-timing-out at 3,600 s each time while the server's single slot burned).
With streaming, bytes flow as tokens are generated: inactivity between chunks
is an honest dead-server signal, and the deadline can close the connection
mid-generation, which makes the server STOP and frees the slot.

## Failure semantics (no silent fallbacks, ever)

- Inactivity between chunks → retryable transport failure (up to `max_attempts`).
- `call_deadline_s` breach → the stream is closed mid-generation; terminal
  TransportError naming the deadline and the chunk count.
- 429/5xx exhausted → TransportError; non-retryable 4xx → NonRetryableHTTPError
  with the server's body and a copy-pasteable hint.
- HTTP 200 + an SSE `{"error": ...}` payload (the server reporting failure
  inside the stream - llama.cpp context-overflow style, and how the service
  node relays its own exhausted upstream) → terminal TransportError with the
  server's own words preserved; never retried.
- Malformed response shape → BadServerResponseError.
- While the node's upstream is silent (a thinking model streams reasoning
  deltas that are deliberately not re-emitted as content), the node emits SSE
  comment keepalives (`: keepalive`) so the caller's inactivity timeout stays
  honest - OpenAI-format parsers ignore comment lines per spec.

## Library usage

```python
from llm_manager import LLMConfig, LLMManager, TransportError
from llm_manager.validation import run_validation_rounds

config = LLMConfig.from_env()  # ZIVON_BASE_URL, ZIVON_MODEL, ...
manager = LLMManager(config)

# one-shot structured call with validation rounds
result = manager.complete(
    [{"role": "user", "content": 'Return {"ok": true} as JSON'}],
    temperature=0.2,
)
print(result.text, result.usage, result.first_token_s, result.chunks_received)

# incremental output (a future translator)
for delta in manager.stream([{"role": "user", "content": "Summarize this..."}]):
    print(delta, end="", flush=True)
```

A translator-shaped consumer with schema validation:

```python
from llm_manager import ValidationExhaustedError, run_validation_rounds

TRANSLATION_SCHEMA = {
    "type": "object",
    "required": ["lines"],
    "properties": {"lines": {"type": "array"}},
}


def translate(lines: list[str]) -> dict:
    messages = [{"role": "user", "content": "\n".join(lines)}]

    def call(round_no, transcript):
        result = manager.complete(transcript)
        return result.text, result.finish_reason

    try:
        return run_validation_rounds(
            call,
            messages,
            TRANSLATION_SCHEMA,
            "translation",
            rounds=config.validation_rounds,
        )
    except ValidationExhaustedError as exc:
        ...  # surface to the caller; the transcript proved what was attempted
```

## Configuration

Every knob is a constructor argument; `LLMConfig.from_env()` reads the same
names from the environment (see `docs/content-factory/config-reference.md`
and `.env.example` for the full table). `max_tokens` is constructor-only by
design - no environment variable (founder decision 2026-11-04: the factory
sends no completion cap).

## Isolation rules (enforced by tests)

- `llm_manager` imports NOTHING from `factory/`.
- `llm_manager` prints nothing; observability flows through the observer
  hooks and the returned result objects.
- No local token counting (tiktoken is offline-hostile); usage comes only
  from the server's reported usage.
- Transport retries (`max_attempts`) and validation rounds
  (`validation_rounds`) are separate budgets that never consume each other.
