# Review procedure

The repeatable path from "here is a content PR" to a defensible verdict. It assumes the evidence rules and rubric in `SKILL.md`; this file is the how.

## 0. Preconditions

Read these before touching the artifact (skim the ones the artifact does not use):

- `AGENTS.md` — scope, grounding law, non-negotiables, definition of done.
- `docs/content-factory/architecture.md` — stages, gates, coverage contract, severity ladder, resume/fingerprint rules.
- `docs/content-factory/blocks-schema.md` — block IDs, per-type payloads, ordering, localization contracts.
- `docs/specs/evals/spec.md`, `docs/specs/evals/card-template.md`, `docs/specs/evals/golden-sets.md` — deterministic-first funnel, cards, goldens, thresholds.
- `docs/specs/translation/spec.md`, `docs/specs/translation/block-contract.md`, `docs/specs/translation/reviewer-rubric.md` — locale model, script rules, glossary, fallback flags (translation PRs).
- `docs/specs/gaps/gap-register.md` §GAP-015 — narration rules (narration PRs).
- `docs/product/features.md` — the feature the artifact serves (F-COR-LES-01, F-COR-CHK-01, F-COR-SIM-01, F-COR-DIA-01, F-COR-PROV-01, F-WRP-LAN-01, F-WRP-TTS-01), plus the frozen product decisions.
- `TIMELINE.md` — the live gate state, scope ladder, and release decisions.
- `docs/specs/frontend/shell-injection.md` + `docs/frontend/design-doctrine.md` — the reference page shape and visual language the content must remain compatible with.

Hard limits: no live model calls, no live Timbre synthesis, no `python pipeline.py`, no paid judge; use run artifacts, goldens, fixtures, and `--mock`. Do not hand-edit generated artifacts or `frontend/courses/**` to make a review pass.

## 1. Classify the artifact

| Artifact | Where it lives | Governing contract | Primary evidence |
|---|---|---|---|
| Lesson page | `frontend/courses/<course>/<topic>/` (`index.html`, `page.js`, `page.css`, `manifest.json`, `i18n/<locale>.json`, `i18n.js`) | `docs/content-factory/blocks-schema.md`; `docs/specs/frontend/shell-injection.md`; `docs/frontend/design-doctrine.md` | rendered page + manifest + perf report |
| Lesson draft / run output | `runs/<run_id>/02-generate/output.json`, `03-check/combined-*.json`, `09-review/**`, `status.json`, `run_report.json`, `issues_ledger.jsonl`, `calls_ledger.jsonl` | `docs/content-factory/architecture.md` | run artifacts + gate verdicts |
| Translation | `runs/<run_id>/10a-translate/blocks/<locale>/*.json`, `10b-transcheck/**`, `10d` output, published `i18n/<locale>.json` and `<locale>/index.html` | `docs/specs/translation/spec.md`, `docs/specs/translation/block-contract.md`, `docs/specs/translation/reviewer-rubric.md` | per-locale verdict + TM + published strings |
| Narration | `frontend/audio/<course_id>/**`, topic `manifest.json` → `narration`, `narration-manifest.json`, `runs/narration-budget.json`, `narration_usage.jsonl` | `docs/specs/gaps/gap-register.md` §GAP-015; architecture stage 12 | manifest + assets + speakable selection |
| Catalogue / publish | `frontend/courses.js`, `catalogue.json` (when present), `frontend/sitemap.xml`, `frontend/robots.txt`, publish report | `factory/link.py`, `scripts/publish-frontend.sh`, `docs/specs/frontend/seo-plan.md` | every href/locale/sitemap URL resolves |
| Prompt / checker / rubric | `factory/agents.py`, `factory/review.py`, `factory/checks.py`, `factory/lint.py`, `factory/perf.py`, `evals/checkers/**`, `evals/cards/**`, `evals/goldens/**` | `skills/prompting-and-agent-design/SKILL.md`; `docs/specs/evals/spec.md` | affected artifact + eval run + calibration |

Write a three-line map before reviewing:

```
Stage: 02-generate → 03-check → 06-render → 09-review → 11-link
Artifact: frontend/courses/class-9-physics/motion/index.html + manifest.json
Gate evidence: runs/motion-c9/run_report.json, 09-review verdict, perf report, eval run id
```

If you cannot fill the map, the PR is missing evidence; that itself is a finding.

## 2. Trace the stage and the contract

