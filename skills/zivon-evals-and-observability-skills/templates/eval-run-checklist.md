# Eval run checklist

Copy into the PR description or the run log. Fill every line; "n/a" needs a reason.

## Pre-flight (before spending a run)

```text
[ ] Card id is in the closed prefix set; stage and agent_role are in the enum
[ ] suites includes smoke and the card has >= 1 deterministic checker
[ ] cost_budget.smoke_model_calls == 0
[ ] Every golden_inputs.topics path exists with expected.json + source_pack_meta.json + artifact_ref.json
[ ] Every golden topic is registered in evals/goldens/manifest.json
[ ] Every deterministic checker is importable and reuses a named factory rule
[ ] No checker returns [] for missing data without writing context["skipped_checks"]
[ ] A judge (if any) reuses the factory rubric verbatim and has fatal/major/minor anchors
[ ] No child PII, transcript, prompt, answer, audio, or secret in any fixture
[ ] The persistent counts in testing/evals/ are updated (cards 9, topics 4, defects 19, checks 24
    at 2026-11-14; verify current values)
```

## Key-free run

```bash
python -m evals run --suite smoke --mock
python -m evals run --suite smoke --fail-on-regression
python -m unittest discover -s testing/evals -t .
```

```text
[ ] Smoke verdict: PASS / FAIL
[ ] Model calls: 0
[ ] Regression gate exit code: 0
[ ] testing/evals: N/N OK
```

If you used `--card`, confirm `--mock` was present: `--card` forces the judge path even in
`smoke`.

## Persistence check

```bash
tail -1 evals_runs/eval_runs_ledger.jsonl
ls evals_runs/<eval_run_id>/
```

```text
[ ] eval_run_id: ________________________________
[ ] Ledger row present: yes/no
[ ] eval_report.json present: yes/no
[ ] eval_summary.md present: yes/no
[ ] eval_metrics.prom present: yes/no
[ ] eval_diff.json present (if --fail-on-regression): yes/no/n/a
[ ] Relational mirror written (if DB configured): yes/no/n/a
[ ] Outbox bundle written (if the store degraded): path or n/a
[ ] EVT-EVAL-* names resolve to map rows: yes/no (open P-GAP-14 if no)
```

## Live run (only in an authorised infra window)

```text
[ ] Authorised by: founder / infra owner
[ ] Endpoint/model: ________________________________
[ ] Suite: full / calibrate        [ ] Cards/topics selected: ________________
[ ] Model-call budget respected (card cost_budget + run summary)
[ ] Calibration metrics (fatal recall, clean specificity) recorded if a reviewer changed
[ ] Run id: ________________________________
```

## Evidence bundle (paste into the PR)

```markdown
## Evals
- Run id: `eval-...`
- Suite: `smoke` (mock) / `full` / `calibrate`
- Verdict: PASS / FAIL
- Regression: `python -m evals run --suite smoke --fail-on-regression` -> clean / exit 2
- Artifacts: `evals_runs/<eval_run_id>/eval_summary.md` (linked/attached)
- Model calls: 0 (smoke) / N (full)
- Baseline: `eval-...` (or "first run")
- Known debt: <list or "none">
```

## Post-merge

```text
[ ] The baseline the next run will compare against is this run id
[ ] Any deliberate baseline change is explained in the PR
[ ] The card/checker/golden docs are updated (spec.md card table, golden-sets.md if needed)
[ ] Any telemetry the run emits is declared in the instrumentation map (or the gap is recorded)
```
