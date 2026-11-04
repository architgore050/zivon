---
name: prompting-and-agent-design
description: Guides prompting and agentic-design decisions for the Zivon content factory and the voice tutor. Use when writing, reviewing, or refactoring any agent prompt (02-generate, 03-check, 04-repair, 05-interactive, 09-review, the catchers, or the tutor prompts), when reshaping the agent graph (calls, gates, catchers, retries), when calibrating reviewer rubrics, or when deciding what a guardrail belongs in (prompt vs harness). Encodes current-era practice from dated 2026 sources: goal-first prompting, context management, contracts over coercion, verification loops over instruction walls.
---

# Prompting and Agent Design

How to prompt current-generation models and how to shape the systems around
them. Written for this repo's two agent systems — the content factory
(build-time multi-agent pipeline) and the voice tutor (runtime loop) — but the
rules are model-agnostic. The dated bibliography behind every rule is in
[references/sources-and-evidence.md](references/sources-and-evidence.md); each
rule below cites it as `[S#]`.

## The stance

Current models are strong reasoners with real agentic capability. The work that
pays off is no longer writing execution plans for them; it is:

1. stating the **goal** and what "good" looks like,
2. curating the **context** the model needs to judge that goal,
3. fixing the **contract** the output must satisfy (schema, examples,
   interface rules),
4. building **verification** into the harness (code checks, independent judges,
   bounded repair loops) so correctness is caught outside the model.

Micromanaging a strong model's procedure — numbered "do step 1, step 2" plans,
repeated prohibitions, fear-based nagging — measurably hurts results and burns
the context budget `[S1][S2][S5]`. Weak/quantized models (ours today runs a
quantized Qwen server) still need more scaffolding than frontier models: keep
contracts and one worked example, keep the verification loops, and drop the
rest `[S3][S8]`.

## The four control layers — put every requirement in exactly one

| Layer | What goes here | Enforced by |
|---|---|---|
| **Harness guarantees** | Anything that must hold EVERY time: schema validation, lint rules (no `eval`, no external calls), citation rule checks, repair-round caps, `backoffLimit: 0`, run deadlines, resume guards | Code |
| **Contracts** | Output shape and interface rules the model must match: JSON field spec, SHAPE examples, the simulation skeleton, the severity ladder, exact palette values | Prompt + code re-validates |
| **Goal & success criteria** | What the deliverable must achieve and for whom: "a class-9 first-time learner can learn the chapter from this page alone" | Prompt |
| **Context** | The material the model needs to judge: source pack, ground truth, lesson, doctrine, palette, prior verdicts and errors | Prompt assembly |

Decision rule `[S3][S6]`: a requirement written as prompt prose that must never
be skipped is misplaced — move it into code. Prompt prose is read, weighed, and
sometimes deferred; code never forgets. Conversely, a judgement call (is this
explanation right for a 14-year-old?) does not belong as a code assertion —
give it to a reviewer stage with a rubric.

Match constraint strength to fragility `[S3]`: where several approaches are
valid (lesson prose, claim selection), give goals and criteria. Where a
sequence or interface is rigid (the ZivonSim skeleton, canvas rules, JSON
shape), state the exact contract and say it must be matched.

## Prompting rules (current era)

1. **Goal first, plan never.** State the objective, the audience, and the
   success test. Let the model choose the path. `pass@k`-style thinking: grade
   what it produced, not the route it took `[S2][S5]`.
2. **Be clear and explicit anyway.** Minimal ≠ vague. Ambiguity becomes noise:
   if a colleague with no context could misread the prompt, rewrite it `[S1]`.
