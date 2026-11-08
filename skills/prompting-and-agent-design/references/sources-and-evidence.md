# Sources and evidence

Dated bibliography behind `SKILL.md`. Rule ids `[S#]` in SKILL.md refer to the
numbers here. Window requested by the founder (2026-11-04): sources from the
last 3 months preferred, 6 months maximum; continuously-maintained official
docs count as current. Older sources are marked HISTORIC — they are cited only
because newer official material still builds on them, and any rule taken from
them was re-checked against an in-window source before encoding.

## In-window sources (May 2026 → Nov 2026)

### [S3] Authoring Agent Skills: A Software-Engineering Approach — G. Destefanis, UCL. arXiv:2607.25032, 27 Jul 2026
A skill is a software artefact: single responsibility, interface (description)
separated from implementation (body), low coupling, economy in a shared token
budget, behavioural evaluation in place of deterministic testing. Key rules
adopted:
- Staged loading (progressive disclosure): metadata always resident, body
  loaded on trigger (< ~500 lines), references/scripts on demand.
- References stay ONE level deep from SKILL.md; >100-line references carry a
  table of contents so partial reads are safe.
- **Degrees of freedom:** "Match the level of constraint to the fragility of
  the task. Where several approaches are valid, give general direction; where
  a sequence is fragile and must run exactly, give the precise command."
- Evaluation-driven authoring: write evaluations first, measure the baseline
  without the skill, then write the MINIMUM instructions needed to pass.
  Draft with one instance, test with a fresh instance that has only the skill
  loaded.
- Assume the model already holds general knowledge; add only what it lacks.
- Who-decides/guarantee table separating memory files, skills, commands,
  subagents, tools, hooks: requirements that must hold every time belong in
  runtime-guaranteed mechanisms, not advisory prose.
- Offer many alternatives → the model chooses without grounds: give one
  default and name the exception. Test with each model intended for use: a
  body tuned for a strong model may need more detail for a weaker one.

### [S2] Demystifying evals for AI agents — Anthropic Engineering, 9 Jan 2026
Evaluation design for agent systems; adopted directly for the factory's gates:
- Grader taxonomy: code-based graders (fast, objective, reproducible) where
  possible, model-based graders (rubrics, calibrated with humans) where
  necessary, human graders for calibration. Maps 1:1 onto our rules-checks +
  reviewer stages + kid-tester edit rate.
- "Grade what the agent produced, not the path it took" — rigid step/order
  assertions are brittle and punish valid creativity.
- Judges need a way out: "give the LLM an instruction to return 'Unknown' when
  it doesn't have enough information" (our `unverified:` minor hedge); grade
  each dimension with clear structured rubrics.
- Balanced problem sets: test both directions (a reviewer must pass good pages
  and catch bad ones; one-sided evals create one-sided optimization).
- Failures should seem fair: read the transcripts; if scores don't climb,
  verify it's the agent, not the grader. A 0% pass rate is usually a broken
  task, not an incapable model (applies to our fixture/review design).
- Partial credit; capability evals vs regression evals; pass@k vs pass^k
  (our pipeline cares about pass^1 per stage with bounded retries — the
  measured quantity is human edit rate per topic).
- Harnesses and evals encode assumptions and go stale as models improve;
  teams without evals face weeks per model upgrade.

### [S4] Prompting best practices — Claude Platform docs (live, fetched 2026-11-04; covers Fable 5.1 / Opus 5.5 / Sonnet 5.5 era)
The current official prompting reference; adopted rules:
- "Tell the model what to do instead of what not to do."
- "Add context to improve performance": explaining WHY a rule exists lets the
  model generalize the rule to unenumerated variants.
- Examples are one of the most reliable steering levers: 3–5 relevant,
  diverse, structured examples; wrap them so they cannot be confused with
  instructions.
