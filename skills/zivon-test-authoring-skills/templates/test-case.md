# Test case: `<scenario>_<expected>`

Use this when writing a new test module or turning a vague test into one
behaviour. The headings are the review questions; keep them even if the code is
short.

## Contract

- **Test name:** `test_<scenario>_<expected>`
- **Behaviour in one sentence:** `<when X happens, Y is observed>`
- **If it breaks, the user sees:** `<observable>`
- **Layer:** unit / contract / integration / browser / a11y / perf
- **Seam:** `<real collaborator kept>` / `<double used>`

## Skeleton

```python
from __future__ import annotations

import unittest


class ExampleTest(unittest.TestCase):
    def test_rejects_expired_token(self) -> None:
        # Arrange: the smallest state that makes the behaviour reachable.
        token = make_token(expires_at=100)

        # Act: one call, one action.
        result = validate_token(token, now=101)

        # Assert: the observable, named in the message.
        self.assertEqual(
            result.reason,
            "expired",
            "an expired token must be rejected with reason='expired'",
        )
```

## Determinism

- [ ] No network, API key, model call, or vendor socket.
- [ ] No `time.sleep`, `page.wait_for_timeout`, or unpinned wall clock.
- [ ] No unseeded randomness, locale, timezone, or hostname dependency.
- [ ] Temp dir / DB / server / browser context is unique and cleaned up.
- [ ] The test passes alone, repeated, and in a different order.
- [ ] Environment variables restored after the test.

## Failure proof

- **Mutation that must turn this red:** `<flip condition / return constant / drop field / buffer stream>`
- **Observed red output:** `<assertion / timeout>`
- **Restored green:** `<yes>`

For a bug fix, the test must fail on the base commit. Paste the red evidence in
the PR.

## Assertions

- **What is asserted:** `<returned value / persisted row / emitted message / rendered DOM / frame order>`
- **What is deliberately not asserted:** `<private method / call count / exact wording>`
- **Failure message:** `<names the contract and the actual value>`

## Fixtures

- **Input:** `<path or builder>`
- **Provenance:** `<hand-written / captured from run id / public-domain source>`
- **Writes:** `<temp dir only>`
- **Cleanup:** `<TemporaryDirectory / addCleanup / finally>`

## What this test does not prove

- `<vendor wire shape>` — covered by `<other test>`
- `<latency>` — covered by `<budget test>`
- `<teaching quality>` — covered by `<eval card>` or a manual gate

## Review pass

- [ ] One behaviour; the name does not need "and".
- [ ] The double is at a seam; the thing under test is real.
- [ ] The assertion is observable, not a mock's diary.
- [ ] A named mutation makes it fail.
- [ ] The failure message identifies the contract.
- [ ] Lint, format, and types pass.
