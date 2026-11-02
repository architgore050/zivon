# Session log — 2026-11-02 — design doctrine flow (open-ended design context)

The pipeline held design info by hand: 06's prompt carried a hardcoded token
list (`var(--ink), var(--paper), ...`) and an inert "Reference: <doctrine
path>" line the model cannot act on (models can't read files), 04-draft specs
diagrams with no palette at all (the model invented colours), and 10-review
policed style against nothing. The question asked: what happens when the
doctrine changes again? Answer: it must be a system, not another excerpt.

## The system

`factory/design.py` is now the single point where the factory touches design.
It hands the LIVE documents to model stages at build time:

- **Doctrine document** — `paths.doctrine`, injected verbatim (no section
  extraction anywhere, so renumbering or rewriting sections needs no pipeline
  change).
- **Example pages** — `paths.doctrine_examples` glob
  (`docs/frontend/design-doctrine*.html`); every match is injected into 06.
  A new example file joins every future run automatically (proved by a
  fake-repo-tree test). The dead `doctrine_example` key (nothing consumed it)
  is gone.
- **Palette** — CSS custom properties parsed verbatim from
  `frontend/assets/zivon.css`. Canvas code cannot use `var(--x)`, so the hex
  values are handed over; parsing keeps generated colours identical to the
  shell that renders around them.
- **Budget** — `limits.max_chars_design_context` (48k; shipped doctrine +
  examples ≈ 41k). Over-budget fails loudly with the numbers; never silently
  truncated.

Stage composition: 04-draft gets doctrine + palette (it specs diagrams);
06-interactive gets doctrine + examples + palette + a medium-translation
BRIDGE line (the shell is renderer-built; you fill one canvas sim inside a
card; examples are single-file demos — read them for the visual language,
never copy their structure); 10-review gets doctrine + checklist item 5
(clear doctrine violation = major; one that misleads the learner about what
moves or what is correct = fatal). Doctrine semantics are no longer restated
in any prompt — the injected document carries them.

## Accepted gap (documented, not hidden)

`render.py` / `zivon.css` implement the pre-§10 shell. The doctrine's §10
lesson shell (ruled grid, taped cards, language bar, Caveat body) is Phase 4
(Day 9) frontend work, validated against the example pages first — the
doctrine's own §10.11 risk list (baseline alignment on low-end Android) is
open. Sims and diagrams following §10's palette semantics is compatible with
the current shell (palette unchanged), so injection is forward-safe now.
Kalam font not vendored (needed only for Devanagari).

## Also

- Integration test's fake tree now copies `docs/frontend/design-doctrine*`
  (04/06/10 read them at build time in the subprocess run).
- Unit tests: `test_design.py` (6 tests incl. the open-endedness proof);
  prompt-promise tests in test_interactive / test_agents_draft / test_review
  assert the verbatim doctrine head, glob-picked example markers, parsed
  palette hex, and the absence of the old held token list. Suite: 176 tests.

## Not done / next

- First real inference-server run (Gate B): measure whether the enlarged
  04/06 prompts fit the server's context; tune `max_chars_design_context` or
  per-stage composition from measurements if not.
- Possible mechanical lint: generated page.css colours checked against the
  palette (P2 idea, not started).
- §10 shell adoption in `render.py` / `zivon.css` — Phase 4, Day 9.