- Long-context layout: put long documents ABOVE the query/instructions;
  queries at the end improve quality measurably; structure documents and
  citations with explicit tags; ground answers in quotes from the material.
- Reasoning/thinking era: thinking is adaptive and calibrated by the model;
  token-budget capping for thinking is deprecated in favor of effort/scope
  settings; "prefer general instructions over prescriptive steps — a prompt
  such as 'think thoroughly' often beats a hand-written plan"; manual CoT is
  a legacy fallback; over-prompting (belt-and-braces MUST language) now causes
  over-triggering — soften aggressive language.
- Self-check instruction helps some models, over-verifies others; remove
  carried-over verification nagging for models that verify unprompted.
- Long-horizon work: state in structured files + progress notes + git; set up
  verification tools; don't fight the model's incremental-progress tendency.
- Migration notes: prefills and other legacy coercions are obsolete "model
  intelligence and instruction following have advanced such that most use
  cases of prefill no longer require it."

### [S1] Skill authoring best practices — Claude Platform docs (live, fetched 2026-11-04)
- "The context window is a public good."
- Concise is key; assume the model is smart; add only what it does not know.
- Evaluation-driven authoring loop (draft instance vs fresh test instance);
  iterate against observed behaviour, not imagined failure.
- SKILL.md structure/naming rules used for this very folder.

### [S5] How to prompt reasoning models effectively — OpenAI API docs, reasoning guide (live doc, fetched 2026-11-03)
- "These models perform best with straightforward prompts"; chain-of-thought
  instructions "may not enhance performance (and can sometimes hinder it)".
- Keep prompts simple and direct; try zero-shot first, add few-shot examples
  only if needed; be explicit about success criteria — state what winning
  looks like rather than the route to it.

## Adjacent-window / older official sources (HISTORIC — foundations newer docs build on)

### [S6] Scaling Managed Agents & context-engineering practice — Anthropic cookbook (Mar 2026) and "Effective context engineering for AI agents" (29 Sep 2025, HISTORIC)
- The harness encodes assumptions about the model and quietly goes stale as
  models improve — re-evaluate scaffolding on every model change.
- Context is a finite resource to be curated: curate what enters the window,
  compress/summarize what must stay, offload state to disk/tools.
- Compaction / on-disk state / fresh-context patterns for long horizons
  (our analogue: stage artifacts + resume instead of giant in-memory
  conversations).
- "Prompts are frameworks for collaboration, not strict instructions" — the
  multi-agent-systems framing behind our gate/catcher design (HISTORIC, Jun
  2025, restated inside later official material).