1. Find the stage in `docs/content-factory/architecture.md`. What does it consume, produce, and hand to the next stage?
2. Name the gate that approved the artifact (03-check for facts/answers/coverage; 05-interactive lint for sim code; 07-perf for budget; 09-review for facts/design; 10b-transcheck for translation; 11-link for publish integrity).
3. Read the artifact's contract, not a remembered version of it. If the PR changes the contract, read the updated doc and check the change is documented in the same PR.
4. For a prompt/checker change, identify the **artifact it can change** and the eval card/golden that covers that artifact. A prompt diff with no artifact and no eval is an evidence gap.
5. Check `PIPELINE_VERSION` and the run fingerprint. A page built under a different version is not comparable to a current-shape page without saying so (`docs/content-factory/architecture.md`, "Resume and freshness").

## 3. Sample deliberately

| Artifact size | Sampling rule |
|---|---|
| One lesson page (4–45 blocks) | Inspect **all** blocks. It is small enough; sampling hides the one wrong key. |
| Check set on a lesson page | All answer keys and numeric answers. For explanations/prose, stratify by concept, item type, and language; at least 6 checks or 10%, whichever is larger. Always include the first, last, and one middle check. |
| Translation | Every locale in `locales_available`; every key with a fallback; a full script-purity scan; sample glossary first mentions and every check explanation. |
| Narration | Every speakable block's selection; inspect a sample of audio metadata/hash/duration; listen only when a human reviewer is available and the asset is present. |
| Catalogue / publish | Every entry, every href, every declared locale file, every sitemap URL. |
| Prompt/checker | The diff plus the affected artifact from the latest run; the eval card and the last two eval runs (regression diff). |

Record the sample in the report: what you inspected, what you skipped, and why. Never sample only the first N items; generated pages often cluster defects near the end or after a repair round.

## 4. Run the deterministic checks

Run what covers the artifact. All of these are key-free and offline unless noted.

```bash
# pipeline mechanics (schema, rules, renderer, resume, lints)
python -m unittest discover -s testing/content_factory/unit -t .
python -m unittest discover -s testing/content_factory/integration -t .

# translation + narration + eval mechanics
python -m unittest discover -s testing/translation -t .
python -m unittest discover -s testing/narration -t .        # needs ffmpeg on PATH
python -m unittest discover -s testing/evals -t .
python -m unittest discover -s testing/observability -t .

# shell/page contracts (browser)
python -m unittest discover -s testing/frontend -t .         # needs: python -m playwright install chromium

# evals (deterministic-first; smoke is key-free)
python -m evals run --suite smoke --mock
python -m evals run --suite smoke --fail-on-regression
python -m evals calibrate --stage all --mock                 # reviewer/prompt changes

# regression diff between two eval runs
python -m evals diff --prev <prev_run_id> --curr <curr_run_id>

# repo hygiene
ruff check . && ruff format --check .
python3 scripts/check_specs.py
```

For a published page, also open it locally (for example `python3 -m http.server` from `frontend/`) and check: zero console errors, no external requests, 360 px and 1280 px layout, JS-off readability, keyboard walkthrough, and a reduced-motion pass. Do not run `scripts/publish-frontend.sh`; it is the founder-run publish bridge. Do not run `python pipeline.py`; it spends model credits and is founder-triggered.

Read the artifacts the checks produce:

- `runs/<run_id>/status.json` — stage ok/failed and elapsed time.
- `runs/<run_id>/run_report.json` — stage durations, model-call stats, issue counts by category.
- `runs/<run_id>/issues_ledger.jsonl` — every reviewer finding (stage, call, severity, category, block, unverified flag).
- `runs/<run_id>/calls_ledger.jsonl` — answered/rejected/transport-failure per attempt; a plateau or `length` cut is visible here.
- `runs/<run_id>/<stage>/attempts/...` — the exact request/response evidence.
- `evals_runs/eval_runs_ledger.jsonl` + `evals_runs/<eval_run_id>/eval_report.json` — eval evidence.
- `python3 scripts/issue_report.py` — cross-run recurring findings (after `scripts/publish-artifacts.sh`, which mirrors `runs/` for human inspection).

A failing deterministic check is the finding. Do not override it with a judge or a prose opinion.

## 5. Compare with the reference

- Current-shape lesson pages: `frontend/courses/class-9-physics/motion/` and `frontend/courses/class-11-physics/laws-of-motion/`.
- Kit/doctrine reference: `docs/frontend/design-doctrine-lesson-example.html` and `docs/frontend/design-doctrine.md` §10.
- Golden contracts: `evals/goldens/topics/*/expected.json` (structure bounds, concepts/equations, numerical anchors, visual invariants, perf budgets) and `evals/goldens/defects/` (seeded defects for reviewer calibration).
- Pipeline expectations: `PIPELINE_VERSION` lives in the run fingerprint (`factory/stages.py::run_fingerprint`, recorded in `status.json`), not in the topic manifest. The published tree predates that field, so compare manifest shape (`lesson_title`, `locales_available`, `translation_status`, `narration`) and the run's fingerprint/status; match the best page and the tests, not the average. Known live defects (for example `chapter.title = "Grade"` on `describing-motion-around-us`) are **not** a licence to copy.

