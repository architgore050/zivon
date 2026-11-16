# Critique sheet

One sheet per scorer. Score alone, then compare. Copy into the PR.

---

## Header

```
Page:            /
Version / commit:
Scorer:
Date:
Viewed at:       360 px  |  1280 px  |  JS off  |  reduced motion
Artifacts read:  brief  |  storyboard  |  copy deck  |  claim ledger
```

## 1. Gates (check first — a tripped gate ends the review)

- [ ] **G1** No fabricated or unlabelled testimonial, review, or count
- [ ] **G2** No scarcity or urgency the system does not enforce
- [ ] **G3** No "official"/"affiliated"/"certified"/"recommended" without a document
- [ ] **G4** No privacy or safety claim the code does not implement
- [ ] **G5** No doctrine §10 devices (ruled grid, handwritten body, taped cards, language bar, voice dock)
- [ ] **G6** No autoplaying audio or video
- [ ] **G7** No WCAG 2.2 AA failure on the critical path
- [ ] **G8** The argument does not require JavaScript
- [ ] **G9** One primary CTA per screen
- [ ] **G10** Claim ledger present, and every claim has an evidence row

Any box unticked → verdict is **Request changes**. Name the gate in the first
line of the review.

## 2. Scores

Score 1–5 using the anchors in
[../references/critique-rubric.md](../references/critique-rubric.md). Every score
below 4 needs evidence.

| # | Dimension | Score | Evidence (quote / screenshot / number) |
|---|---|---|---|
| D1 | Hook — does the first screen stop a stranger? | /5 | |
| D2 | Clarity — is the argument followable in one pass? | /5 | |
| D3 | Desire — does the reader want the outcome? | /5 | |
| D4 | Proof — is every claim paid? | /5 | |
| D5 | Differentiation — could a competitor publish this? | /5 | |
| D6 | Craft — is the execution at the level the claim promises? | /5 | |
| D7 | Accessibility — can everyone the page is for use it? | /5 | |
| D8 | Performance — does it load for the reader it is for? | /5 | |
| D9 | Honesty — is everything on the page true? (5 or no ship) | /5 | |
| | **Total** | **/45** | |

## 3. The four tests

| Test | Result | Note |
|---|---|---|
| Five-second test (n≥5): what is this / who / what can you do / what does it cost | /4 correct | |
| Heading-only read: do the headings form a sentence? | Y / N | |
| Swap test: put a competitor's wordmark on it — does it still work? | Y / N | |
| JS-off read: is the argument intact? | Y / N | |

## 4. Findings

Use the repo's severity scale. One finding per row.

| # | Severity | Location | Finding | Evidence | Fix |
|---|---|---|---|---|---|
| 1 | blocker / major / minor / nit / question / praise | | | | |
| 2 | | | | | |
| 3 | | | | | |

Severity definitions:

- **blocker** — cannot ship: a gate, a false claim, an inaccessible critical
  path.
- **major** — ships badly: the argument breaks, the hero fails the five-second
  test, the proof is absent for the main claim.
- **minor** — a real cost, not fatal: a section that could be cut, a weak
  heading, a slow artifact.
- **nit** — taste, formatting, wording.
- **question** — you are not sure, and the author can answer it.
- **praise** — something that worked, named specifically, so it is repeated.

Review top-down: report a design or argument failure first and stop there. Line
notes on a page that needs restructuring are wasted effort.

## 5. Verdict

- [ ] **Ship** — no gate tripped, every dimension ≥ 3, honesty = 5, total ≥ 36
- [ ] **Ship with follow-ups** — no gate, every dimension ≥ 3, total 30–35,
      shortfalls have owners and dates
- [ ] **Request changes** — any gate, any dimension ≤ 2, or honesty < 5
- [ ] **Restart** — D1, D4 and D5 all ≤ 2

```
Rationale (two sentences):
Follow-ups (owner, date):
```

## 6. The three questions

Answer honestly; they override a close score.

```
Would I send this page to a 15-year-old I know, without explaining it first?   Y / N
Is there a sentence I would be uncomfortable defending to a parent and a teacher
in the same room?                                                             Y / N
If it converted twice as well but kept one dishonest element, would I keep it? Y / N
```

A "no / yes / yes" pattern is a **request changes**, whatever the total says.

## 7. Second scorer

```
Scorer 2:
Their total:
Where the two scores differ by ≥ 2:
Evidence that settles it:
Re-scored after evidence:
Final total:
```

Disagreement is settled by re-running the test, not by seniority. If the evidence
is absent, the lower score stands.