### [S7] Rubric verification and LLM-as-judge reliability (2026 literature)
- RUVERBENCH / "Can LLM-as-a-Judge Reliably Verify Rubrics in Agentic
  Scenarios?" (EMNLP 2026): judge reliability on concrete rubric items is
  much higher when each rubric item is verified separately with quote-grounded
  evidence — supports our per-issue citation requirement ("quote the source
  passage that proves it") and one-verdict-per-severity calibration.
- 2026 judge-calibration practice (Arize, Logfire, Jan 2026 evals post): LLM
  judges drift; sample-calibrate against human grading regularly — supports
  reading run evidence rather than trusting gate stats.

### [S8] Evidence that minimal scaffolding wins on strong models
- mini-swe-agent (SWE-agent org; widely used third-party baseline, repo live
  2025→2026): a ~100-line agent with a radically short prompt scores within a
  few points of massive scaffolds on SWE-bench-class work — complex scaffold
  prompts do not buy reliability on capable models; the loop and the
  verification do.
- Contrast point kept from the same literature: the same minimal prompt does
  WORSE on weak models — scaffolding is calibrated to model strength, not
  removed by ideology (ties to [S3]'s "test with each model intended for
  use").

## How the founder's thesis maps (2026-11-04 request)

The founder's summary — "newer models shine with minimal guardrails and intent
framing; older-era guardrails (tight output budgets, heavy instruction) hurt
them; modern prompting is context management, goals not execution plans" — is
confirmed by [S1][S2][S3][S4][S5][S8] with two corrections we must keep in
force:
1. Contracts are NOT old-era guardrails: schemas, SHAPE examples, interface
   skeletons, and severity ladders remain the right coercion; what went away
   is prose micromanagement of REASONING and fear-based repetition.
2. Guardrails did not disappear — they MOVED: from prompt prose into the
   harness (code checks, bounded loops, judges with rubrics, deadlines). The
   model gets latitude inside a verified envelope ("trust, but verify with the
   harness").

## Repo-side experiment: 09-review bounded-procedure restructure (2026-11-08)

Failure class (measured): the 09-review call rambled — it streamed ~2,000 s
with no content chunks, then the server reported "structured output was
incomplete (finish_reason=length); increase the output budget" mid-call.
llm_manager maps server-reported errors to terminal transport failures, so
the truncation preempted the validation-round logic that would otherwise ask
for a compact retry. The successful review of the same page used 47k
completion tokens; the ramble exhausted the remaining context (~207k).
Run-level doom loop: each re-trigger burned ~34 minutes and died at the same
stage.

Lever applied (founder decision, prompting-only): the task section was
rewritten from an open-ended "hunt for REAL defects" + six-item requirements
checklist into a bounded six-step inspection procedure run EXACTLY ONCE
(inventory → per-block correctness → facts sweep → usability/access →
visual language + frame → verdict), with commitment language ("Commit to
this procedure: one pass, one check per item, then the verdict") — the
sanctioned fix for runaway thinking is scope setting, not switches. Two
checklist items (perf hygiene, code quality) were dropped from the model's
procedure: both are already enforced by the harness (07-perf gate, lint) and
were minor-only, so the gate's power is unchanged.

Rule mapping: the "numbered execution plans" anti-pattern targets
GENERATION; a reviewer's defined pass order is a calibrated rubric [S7], and
quantized local models need more scaffolding than frontier models [S3][S8].
Honest framing, the severity ladder (now stated exactly once), the
'unverified:' way out, and the JSON contract are unchanged.

Status: unit-anchored (test_review.py pins the procedure); live validation
against the real server pending (resume re-runs 09-review only). If the
model still rambles, the founder-sanctioned next lever is splitting the
review into smaller steps across calls; a harness-side alternative is
treating a server-reported structured-output truncation as a validation
round instead of a terminal error.

## Repo-side experiment: 09-review split into two calls + failure ledgers (2026-11-08)

Follow-up to the bounded-procedure entry above; same day, same stage.

Live probe of the bounded procedure was green (444 s, 14k completion tokens,
verdict=pass, 7 issues of which 3 major - compact, procedure-following). The
founder's real re-trigger (run `factory-run-motion-in-a-straight-line-180935`)
still doom-looped, and the attempt evidence shows the pathology moved from
"one call rambles" to "the 09<->10 catcher plateau burns thinking every
cycle":

- First 09-review pass: 792.8 s, 24,035 completion tokens, `finish_reason`
  clean, verdict=fail (5 issues) - mechanically sound, one REAL fatal
  (b-31 quiz answer key: "49 s" is physically wrong).
- 10-reviewfix round 1 "fixed" it by making page.js rewrite 49 s -> 37 s
  while index.html still displayed 49 s.
- Re-review round-01: 1,747 s, 55,101 completion tokens, verdict=fail (7
  issues) - the same fatal re-flagged as an HTML-vs-JS inconsistency.
  Blocking score 2 -> 2 (plateau, streak 1/3).
- Reviewfix round 2 ok (380 s, 8,887 tokens); re-review round-02 thought
  ~130k tokens and was killed by the founder mid-call. Server-side MoE
  expert-cache hit rate had climbed to suspiciously high levels - the same
  experts re-entered again and again: the loop signature.
- `first_token_s == latency_s` on every review attempt: the model streamed
  NOTHING until the final JSON - completion_tokens is essentially pure
  thinking time, and the calls ledger now makes that visible per attempt.

Server-side finding (the founder's "256 repeat trigger did not go off"): the
Strata server's `REPEAT_STOP_TOKENS=256` guard only catches SINGLE-TOKEN
runs (its motivating issue was 36,689 "!" tokens). Passage-level reasoning
repetition is guarded by the OPT-IN `reasoning_loop_recovery` config
("stop" ends the reply there; "recover" continues with a low-effort
instruction) - unset on this server, so the 130k-token loop was invisible to
it. Recommendation to the founder (their infra, their call): set
`"reasoning_loop_recovery": "recover"` in `strata-iq3_xxs.json`.

Lever applied (founder decision - the sanctioned fallback from the previous
entry): 09-review's one giant call became TWO bounded calls, each carrying
only the context its checks need:

- `09-review-facts`: block specs + cited facts + final files. Answer keys,
  fact contradictions, drawn behaviour, and a named HTML-vs-JS CONSISTENCY
  sweep (the b-31 pathology is written into the prompt as the worked example:
  "HTML shows 49 s while the script mutates it to 37 s"). No doctrine, no
  example.
- `09-review-design`: compact block inventory + final files + doctrine +
  lesson example. Doctrine compliance, frame law, usability/access, plus a
  general RENDERING SWEEP - "judge the page as a learner would, not against
  the doctrine": labels vs what is drawn, clipped text, broken canvases,
  animations contradicting captions. (Founder requirement: design correctness
  must not be only doctrine-example comparison.) No full specs, no facts.
- Both calls output ISSUES ONLY with a required `category` from a fixed enum;
  the verdict rule ("fail iff any fatal") moved from prompt prose into
  harness code - a guarantee in the harness, not in the prompt.
- The manifest dump left the prompt entirely (mechanical metadata;
  traceability is enforced by the static checks); both calls get a 3-line
  identity header instead. Founder delegated this call; this is the decision.

Logging layer (founder's ask: "actionable insights, not status updates"):
append-only `calls_ledger.jsonl` + `issues_ledger.jsonl` per run, meta.json
now written for mid-call transport deaths too, run_report rollups, and
`scripts/issue_report.py` for cross-run failure-class analysis (per-stage
thinking seconds, rejection reasons, issue categories, recurring
block+category across rounds = plateau signature).

Rule mapping: smaller task scope per call is the scope-setting lever [S4];
verdict guarantees belong in the harness [S7]; categories turn reviewer
findings into data that prompting fixes can target. PIPELINE_VERSION stays 6
(00-08 artifacts unchanged; resume survives).

Status: unit + e2e anchored (test_review.py two-call anchors, plateau e2e on
the split fixtures); live probe of both calls pending; founder re-trigger of
the class-11 run (resume, no --fresh) pending. If per-call thinking is still
bloated, the documented harness-side option remains: treat a server-reported
structured-output truncation as a validation round instead of terminal.

## Repo-side experiment: kit refactor — layout correctness in the kit, not in prose (2026-11-09)

A full pipeline run after any model change still shipped a broken quiz card:
the renderer's `<fieldset>`+`<legend>` quiz markup diverges when the question
wraps (border slices through the text, tape lands inside the question). The
founder's diagnosis ("everything in the doctrine is right; only generation
gets messed up") and fix ("building blocks") are both correct in substance:
the root cause is mechanical kit composition, not model output quality —
the same defect appeared under Qwen locally and the cloud model.

Lever applied (extending the standing skill rules — "guarantees in the
harness, not in the prompt" and "contracts over coercion"):
- ONE kit: `frontend/assets/zivon.css` + `zivon.js`, with a component catalog
  in the CSS header naming every renderer-emitted markup contract (page chrome,
  language bar, taped cards, quiz, sim, diagram). The doctrine §10 was
  reframed around counting the guarantees the kit carries, not re-teaching
  layout in prose.
- The quiz legend overflow is fixed in the kit with the float-legend rule
  (legend floats at 100% width so the card border paints OUTSIDE it) — CSS
  only, so already-rendered pages are repaired at serve time with no
  re-render (PIPELINE_VERSION stays 6 deliberately).
- Kit ownership is enforced by lint (`lint_page_css_scope`: model page.css may
  only style inside the block's `.zn-sim-<id>` scope; canvas sizing is
  forbidden because the kit sizes the canvas). The class-11 run's invented
  `.zn-lang-bar`/`.sim-read` CSS - a textbook case of prompt-side layout
  re-invention - now fails loudly at authoring sites (05-interactive,
  06-render, both fixers) instead of shipping dead styles.
- The lesson example is rebuilt onto the kit's exact classes and local fonts
  (no Google Fonts, no lesson-kit.js) so models copy component patterns by
  structure. The renderer's language bar (doctrine §10.5, previously flagged
  missing on every page) is now renderer-emitted kit chrome.

Status: unit (282) + e2e (8) + frontend (11) green incl. a new Chromium
legend-geometry regression test, ruff/mypy clean. 0.3.14 release + visual
probe of the class-11 card pending.

## Repo-side experiment: layout correctness into the kit (2026-11-09)

A full pipeline run after any model change still shipped a broken quiz card:
the renderer's `<fieldset>`+`<legend>` quiz markup diverges when the question
wraps (border slices through the text, tape lands inside the question). The
founder's diagnosis ("everything in the doctrine is right; only generation
gets messed up") and fix ("building blocks") are both correct in substance:
the root cause is mechanical kit composition, not model output quality —
the same defect appeared under Qwen locally and the cloud model.

Lever applied (extending the skill's standing rules — "guarantees in the
harness, not in the prompt" and "contracts over coercion"):
- ONE kit: `frontend/assets/zivon.css` + `zivon.js`, with a component catalog
  in the CSS header naming every renderer-emitted markup contract (page chrome,
  language bar, taped cards, quiz, sim, diagram). The doctrine §10 was
  reframed around counting the guarantees the kit carries, not re-teaching
  layout in prose.
- The quiz legend overflow is fixed in the kit with the float-legend rule
  (legend floats at 100% width so the card border paints OUTSIDE the question) —
  CSS only, so pages already rendered (including the founder's just-published
  class-11 page) are repaired at serve time with no re-render
  (PIPELINE_VERSION stays 6 deliberately).
- Kit ownership is enforced by lint (`lint_page_css_scope`: model page.css may
  only style inside the block's `.zn-sim-<id>` scope; canvas sizing is
  forbidden because the kit sizes it). The class-11 run's invented
  `.zn-lang-bar`/`.sim-read` CSS - a textbook case of prompt-side layout
  re-invention - now fails loudly at authoring sites (05-interactive,
  06-render, both fixers) instead of shipping dead styles.
- The lesson example is rebuilt onto the kit's exact classes and local fonts
  (no Google Fonts, no `lesson-kit.js` duplicate — the `LessonKit` is
  single-sourced in `frontend/assets/zivon.js` now).
- The renderer's language bar (doctrine §10.5, previously flagged missing on
  every page) is now renderer-emitted kit chrome.

Status: unit (282) + e2e (8) + frontend (11) green incl. a new Chromium
legend-geometry regression test, ruff/format/mypy clean. 0.3.14 release +
visual probe of the class-11 card pending.

## Maintenance rules for this folder

- Re-validate a rule against current official docs when the factory's model or
  inference server changes (stale-assumption risk, [S6]).
- When adding a source: date it, keep the bibliography sorted by window, and
  mark anything older than 6 months HISTORIC.
- SKILL.md stays under 500 lines; this file is the deep layer and is read only
  when a decision is contested.
