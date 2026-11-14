# Artifact contract

Fill this in before changing a stage's handoff. One artifact per stage.

## Identity

- **Stage id:** (`00-ingest` ... `12-narration`)
- **Owner module:**
- **Run id:** deterministic / custom (why)
- **Schema:** `factory/schemas.py::<NAME>` / none
- **`PIPELINE_VERSION` impact:** none | bump (why)

## Input

| Input | Artifact path | Schema | Produced by | Optional? |
|---|---|---|---|---|
| | `runs/<run_id>/.../output.json` | | | |

- **In-memory handoff:** what the orchestrator passes directly
- **Cross-run fallback:** which `load_stage_output` calls are allowed
- **Secrets/config:** env-only keys read (names only, never values)

## Output

- **Shape (JSON):**
  ```json
  {}
  ```
- **Artifact path:** `runs/<run_id>/<stage>/output.json`
- **Side effects:** files outside the run dir? (`frontend/`, `sources/cache/`,
  `audio/`) — name them and the owning flow
- **Stable IDs:** created/preserved
- **Size/limits:** blocks, chars, tokens, rounds

## Resume semantics

- **`stage_ok` means:** state `ok` and `output.json` present
- **On resume:** reused / re-read / re-derived
- **If an upstream artifact is missing:** fail (`MissingArtifactError`) /
  copy from newest previous run
- **Fingerprint inputs:** which config changes invalidate this artifact
- **Safe to resume after a schema change?** yes / only with re-render / no
  (`--fresh`)

## Failure semantics

| Failure | Class | Routed to | Behavior |
|---|---|---|---|
| schema/validation | `SchemaError` | retry with errors-as-context, then fail | |
| gate fatal/major | `StageError` | paired catcher | |
| infeasible/budget | `BudgetError` | fixable → catcher / unfixable → stop | |
| lint | `LintError` | model feedback / stop | |
| infra | `MissingArtifactError` etc. | stop loudly | |

- **Never:** swallow, silent fallback, re-run upstream, retry a permanent 4xx
- **Evidence:** attempt path, round history, ledger rows

## Verification

- **Unit tests:**
- **Integration/mock test:**
- **Eval card/checker/golden:**
- **Manual artifact to inspect:**
- **Logging events:**

## Contract review

- **Producer/consumer files grepped:**
- **Docs updated:**
- **Resume test:**
- **Rollback:**
