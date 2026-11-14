# Test plan: `<change or feature>`

Copy this plan into the PR description or the work note when a change spans
more than one behaviour or layer. Delete rows that do not apply; do not leave a
blank one.

## 1. Change summary

- **What changed:** `<one paragraph>`
- **Why:** `<bug, feature, contract change>`
- **Risk if untested:** `<student/operator-visible failure>`
- **Contracts touched:** `<paths, specs, ADRs>`

## 2. Behaviours and failures

| # | Behaviour | If it breaks, the observable is | Risk |
|---|---|---|---|
| 1 | `<e.g. first audio frame streams before segment end>` | `<student waits for full answer>` | high |
| 2 | `<...>` | `<...>` | medium |

## 3. Layer selection

For each behaviour, pick the cheapest layer that can see the break. Justify any
layer above unit.

| # | Layer | Seam / real dependency | Why this layer |
|---|---|---|---|
| 1 | unit / contract / integration / browser / a11y / perf | `<TtsTransport fake>` | `<no browser needed; the break is in the adapter>` |
| 2 | `<...>` | `<...>` | `<...>` |

## 4. Doubles and fixtures

| Need | Existing double / fixture | New? | Notes |
|---|---|---|---|
| Vendor transport | `<MockBrain / MockTimbre / openai_mock / FakeWebSocket>` | no | `<scripted failure>` |
| Clock | `<FakeClock>` | yes | `<advance 0.25 s>` |
| Input artifact | `<fixture path>` | no | `<schema-valid>` |
| DB | `<SQLite in memory / Postgres service>` | no | `<mechanics only>` |

## 5. Golden / eval boundary

- Is any part of this a judgement about model output, prompt quality, reviewer
  calibration, or generated-page quality? `<yes/no>`
- If yes, the eval card is `<EV-...>` and the run id is `<id>`. Do not put the
  judgement in a unit test.
- If no, state why the deterministic check is sufficient: `<reason>`.

## 6. Commands and expected result

```bash
python -m unittest discover -s testing/<area> -t .
python -m unittest testing.<area>.<module>
ruff check .
ruff format --check .
mypy --ignore-missing-imports <paths>
```

Expected: `<N/N OK>`. A skipped test is reported as skipped, with the reason.

## 7. Failure proof

- Mutation that turns each new test red: `<flip condition / buffer frames / drop field>`
- For a bug fix: base commit result `<red>`, fixed result `<green>`.
- Evidence: `<command output, commit sha, or PR link>`.

## 8. Out of scope

- `<behaviour deliberately not tested now>`
- Reason: `<no seam / live vendor / covered by eval / low risk>`
- Follow-up: `<link or "none">`

## 9. Docs

- [ ] `testing/README.md` row added or updated.
- [ ] Owning spec updated (`docs/specs/...`) if a contract changed.
- [ ] No doc claims a guarantee the tests do not enforce.

## 10. Final checklist

- [ ] Every behaviour has a test or a recorded reason it does not.
- [ ] No network, key, sleep, wall clock, or order dependence.
- [ ] Fixtures are tracked, minimal, and free of learner data.
- [ ] The new tests fail under a named mutation.
- [ ] The suite passes alone and as a folder.
- [ ] Lint, format, and types are clean.