When the artifact is a new surface with no reference, compare with the **closest** existing contract: the `docs/product/features.md` feature card and the eval card/golden that covers the artifact. State the comparison you used. Do not invent a contract for a surface the repo has not specified.

## 6. Classify severity

Start from the defect class, then adjust for blast radius and whether the artifact is already published.

| Defect class | Default | Escalate when |
|---|---|---|
| Wrong answer key; fact contradicts the cited source; later-chapter concept taught/tested as fact; translation inverts a physics statement; answer read aloud | blocker | already published and a learner sees it → still blocker |
| Page blank/broken; `eval`/external call/CSP break; missing block/asset that makes the lesson unusable | blocker | — |
| Identity-only title/label error (`"Grade"`, model headline, wrong chapter label) | major | the page teaches the wrong chapter's content → blocker |
| Missing/empty explanation; required section/exercise type missing; untranslated leak in a promised locale; duplicate topic; false provenance or over-claim | major | a false official-endorsement or guaranteed-score claim → blocker |
| Mixed pipeline versions in one catalogue; stale sitemap/placeholder host; narration asset missing while marked available | major | a route 404s or the catalogue cannot be trusted → major |
| Thin but correct explanation; glossary gap; readability above class level; awkward but faithful translation | minor | it changes the answer/claim → major |
| Typography, wording preference, layout taste with no learning impact | nit | — |
| Unsettled product choice, missing context, suspicion you cannot reproduce | question | — |
| Notably clear, grounded, honest content | praise | — |

Rules:

- **One root cause, one finding.** If the same defect appears in 6 items, write one finding and list the ids.
- **Distinguish new from pre-existing.** A pre-existing published defect is reported but does not block an unrelated PR; name the publish owner.
- **A blocker is never "just a follow-up".** `TIMELINE.md` records pending work, but a wrong answer, a false claim, or a broken page remains a blocker.
- **The rubric does not override severity.** A single wrong key is a blocker even if the other five dimensions score 3.

## 7. Do not re-litigate product decisions

These are frozen; a review that argues with them is noise:

- Subject scope is academic Physics, Class 9–12. No Python, no general chat.
- Product language set is all Gnani-supported languages; the v1/demo subset is English + हिन्दी + Hinglish (`T2`). Page translation is a separate second-layer pipeline (`SC-01`, not yet built); the factory produces English natively.
- Guest-first; no parent account, no leaderboards, no share links; static generated lessons + server-rendered pages + vanilla-JS islands, no SPA.
- Voice loop is Prisma v3.0 + Timbre v3.0 + Gemma 4 26B A4B (Gemini API key); never replace.
- Source content is NCERT/public-domain only, with citations; no scraped copyrighted textbooks.
- Every generated page passes the Comprehension & Fact Reviewer and the Code Reviewer before it goes live (`AGENTS.md`). There is no content-debt exception gate; `TIMELINE.md` is the only task list, and a follow-up is recorded there or in the PR body with artifact, owner, severity, and reproduction.

If a PR contradicts a frozen decision, record a **question** with the doc citation (`docs/product/features.md`, `TIMELINE.md`, `AGENTS.md`). If two docs conflict, treat `AGENTS.md` and `TIMELINE.md` as the repo law above derived specs, record both paths, and raise the conflict; do not pick a side silently. Do not ask for a new feature in a review; log it as a follow-up or question.

## 8. Write the report

Use [../templates/content-review-report.md](../templates/content-review-report.md). Include:

1. Verdict and the top issue in the first three lines.
2. Artifact/stage map and the evidence you actually ran.
3. Rubric scores with one sentence of evidence each.
4. Findings by severity, in the suite format, ordered by learner impact.
5. Coverage table: what was inspected, what was sampled, what was skipped.
6. Content-debt table: finding, owner, artifact, reproduction, target.
7. What you did **not** review (live model calls, full regeneration, audio listening, a page you could not render) so approval is not read as broader than it is.

If the user asks for fixes rather than a report, make the smallest change that addresses blockers/majors, re-run the deterministic checks, and list exactly what changed. Never bypass a gate, never edit a golden to make a failure disappear, and never hand-edit a generated artifact that the publish flow owns.