3. **Say what TO do, not what not to do.** Prohibition lists ("NEVER X, do
   not Y, avoid Z") outperform nothing; pair each hard boundary with the
   positive alternative ("write plain-English definitions", "use values that
   appear verbatim in the source") `[S1][S4]`.
4. **Explain why.** Motivation generalizes: "the source is the whole universe
   of this page because the reader cannot consult any other book" teaches the
   model the *category* of violation, so it catches variants you never
   enumerated `[S1]`.
5. **One law, stated once.** Repeating the same constraint three times in one
   prompt signals panic, costs tokens, and does not improve compliance
   `[S1][S6]`. If a constraint keeps being violated, it is a harness problem:
   add a code check and feed violations back (see Catchers).
6. **Examples are the most reliable format lever.** 1–3 tightly structured
   SHAPE examples beat paragraphs of format description; keep them clearly
   marked "shape only — never reuse its content" `[S1][S3]`. Prefer examples
   over abstract style talk.
7. **Long-context layout:** put the big material (source pack, files, doctrine)
   above the ask; keep the task/goal and the output contract near the END of
   the prompt. Grounding instruction ("quote/cite as you go") belongs near the
   material `[S1][S6]`. Our prompts already do this — preserve it when editing.
8. **Structured output is a contract, not a guardrail.** JSON schemas,
   `response_format`, and field-level SHAPE specs are exactly how modern
   systems constrain output without coercing reasoning `[S1][S5]`. Keep them;
   keep prose instructions about format SHORT because schemas carry the load.
9. **Thinking models: do not script, cap, or disable thinking.** No
   "think step by step", no `<thinking>` mimicry, no token budgets aimed at
   the reasoning itself; send no completion caps at all - no `max_tokens`, no
   thinking budgets - and let adaptive thinking size itself within the
   server's own context `[S2][S4]`. Repo law (2026-11-04): never
   `enable_thinking=false`, and factory requests carry no `max_tokens` (a
   measured review call spent ~50k completion tokens thinking, then produced a
   correct verdict - thinking-heavy calls make any cap a truncation risk). If
   runaway thinking is measurable, fix it with scope-setting ("choose an
   approach and commit to it"), not a switch.
10. **Self-check sparingly.** "Before you finish, verify against [criteria]"
    catches real errors on some models; strong current models often verify
    unprompted, and bolted-on verification language causes over-verification
    and token waste `[S4]`. Prefer an external reviewer stage over in-prompt
    self-review rituals.
11. **Calibrate scaffolding to the model you actually run.** Quantized local
    models need clearer contracts and examples than frontier models; re-measure
    after every model change — harnesses encode stale assumptions about model
    behavior and rot quietly `[S6][S8]`.

## Designing the factory (multi-agent graph)

1. **One author, several judges.** Generation is a single reasoning call with
   full context (facts + lesson + blocks in one thinking cycle — graph v2's
   core decision). A reviewer must never be the author; gates are separate
   calls with their own context `[S2][S6]`.
2. **Reviewers get calibrated rubrics, not vibes.** Define the severity ladder
   exactly, define what FAIL means ("fail iff at least one fatal"), and give
   the judge a way out: unverifiable suspicions are reported as
   `unverified:` minor, never as fatal `[S2][S7]`. LLM-as-judge reliability is
   the price of automation — calibrate judges against human reading of run
   evidence (transcripts) regularly `[S2][S7]`.
3. **Honest reviewer framing.** Never "assume the page contains at least one
   defect" — that framing manufactures trivia-failures. Frame as: *hunt for
   real errors; if the draft is faithful, pass it with an empty issues array*
   `[S2][S7]`. This repo already fixed 03-check this way in v2; 09-review must
   keep the same posture.
4. **Catcher pattern (fail → bounded repair, never re-run upstream).** Every
   gate's verdict is a structured handoff to its paired fixer. Repair rounds
   are bounded; the caught issue flows downstream with its evidence, not a
   pipeline restart. This is the pipeline analogue of "give the agent
   verification tools and let it iterate on findings" `[S4][S6]`.
5. **Errors are context.** Validation/lint failures fed back into the retry
   transcript ("here is the exact violation; fix it, keep everything valid
   unchanged") are the single highest-value prompt content a generation stage
   can receive — far better than pre-emptive prohibition lists written to
   avoid those same violations `[S4][S6]`. Write feedback turns precisely and
   minimally.
6. **Partial credit keeps gates honest.** Minor issues ride along without
   failing the page; only the severities that genuinely mislead a learner
   block the page `[S2]`. Class-balanced gates: a reviewer must be able to
   pass a good page AND catch a bad one — a gate that always fails proves
   nothing `[S2][S7]`.
7. **State lives on disk, not in prompts.** Stage artifacts, fingerprints,
   status files, and resume guards make a long pipeline robust the way memory
   + git make a long agent session robust. Never ask a later stage to "remember"
   what an earlier stage did — read it from the artifact `[S4][S6]`.
8. **The harness must be observable or you cannot hill-climb.** Per-stage
   durations, per-call latency and token usage, in-flight heartbeats on long
   calls, verdicts and issue lists on disk: these are what turn "the run feels
   slow" into a diagnosis `[S2][S6]`. When a single call can legitimately run
   for many minutes (thinking model at ~20 tok/s), silence is not failure —
   but un-instrumented silence is undiagnosable. Log heartbeats.

## Context engineering per stage (the factory version)

For each stage prompt ask, in order `[S6]`:

1. What does this stage need to make its judgement? (source pack? ground
   truth? the lesson prose? the final files? the previous verdicts?) Include
   it — a reviewer cannot verify a pedagogical claim about "was this taught
   before it was tested" without the lesson text in context.
2. What does it NOT need? (example shells a builder doesn't reuse, doctrine
   excerpts a reviewer doesn't police, giant style dumps). Exclude it — the
   context window is a shared budget and the source pack is the expensive
   tenant `[S6]`.
3. Where is the boundary of the stage's universe? State it as ONE grounding
   law with motivation (see prompting rule 4), not as five scattered
   "never"s.
4. Is the output contract complete enough that code can validate it
   mechanically? If yes, keep the prose contract short.

## Authoring loop for any prompt change

Treat prompts like code, with behavioural evaluation instead of unit
certainty `[S3][S7]`:

1. Baseline first: run the stage without the change, read the evidence, name
   the observed failure class (e.g. "smuggled-in concepts", "JSON with prose
   around it").
2. Add the MINIMUM instruction/contract/context that addresses that class —
   goal rewording, one example, or a code check + feedback turn. Never add
   blanket scaffolding for a specific bug.
3. Test on a fresh instance with only that stage's context loaded; read
   transcripts (attempt artifacts under `runs/<run>/`). A failure should look
   *fair*: it is clear what the model got wrong and why `[S2]`.
4. Keep prompt-anchor unit tests (the substrings tests assert on) in sync in
   the same commit; update docs the same commit.
5. Measure the product metric behind the gate (human edit rate per generated
   topic, kid-tester comprehension) — a gate that passes everything or fails
   everything is broken scaffolding, not quality `[S2][S7]`.

## Anti-patterns — do not reintroduce these in this repo

- "Assume the page contains at least one defect" reviewer framing (manufactured
  failures) — fixed in 03-check v2, keep 09-review honest.
- The same constraint stated 2–3 times in one prompt ("verbatim" x3).
- Numbered execution plans for generation ("1. synthesize, 2. draft, 3. lay
  out") — the model plans its own reasoning; give it layers as deliverables,
  not steps.
- Reviewer asked to judge something whose material it was not given (checking
  "taught before tested" without the lesson text).
- Stale docstring/config defaults that contradict `_SERVER_DEFAULTS` — docs
  that lie are worse than none.
- `max_tokens` aimed at a thinking model (even a huge cap counts against
  thinking tokens and becomes the failure point - removed from this factory
  entirely 2026-11-04); or disabling thinking.
- Prompt prose enforcing guarantees code should enforce (citation presence,
  no-`eval`, palette-only colors are RULE CHECKS, not prayers).
- Silent long-running calls with no heartbeat or timing logs.
- Micromanaging the Visual Builder's creativity: its CONTRACT (skeleton,
  bridge rules, lint) is rigid because the interface is rigid — keep contracts
  there and give the design work itself room.

## Where this applies in Zivon today

- `factory/agents.py` — 02-generate (goal-first layers + contracts + SHAPE
  example), 03-check (rubric ladder + honest framing + lesson context),
  04-repair (verdict-in, minimal fix contract).
- `factory/interactive.py` — rigid-contract example of the Degrees-of-freedom
  rule: hard skeleton + lint-in-retry, creative latitude inside it.
- `factory/review.py` / `factory/reviewfix.py` / `factory/fixloop.py` —
  catcher pattern, judge way-out, verdict-as-handoff.
- `factory/llm.py` — errors-as-context feedback turns; call-level logging.
- `factory/stages.py` / `factory/artifacts.py` — on-disk state, resume,
  bounded loops, timing logs.
- Voice tutor (Phase 2): the same posture for Evon's doubt-tutoring prompt —
  personality + page context + goal, not a scripted answer flow.

Read [references/sources-and-evidence.md](references/sources-and-evidence.md)
before a contested design decision (e.g. "should we add another guardrail to
the generate prompt?") — it dates every rule and says where each came from.
