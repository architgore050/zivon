# testing/observability - the EX3-OBS observability test set

Covers the `logging_manager` contract (`docs/specs/observability/logging-api.md`),
its instrumentation call sites in `factory/` + `llm_manager/`, and the admin
dashboard (`dashboard/`, ADR-0026 auth). Run from the repo root:

    python -m unittest discover -s testing/observability -t .

All tests need NO API keys and NO running Postgres: store-dependent paths are
exercised through stub connections / the JSONL fallback, which is the point —
the fallback IS the always-works path.

| File | What it pins |
|---|---|
| `test_redaction.py` | every key-denylist pattern, every value-regex kind, the sanctioned reference-field allow, shape guard, `log.redaction_violation` shape + first-plus-every-100th dedup |
| `test_schema.py` | JSON line v1 (field order, ms-precision UTC ts, order-insensitive `fields`), closed enums, env/level config, dev-mode programmer errors, delivery that never raises |
| `test_context.py` | `bind_context` / `context_scope` / `current_context`, asyncio task inheritance + isolation, thread isolation, `X-Request-Id` / `X-Zivon-*` receive + propagate rules |
| `test_sinks.py` | stdout always, byte-identical `YYYYMMDD-<component>.jsonl` fallback, one-retry-then-loud-fallback + recovery events, DEBUG filtering at emit, `delete_subject` fallback rewrite + audit, verify-then-drop checksum gate |
| `test_events.py` | instrumentation-map conformance: the map parses, every emitted name resolves to a row with the declared severity/component, the frozen public surface and exact `log_event` signature |
| `test_store.py` | export manifest + checksum roundtrip, idempotent fallback ingestion, L3 set derived from the map, retention constants, CLI refuses without a DSN |
| `test_dashboard.py` | endpoints against a seeded stub store: fail-closed 503, login/lockout/CSRF flows, honest empty states, security headers + `X-Request-Id` echo, the two buttons (script semantics, CSRF, manual-only concurrency refusal) |
| `test_factory_events.py` | the factory/node call sites emit the map's rows: stage transitions via `mark_stage`, content-free reason codes, `call_intent` enum, deadline/server-reported markers on TransportErrors |

Weakens-a-test policy: these tests ARE the redaction/retention guarantees
(spec.md §4.5). A PR that loosens one fails review by the tests lens — same
rule as the rest of the repo's harness guarantees.
