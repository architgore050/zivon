# Pipeline debug log

One run, one log. Quote evidence; do not paraphrase a model output from memory.
Attach this to the PR or the incident note.

## 1. Run

- **Command:**
- **Run id:**
- **Chapter / class / locales:**
- **Pipeline version:**
- **Model / endpoint (name only, no key):**
- **Environment:** local / compose / cluster
- **Started / failed at:**
- **Operator:**

## 2. Symptom

- **What the operator saw:** (exact error/line)
- **First failing stage:**
- **Is it a gate failure, a catcher exhaustion, a config/resume guard, or an
  unexpected crash?**
- **Did it publish anything?** yes/no

## 3. Evidence read

| Artifact | Path | What it showed |
|---|---|---|
| `status.json` | | |
| `run_report.json` | | |
| stage `output.json` | | |
| `attempts/*/request.json` | | |
| `attempts/*/response.json` | | |
| `attempts/*/meta.json` | | |
| `combined-*.json` / history | | |
| `calls_ledger.jsonl` | | |
| `issues_ledger.jsonl` | | |

## 4. Timeline

| Time | Stage/round | Event | Evidence |
|---|---|---|---|
| | | | |

## 5. Diagnosis

- **Failure class:** (`transport`, `schema`, `gate`, `catcher_plateau`,
  `budget`, `lint`, `config`, `infra`, `other`)
- **Root cause (confirmed / likely / suspected):**
- **Why the existing guard did not catch it earlier:**
- **Is this a one-off or a recurring `(stage, block, category)` pattern?**
  (`scripts/issue_report.py`)

## 6. Action

- **Immediate recovery:** resume / targeted stage subset / `--fresh` (why)
- **Fix:** prompt / rule / catcher / renderer / config / infra
- **Tests added:**
- **Eval added/updated:**
- **Docs updated:**
- **Event/map row added:**
- **Resume/version impact:**

## 7. Follow-ups

- [ ] Debt logged with an owner and a trigger
- [ ] A seeded defect or golden captures the failure
- [ ] The runbook/architecture doc is corrected if it was wrong
- [ ] The next run id is linked here

## 8. Safety check

- [ ] No secret or learner record is copied into this log
- [ ] Every quoted model output is from an artifact, not retyped
- [ ] The fix is in the owning file, not a hand-edit of generated output
