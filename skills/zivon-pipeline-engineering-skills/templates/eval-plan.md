# Eval plan

Fill this in for any change that affects model/prompt/content quality. A
deterministic code change may not need a new card; say why in the PR.

## 1. The change and the failure mode

- **Stage/agent:**
- **Change:**
- **New or changed failure mode:** (the specific defect this must catch, not
  "quality")
- **Evidence it exists:** run id / artifact / incident
- **What would regress if this change is wrong:**

## 2. Card

- **Card id:** `EV-<PREFIX>-<NNN>` (existing or new)
- **If new, is the stage/role in `evals/models.py`?** yes / needs the additive
  schema extension
- **Suites:** `smoke` (deterministic) / `full` / `calibrate`
- **Cost budget:** smoke model calls `0`; full calls per topic; max completion
  tokens; call deadline

## 3. Deterministic checks (run first, zero model calls)

| Check id | What it asserts | Reuses factory rule/schema | Fatal? |
|---|---|---|---|
| | | `factory.checks::...` | |

- **Short-circuit:** a fatal checker failure skips the judge.
- **False-fatal risk:** what could it wrongly reject? How is that calibrated?

## 4. Judge (only if judgement is required)

- **Rubric source:** reuse `factory/agents.py::run_check` /
  `factory/review.py` verbatim? If not, why?
- **Context given:** exactly which artifacts; what is deliberately excluded
- **Severity ladder:** fatal / major / minor / `unverified:`
- **Anchor examples:** one per severity
- **Bounded procedure:** yes/no
- **Verdict owner:** harness code (fail iff any fatal), not the model

## 5. Goldens

- **Topic goldens:** `evals/goldens/topics/<slug>/expected.json` invariants
- **Seeded defects:** `evals/goldens/defects/<stage>/<id>.json`
- **Clean control:** which clean golden proves specificity
- **Registered in `evals/goldens/manifest.json`:** yes/no
- **Baseline:** previous run id / previous expected values

## 6. Thresholds and regression

- Deterministic pass rate:
- Fatal recall:
- Clean specificity:
- Max major/minor:
- Perf budget (if applicable):
- Thinking guard (max completion tokens / `length_cuts`):
- Human edit rate target (if applicable):
- Regression alert: what flips to fail; `--fail-on-regression` behavior

## 7. Commands and evidence

```bash
python -m unittest discover -s testing/evals -t .
python -m evals run --suite smoke --mock
python -m evals run --suite smoke --fail-on-regression
python -m evals calibrate --stage <stage> --mock
# live (authorized window only)
python -m evals run --suite full
```

- **Run id:**
- **`eval_summary.md` path:**
- **Ledger row present:** `evals_runs/eval_runs_ledger.jsonl`
- **Relational mirror / outbox:** yes/no/n/a
- **PR link:** run id + summary

## 8. Known gaps

- The eval card schema is closed; does this need `EV-ASM/EXM/SER` or a new
  stage/role enum?
- Are `EVT-EVAL-*` map rows present? If not, this run is not in the curation
  front.
- Is `pipeline_version` recorded correctly (`evals/runner.py` currently
  hardcodes `1`)?
- Any golden staleness or unregistered input?

## 9. Decision

- **Verdict:** evaluate / defer with reason / no eval needed (why)
- **Debt logged:**
- **Owner for the follow-up:**
