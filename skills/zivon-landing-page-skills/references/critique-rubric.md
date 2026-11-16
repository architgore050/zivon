# Critique rubric

A scored review of a landing page. Nine dimensions, five anchors each, plus hard
gates. The score is a checklist with a number attached — it exists so two people
can disagree about evidence instead of taste.

## 1. How to run a critique

1. **Read the brief, storyboard, and claim ledger first.** A page judged without
   its argument is judged as decoration.
2. **Score alone, then compare.** Two independent scorers, no discussion until
   both sheets are filled. Discussion first produces consensus, not evidence.
3. **Top-down.** Judges the design and the argument before the copy, and the copy
   before the pixels. A fundamental design failure makes line notes pointless —
   report it and stop.
4. **Evidence over opinion.** Every score below 4 needs a quoted line, a
   screenshot, or a measurement. "It feels cluttered" is not a finding.
5. **Find the blockers first.** A page with a blocker is not "mostly good"; it is
   not shippable. Name it in the first line of the review.

The author never scores their own page.

## 2. The nine dimensions

Score each 1–5. Anchors are behaviour, not adjectives.

### D1. Hook — does the first screen stop a stranger?

| Score | Anchor |
|---|---|
| 1 | The first screen could belong to any product in the category; no promise is visible without scrolling |
| 3 | A promise is present and specific, but the artifact is decorative or the CTA competes with a second action |
| 5 | In five seconds a stranger can say what this is, who it is for, why it is different, and what to do next — and one of those answers is remarkable |

Evidence: the five-second test transcripts, a 360 px screenshot.

### D2. Clarity — is the argument followable in one pass?

| Score | Anchor |
|---|---|
| 1 | Sections are a list of nouns; the reader cannot say what the product does after reading the whole page |
| 3 | The argument holds but needs a second read in one or two places; jargon survives in a section or two |
| 5 | One read, one argument; each section answers the objection the previous one raised; the headings alone tell the story |

Evidence: the heading-only read, the two-sentence summary written by a stranger.

### D3. Desire — does the reader want the outcome?

| Score | Anchor |
|---|---|
| 1 | The page describes features and category; nothing is framed as the reader's life getting better |
| 3 | The outcome is stated but abstract ("learn better", "improve results") |
| 5 | The outcome is concrete, small, and recognisable — the reader can picture the moment it happens, and it is a moment they already wanted |

Evidence: the "so what" ladder from the brief; a quote from a test reader naming
what they wanted.

### D4. Proof — is every claim paid?

| Score | Anchor |
|---|---|
| 1 | Claims outnumber evidence; at least one number, person, or capability is unverifiable or invented |
| 3 | Most claims have evidence, but at least one is asserted and left unpaid; the evidence for the main claim sits far from it |
| 5 | Every claim has a ledger row and the evidence is on the page or one click away; the strongest proof is an artifact, not a sentence |

Evidence: the claim ledger, with every row's location checked.

### D5. Differentiation — could a competitor publish this page?

| Score | Anchor |
|---|---|
| 1 | Swap the wordmark and the page still works; the mechanism is the category's mechanism |
| 3 | One specific element is uniquely this product's, but it sits below the fold or in a single section |
| 5 | The differentiator is in the first screen, shown rather than claimed, and cannot be copied without building the product |

Evidence: the swap test, run by someone who does not work on the product.

### D6. Craft — is the execution at the level the claim promises?

| Score | Anchor |
|---|---|
| 1 | Misaligned type, inconsistent spacing, more than one pen mark, gradients or soft shadows, a stock photo standing in for the product |
| 3 | Competent Field Notes execution with one or two lapses: a second annotation, an inconsistent corner radius, a card where the doctrine wants paper |
| 5 | Typography, spacing, and one annotation all obey the doctrine; the artifact is real and well framed; the page looks like nothing else in the category and still looks calm |

Evidence: side-by-side with `docs/frontend/design-doctrine-example.html`, at 360 px
and 1280 px.

### D7. Accessibility — can everyone the page is for actually use it?

