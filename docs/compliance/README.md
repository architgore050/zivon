# `docs/compliance/` — third-party content compliance

This folder records **what Zivon may reuse from third-party educational sources,
under what conditions, and with what user-facing copy**. It exists so that an
engineer, a reviewer, or a future agent can answer "may we ship this?" without
re-doing the research or guessing.

> **Not legal advice.** Every file here is desk research and a product risk
> decision. Where the law is unsettled the memo says so and routes the question
> to counsel (`CQ-##`). A confident-sounding sentence in this folder is not a
> substitute for an opinion from an Indian lawyer.

## Scope

**In scope**

- CBSE question papers, official sample question papers (SQPs), and marking
  schemes (Class 10 Science / Physics section, Class 12 Physics).
- Attribution, non-affiliation and takedown copy for any surface that carries
  third-party exam content.
- The source metadata and publish gates that make the policy enforceable.

**Out of scope (separate decisions)**

- NCERT textbook text — governed by `sources/catalog.json` and `AGENTS.md`.
- ICSE/ISC, state boards, and third-party "PYQ" websites.
- Children's data, DPDP, and privacy — see `docs/backend/` and the privacy page.
- Voice vendor terms (Gnani) — see `docs/specs/voice-agent/`.

## Current status

**`DEC-COMP-001` is active: `EXAM_CONTENT_MODE=blueprint_only` is the shipping
default.** Verbatim CBSE items may not reach a student or a public page until a
clearance record exists in [`decision-log.md`](decision-log.md) — written CBSE
permission or a written Indian-counsel opinion. A legal notice does not create
that permission. See [`cbse-exam-content.md`](cbse-exam-content.md) §0 and §6.

## File map

| File | What it is | Read it when |
|---|---|---|
| [`cbse-exam-content.md`](cbse-exam-content.md) | The research memo: statute, case law, CBSE's own terms, 18 findings (F-01…F-18), content-type matrix, decision, P3 implementation contract, risk register, permission-letter template | You are changing exam-content sourcing, ingest, or publish behaviour |
| [`decision-log.md`](decision-log.md) | The decisions (`DEC-COMP-001`…`008`), the clearance register, the ten counsel questions, and the takedown register | You need the current rule, or you are recording a clearance/takedown |
| [`notices.md`](notices.md) | Exact EN/HI user-facing copy (`N-01`…`N-05`), the placeholder contract, and the removal path | You are rendering an exam surface or changing copy |
| [`sources.md`](sources.md) | Source register (`S-01`…`S-21`) with URLs, dates, fetch status, hashes, and blocked-method notes | You are checking a claim, or re-verifying before a review |

## How decisions are recorded

The chain is deliberate and one-way:

```
S-NN  source (what we read, when, and whether it actually loaded)
  → F-NN  finding (what it establishes, with a confidence tag)
    → DEC-COMP-NNN  decision (what Zivon does, with evidence and owner)
      → N-NN  notice copy (what the student sees)
        → test (docs contract, so the chain cannot rot silently)
```

- **Ids are stable.** `S-`, `F-`, `DEC-COMP-`, `CQ-`, `N-`. Never renumber; add.
- **Confidence tags:** `[STRONG]` (primary source, direct support),
  `[MODERATE]` (primary source plus inference, or a split authority),
  `[WEAK]` (arguable, not relied on), `[ASSUMPTION]` (unverified working
  premise). Every finding carries one.
- **A decision without evidence is not a decision.** `DEC-COMP-*` rows cite the
  findings they rest on.
- **Silence is not clearance.** No reply from CBSE, no lawyer's letter, and no
  "everyone does it" is recorded as `none`.
- **Changing a notice is a decision change.** Edit `notices.md` and the decision
  log together; the contract test fails otherwise.

## Review cadence

Review this folder **quarterly** (next: 2027-02-15) and immediately when any of
these triggers fires:

1. A new CBSE session's papers or SQPs are published (every spring).
2. CBSE updates its Website Policy or publishes a reuse circular.
3. CBSE replies to the permission request (`Appendix A` of the memo).
4. Counsel answers any `CQ-##`.
5. A takedown request or legal notice arrives.
6. The Copyright Act or Rules are amended (2026 activity is tracked as a watch
   item, not a change).
7. Zivon changes commercial model (free ↔ paid) or starts publishing CBSE items
   in a new language.

## Rules for contributors

- Do not publish a verbatim CBSE item without a clearance id that resolves in the
  register. The publish gate enforces it; do not bypass it "for a demo".
- Do not edit a verbatim item — no typo fixes, no re-numbering, no translation
  (`DEC-COMP-003`, `DEC-COMP-004`).
- Do not add a new notice string without a `N-##` id and a placeholder entry.
- Do not add a source without a URL, a retrieval date, and an honest status.
- Do not describe this folder as legal clearance. It is a documented risk
  position with named open questions.
