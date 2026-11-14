# zivon-evals-and-observability-skills

The single entry point for **logging** and **evaluations** in Zivon. It turns two vague
verbs into checklists a reviewer can verify:

- **logged** — the event has an instrumentation-map row, is emitted through
  `logging_manager.log_event`, carries the declared correlation IDs / severity / error class,
  survives redaction, and is visible in a sink in a normal run.
- **evaluated** — a model or content-quality change has an eval card that covers the new
  failure mode, deterministic checkers that run key-free, registered goldens, a persisted run
  in the one curation front, declared `EVT-EVAL-*` telemetry, and a PR that links the run id
  and summary.

This bundle is instructions, templates, and review checks. It is not code: it does not modify
`logging_manager/`, `evals/`, `factory/`, or the specs it cites.

## Scope

**In scope**

- Adding, changing, or removing a structured event (`factory.*`, `llm.*`, `llm_node.*`,
  `voice.*`, `translator.*`, `frontend.*`, `credit.*`, `dashboard.*`, `log.*`).
- Adding or extending an eval card, deterministic checker, golden topic, seeded defect,
  LLM judge, calibration run, or regression baseline.
- Making an eval run land in the curated result store and the PR evidence bundle.
- Reviewing any of the above.

**Out of scope**

- Designing the product feature being instrumented or evaluated (see
  `skills/zivon-product-design-skills/`).
- Writing the prompt or rubric being judged (see `skills/prompting-and-agent-design/`);
  this bundle only says how to evaluate it.
- Admin dashboard UI work (see `docs/specs/observability/dashboard-spec.md`), except for the
  read path the eval store needs.

## Layout and read order

```
zivon-evals-and-observability-skills/
├── README.md                       ← you are here
├── SKILL.md                        ← always read first; the workflow and definitions
├── references/
│   ├── logging-manager.md          ← exact API, enums, sinks, correlation, redaction
│   ├── event-map.md                ← add an instrumentation-map row + map-lint
│   ├── eval-authoring.md           ← testing vs evals, cards, checkers, goldens, judges
│   ├── eval-store-and-dashboard.md ← dual-write store, EVT-EVAL-*, one curation front
│   ├── privacy-and-redaction.md    ← child-data rules, allowed aggregates, DPDP deletion
│   ├── review-checklist.md         ← what a reviewer checks before accepting the change
│   └── worked-example.md           ← one event + one card + one checker, run key-free
└── templates/
    ├── instrumentation-row.csv
    ├── eval-card.yaml
    ├── checker.py
    ├── eval-run-checklist.md
    └── golden-fixture.md
```

Read order for an agent:

1. `SKILL.md` — decide whether the change needs logging, an eval, or both.
2. The matching reference: `logging-manager.md` + `event-map.md` for telemetry;
   `eval-authoring.md` + `eval-store-and-dashboard.md` for evals.
3. `privacy-and-redaction.md` before writing any field or fixture with learner-shaped data.
4. The template you are filling in.
5. `review-checklist.md` before opening the PR (or when reviewing one).

## Sources and evidence

**Evidence date: 2026-11-14.** The repo claims were read at `main` @ `57147bb` (this bundle's
base commit) and match the code paths cited in each reference. Perishable values (row counts,
card counts, test counts) are stated with the date and must be re-checked when they change.

Primary (repo) sources:

| Source | Used for |
|---|---|
| `docs/specs/observability/logging-api.md`, `spec.md`, `instrumentation-map.csv`, `dashboard-spec.md` | The logging contract, event catalogue, privacy classes, dashboard reads |
| `logging_manager/` (`events.py`, `redact.py`, `sink.py`, `store.py`, `context.py`) | Exact implemented API and behaviour |
| `docs/specs/evals/README.md`, `spec.md`, `card-template.md`, `golden-sets.md` | Eval framework, cards, goldens, calibration, CI |
| `docs/backend/adr/0027-*`, `0028-*` | Dual-write store and judge model/calibration decisions |
| `evals/` (`cli.py`, `runner.py`, `store.py`, `telemetry.py`, `report.py`, `models.py`, `checkers/`) | What actually runs and where results land |
| `testing/evals/`, `testing/observability/` | The tests that pin the contracts |
| `AGENTS.md`, `TIMELINE.md` | Repo law and scope |
| `tmp/agent-handshake/LOGGING-EVALS-CONTRACT.md` (read-only, untracked handshake folder) | The binding agent recipe this bundle distils |

External sources (from the tested catalog in `skills/skill-creation/references/source-catalog.csv`,
checked 2026-11-14; no text copied):

| ID | Source | Used for |
|---|---|---|
| SRC-001 | [Agent Skills specification](https://agentskills.io/specification) | Progressive-disclosure and frontmatter shape of this bundle |
| SRC-002 | [Agent Skills best practices](https://agentskills.io/skill-creation/best-practices) | Short body, load conditions, gotchas |
| SRC-003 | [Evaluating skill output quality](https://agentskills.io/skill-creation/evaluating-skills) | Baseline-then-compare eval discipline; assertions over vibes |
| SRC-062 | [skills-ref validator](https://pypi.org/pypi/skills-ref/json) | The format-level validator this repo's `scripts/check_skills.py` extends |

## Validation

```bash
python3 scripts/check_skills.py --strict --bundle skills/zivon-evals-and-observability-skills
python -m unittest discover -s testing/skills -t .
```

The strict validator checks frontmatter, links, secrets/PII, placeholders, body length, and
that every reference is reachable. It does not check whether the instructions are true; the
repo tests and the review checklist do that.

## Maintenance

- Re-verify when any of these change: `LOG_SCHEMA_VERSION`, the component/error enums, the
  instrumentation-map column set, the eval-card schema or stage/role enums, the suite names,
  the ledger/run-artifact names, or the count assertions in `testing/evals/` and
  `testing/observability/`.
- Update the evidence date in `SKILL.md` and in this README in the same PR that changes a
  claim.
- If a documented contract and the code disagree, record the conflict in the PR (and in the
  owning spec's open-questions file) instead of silently teaching the code's behaviour.