| Score | Anchor |
|---|---|
| 1 | Fails a WCAG 2.2 AA criterion (contrast, focus, target size, captions); JavaScript required to read the argument |
| 3 | Keyboard-reachable and readable at 360 px, but one criterion is marginal (a focus ring obscured, a target under 44 px, a transcript behind JS) |
| 5 | WCAG 2.2 AA met and evidenced; keyboard and screen-reader pass; reduced motion honoured; the argument readable with JS off; audio has a transcript and no autoplay |

Evidence: the a11y checklist, the keyboard pass, the JS-off screenshot, the
contrast values from doctrine §8.

### D8. Performance — does it load for the reader it is for?

| Score | Anchor |
|---|---|
| 1 | No LCP/INP/CLS measurement, or any of the three in the "poor" band |
| 3 | All three Core Web Vitals "good" in the lab, but no real-device run, or the demo island blocks the interaction path |
| 5 | All three good in the lab *and* on a low-end Android on a real network; no long task over 200 ms; the page is readable before the island loads; numbers are in the PR |

Evidence: the lab report, the device run, the bundle sizes.

### D9. Honesty — is everything on the page true?

**No partial credit.** Scored 5 or it does not ship.

| Score | Anchor |
|---|---|
| 1 | A fabricated testimonial, a fake countdown, an "official"/affiliation claim without a document, a privacy sentence the code contradicts, or a capability described that is not shipped |
| 3 | Nothing fabricated, but a claim is misleading by framing (an undated number, a limitation omitted where it changes the decision) |
| 5 | Every claim is true, sourced, and dated where perishable; limitations are stated where they change the decision; no manufacturer urgency; no borrowed authority |

Evidence: the claim ledger, the proof audit (§8 of
[proof-and-trust.md](proof-and-trust.md)), the privacy copy checked against the
code.

## 3. Hard gates

Any one of these means **request changes**, regardless of the score.

| Gate | Condition |
|---|---|
| G1 | A fabricated or unlabelled testimonial, review, or count |
| G2 | A scarcity or urgency claim the system does not enforce |
| G3 | An "official", "affiliated", "certified", or "recommended" claim without a document |
| G4 | A privacy or safety claim the code does not implement |
| G5 | Doctrine §10 devices on the landing page (ruled grid, handwritten body, taped cards, language bar, voice dock) |
| G6 | Autoplaying audio or video |
| G7 | A WCAG 2.2 AA failure on the critical path |
| G8 | The argument requires JavaScript |
| G9 | More than one primary CTA on a screen |
| G10 | A claim ledger missing, or a claim with no evidence row |

## 4. Verdict

| Verdict | Condition |
|---|---|
| **Ship** | No gate tripped; every dimension ≥ 3; honesty = 5; total ≥ 36/45 |
| **Ship with follow-ups** | No gate tripped; every dimension ≥ 3; total 30–35; the shortfalls are named with owners and dates |
| **Request changes** | Any gate tripped, any dimension ≤ 2, or honesty < 5 |
| **Restart** | D1, D4, and D5 all ≤ 2 — the page has no promise, no proof, and no difference; polish will not fix it |

The total is out of 45 and is **not a percentage**. A 40 with a tripped gate is a
fail; a 32 with no gates is a ship with follow-ups.

## 5. When two scorers disagree

1. **Compare evidence, not scores.** Which quoted line, screenshot, or number
   supports each anchor?
2. **Re-run the test that settles it.** Disagreement about the hook is settled by
   the five-second test; about differentiation by the swap test; about proof by
   opening the ledger.
3. **If the evidence is absent, the lower score stands** until someone produces
   it. Optimism is not evidence.
4. **Never average away a blocker.** Two scorers who disagree about honesty do
   not meet in the middle; they check the code.

## 6. Three questions that beat the score

When the total is close and the argument is about whether it is good enough:

1. **Would you send this page to a 15-year-old you know, without explaining it
   first?**
2. **Is there one sentence on it you would be uncomfortable defending to a
   parent and a teacher, in the same room?**
3. **If it converted twice as well but you had to keep one dishonest element,
   would you keep it?** A yes here means the page has already failed D9 — and
   the answer is the reason this rubric exists.
