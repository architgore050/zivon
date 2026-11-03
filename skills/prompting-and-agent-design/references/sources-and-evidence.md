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

## Maintenance rules for this folder

- Re-validate a rule against current official docs when the factory's model or
  inference server changes (stale-assumption risk, [S6]).
- When adding a source: date it, keep the bibliography sorted by window, and
  mark anything older than 6 months HISTORIC.
- SKILL.md stays under 500 lines; this file is the deep layer and is read only
  when a decision is contested.
