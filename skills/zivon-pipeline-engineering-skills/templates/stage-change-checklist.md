# Stage change checklist

Copy this into the PR body or a working note. Tick every applicable box; write
"n/a" with a reason for the rest. A box you cannot tick is a question for the
reviewer, not a silent omission.

## 0. Frame the change

- [ ] The failure class or requirement is named, with an artifact, incident, or
      founder decision as evidence.
- [ ] The change is one coherent slice: schema, prompt, gate, renderer, or
      publish. Split unrelated slices.
- [ ] The owning workstream is identified (`factory/`, `evals/`, frontend
      shell, infra), and no other owner's files are touched.

## 1. Contract

- [ ] Inputs and outputs are written down (use `artifact-contract.md`).
- [ ] The artifact path is stable and under `runs/<run_id>/<stage>/`.
- [ ] The schema is updated in `factory/schemas.py` (or explicitly unchanged).
- [ ] The prompt SHAPE example matches the schema, if the model emits the
      shape.
- [ ] Stable IDs (`b-NN`, `claim-NN`, `eq-NN`, `unit_id`, locale) are preserved;
      new content is appended, never renumbered.
- [ ] `PIPELINE_VERSION` decision is recorded: bump for graph/artifact
      semantics; no bump for runtime policy (caps, rules, prompt wording).
- [ ] Resume impact is stated: old artifacts reused, re-rendered, or refused.

## 2. Harness and gates

- [ ] A requirement that must always hold is a deterministic check, not prompt
      prose.
- [ ] A judgement requirement is a reviewer with the right context and a
      calibrated rubric.
- [ ] The gate is paired with a catcher, or it fails loudly with a smoke test.
- [ ] The catcher has a progress metric, a stall limit, a cap, a round history,
      and an actionable failure message.
- [ ] A fix that breaks lint/perf/ownership costs a round, not the run.
- [ ] Upstream stages are not re-run by a downstream failure.

## 3. Tests and evals

- [ ] Unit tests cover valid and invalid mechanics.
- [ ] A mock-server orchestration test covers the stage wiring, if the stage
      changed.
- [ ] A seeded defect or golden covers the new failure mode, if model quality
      is the deliverable.
- [ ] `python -m evals run --suite smoke --mock` passes; a live run is linked
      by run id only if authorized.
- [ ] A skipped browser/ffmpeg test is reported as skipped, not passed.

## 4. Logging

- [ ] Every new observable transition has an instrumentation-map row.
- [ ] The event is emitted through `logging_manager.log_event`.
- [ ] `run_id` (and `request_id` for a model call) comes from context, not an
      argument.
- [ ] Failure events carry a closed `ErrorClass`; timing events carry
      `latency_ms`.
- [ ] No page content, prompt, answer, transcript, or secret is in `fields`.
- [ ] `testing/observability/test_events.py` lists the event and the row count
      is updated.

## 5. Docs

- [ ] `docs/content-factory/architecture.md` stage table/failure semantics.
- [ ] `docs/content-factory/blocks-schema.md` for a block/spec change.
- [ ] `docs/content-factory/config-reference.md` for a config key/default.
- [ ] `docs/content-factory/runbook.md` for an operator-visible behavior.
- [ ] `docs/specs/evals/*` for a card/checker/golden change.
- [ ] `docs/specs/observability/*` for an event/component change.
- [ ] `docs/specs/translation/*` for a translation contract change.
- [ ] `docs/frontend/*` or `docs/specs/frontend/*` for a rendered-page change.
- [ ] This skill bundle, if a contract it teaches changed.

## 6. Verification

- [ ] `ruff check .` and `ruff format --check .` pass.
- [ ] `mypy --ignore-missing-imports <touched paths>` passes.
- [ ] The touched deterministic suites pass key-free.
- [ ] `python3 scripts/check_specs.py` passes.
- [ ] `python3 scripts/check_skills.py --strict --bundle <bundle>` passes, if
      a bundle changed.
- [ ] A before/after run artifact or golden diff is attached.
- [ ] The PR states known debt and rollback.

## 7. Decision record

- Change:
- Why now:
- Alternatives rejected:
- Resume/version decision:
- Eval evidence (run id / `eval_summary.md`):
- Known debt:
- Rollback:
