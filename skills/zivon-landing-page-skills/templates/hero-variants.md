# Hero variants

A hero test compares **strategies**, not synonyms. "See why the ray bends" vs
"Watch the ray bend" is a wording test with a predictable null result; "outcome"
vs "objection" is a strategy test that can change what the page says.

Run this when the hero is the bottleneck — low `cta_try` with healthy
`landing_view`, or a five-second test where nobody can say what the product is.

---

## 1. The five strategies

Fill all five. Each must be a genuinely different argument.

| # | Strategy | The bet | Serves | Its risk |
|---|---|---|---|---|
| 1 | **Outcome** — the reader's life, better | the outcome is desired and specific | cold traffic | it can sound like every competitor |
| 2 | **Mechanism** — how it is done, uniquely | the mechanism is the differentiator | solution-aware traffic | opaque to a reader who does not know the category |
| 3 | **Objection** — the doubt, named and answered | the doubt is the actual blocker | product-aware traffic, referrals | defensive; needs the product to genuinely resolve it |
| 4 | **Tension** — the thing that is wrong, named | the reader recognises it instantly | problem-aware search traffic | negative tone for a young audience |
| 5 | **Artifact** — point at the thing itself | the artifact is remarkable on sight | everyone, if the artifact is real | requires a real artifact; fails if it is a mockup |

### The template

```
Variant A - Outcome
Headline:
Subhead:
Proof line required:
Primary CTA:
What would have to be true for this to win:

Variant B - Mechanism
...

Variant C - Objection
...

Variant D - Tension
...

Variant E - Artifact
...
```

## 2. What each variant must hold constant

Only the strategy changes. Everything else stays identical, or the test measures
two things:

- the subhead's length and structure,
- the CTA label,
- the artifact,
- the section order below the fold,
- the page's performance,
- the audience and the traffic source.

## 3. Choosing without traffic

At low volume an A/B test never reaches significance, and a six-week test that
cannot conclude is a way of not deciding. Use the sequential protocol instead.

1. Write the five variants.
2. Show each to **five people** from the target audience, one at a time, for five
   seconds. Ask the four questions (what is this / who is it for / what can you do
   / what does it cost).
3. Score each variant: how many of the four questions were answered correctly.
4. Keep the top two. Discuss which one carries the differentiation better.
5. Ship one. Re-run the five-second test on the live page after a week.

This is not statistics; it is cheap evidence, and it is far better than a
conversion test that cannot conclude.

## 4. Running a real test

```
Primary metric:      <event> / <denominator>
Guardrails:          demo completion, chapter_open, qualitative recall
Traffic split:       50/50, same source, same device mix
Sample size:         <decided before launch>
Duration:            <decided before launch>
Decision rule:       <pre-registered, e.g. "B ships if chapter_open rises >= 15%
                      relative with no guardrail regression">
Stop rule:           run to the decided sample; do not stop early on a good day
```

Rules:

- **Pre-register the decision rule.** A rule written after the result is a
  rationalisation.
- **Do not stop when it looks good.** Early stopping inflates false positives;
  this is arithmetic, not opinion.
- **Do not change the page mid-test.** A deploy or a copy tweak contaminates it.
- **Segment by traffic source.** A hero that wins on search traffic can lose on
  referrals, and averaging the two hides the only interesting result.
- **Never test honesty.** Whether to disclose a limitation, a cost, or a
  privacy behaviour is not a variant.

## 5. What counts as a win

A variant wins only if **all** of these hold:

- the primary action rate improves by the pre-registered margin;
- no guardrail regresses (demo completion, `chapter_open`, error rate);
- the five-second test still passes for the new hero;
- the new hero does not require a claim the page cannot prove.

A hero that lifts clicks but drops `chapter_open` did not work — it produced
intent the product could not satisfy, which is worse than a lower click rate.

## 6. Record sheet

```
Variant     Impressions   cta_try   chapter_open   demo_complete   Recall (0-4)
A
B
C
D
E

Winner:
Margin:
Guardrails:
Decision taken:
Date:
Follow-up:
```

## 7. Anti-patterns

- **Testing colour or a synonym.** Nothing to learn.
- **Testing five variants at once with low traffic.** Nothing will conclude.
- **Declaring a winner from a screenshot review.** Reviewers are not the audience.
- **Keeping the loser's copy in the code.** Delete it; a dead variant is a claim
  nobody defends.
- **Testing a hero the proof cannot support.** If the winning headline promises
  something the page does not show, the win is a future refund.
