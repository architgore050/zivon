# Measurement

The page exists to produce one action. Measurement is how you find out whether
it did, and why not when it didn't.

`[E]` marks published data or a standard, `[P]` practitioner practice.

## 1. One primary metric

Define it before launch, in one sentence, with a denominator and a window:

> **Primary action rate** = *unique sessions that start a chapter* ÷ *unique
> sessions that see the landing page*, over a 28-day window.

Rules:

- **Name the event that counts.** "Start a chapter" is an event, not a vibe.
- **Name the denominator.** Page views, sessions, or unique visitors — pick one
  and never compare across definitions.
- **Name the window.** A weekly and a 28-day number answer different questions.
- **One primary metric.** Secondary metrics explain it; they do not compete with
  it. A dashboard with nine "north stars" has none.

Everything else on this page — scroll depth, demo plays, time on page — is a
**diagnostic**: it explains why the primary metric moved, and it is never
optimised directly.

## 2. The event set

The frozen spec already names the landing events (`landing_view`, `demo_play`,
`cta_try`, `cta_login` in `REQUIREMENTS.md` §10.1; three of them are repeated in
`skills/zivon-frontend-product-skills/references/screens-and-states.md`).
Use those names; do not invent a parallel scheme. `chapter_open` is in the same
document's public-event register. `faq_open` below is a proposed diagnostic: it
must be added to `docs/specs/observability/instrumentation-map.csv` in the same
PR that ships it, or it does not ship.

| Event | Fires when | Useful properties | What it diagnoses |
|---|---|---|---|
| `landing_view` | the page becomes visible | `locale`, `referrer_class`, `hero_variant`, `viewport_class` | the denominator; segment everything by these |
| `demo_play` | the reader starts the real voice turn | `seconds_played`, `completed`, `blocked` | whether the proof is being consumed or skipped |
| `cta_try` | the primary button is pressed | `placement` (hero / final), `hero_variant` | intent, before any friction |
| `cta_login` | the reader chooses sign-in instead | `placement` | whether the action was misread |
| `chapter_open` | a chapter actually opens (the outcome) | `class`, `chapter`, `locale` | the real conversion, once it exists |
| `faq_open` | a FAQ item is expanded | `question_id` | which objection is live but unanswered |

Rules that keep the set honest:

- **No free text from a child.** Categories and counts only. No typed doubt, no
  name, no school.
- **Consent-gated.** Analytics follows the same consent rules as the rest of the
  product; a declined consent means no event beyond what the page needs to
  function.
- **No fingerprinting, no cross-site identity, no ad-tech pixels.** The page is
  for minors; the measurement plan must be defensible to a parent.
- **A variant is a property, not a new event.** `hero_variant` on
  `landing_view`, not `landing_view_v2`.

## 3. The funnel

```
landing_view
   -> first-screen exit          (did the hero hold them?)
   -> demo_play                  (did the proof get consumed?)
   -> scroll to the offer        (did the argument hold?)
   -> cta_try                    (did they intend to act?)
   -> chapter_open               (did the action complete?)
```

Each drop-off has a different cause and a different fix:

| Drop | Likely cause | Where to look |
|---|---|---|
| view → immediate exit | the first screen did not say what this is, or said it to someone else | the 5-second test, the hero copy deck |
| no `demo_play` | the demo is invisible, below the fold, or looks like a video ad | position, label ("20 seconds, with transcript"), poster |
| demo started, not finished | too long, no transcript, audio failed | `seconds_played`, `blocked`, the transcript |
| scroll stops before the offer | a section raised an objection it did not answer | the storyboard's objection column |
| `cta_try` without `chapter_open` | friction after the click: account, loading, an error | the destination screen, not the landing page |

**The most common misdiagnosis** is treating a post-click failure as a landing
page failure. If `cta_try` is healthy and `chapter_open` is not, the page did its
job and the next screen broke.

## 4. Scroll depth and other diagnostics

Scroll depth is useful and easy to misuse.

- **Use it to find the section where readers stop.** A sharp drop after a
  specific section is a signal that the section failed.
- **Do not use it as a goal.** A page that people scroll to the bottom and leave
  has a conversion problem; "high engagement" is not a win.
- **Report it as a distribution**, not an average. "70% reach the offer" is
  useful; "average scroll 62%" hides two different audiences.
- **Beware the false floor.** A section that looks like the end of the page
  stops scrolling even when content follows `[E]`. If the drop is at a
  full-viewport block, suspect the design, not the copy.

Same rule for **time on page**: a long time can be reading, or a stuck video, or
a tab left open. It diagnoses nothing on its own.

## 5. Qualitative signals

Numbers tell you *that* something failed. Five short tests tell you *what*.

| Test | How | What a failure looks like |
|---|---|---|
| **5-second test** | show the first screen for 5 s, hide it, ask four questions | "it's some kind of learning app" |
| **10-second recall** | read for 10 s, then say the promise back | they repeat the category, not the promise |
| **Differentiator** | "what makes this different?" after 30 s | "it's AI" or "it's interactive" — the category again |
| **Cost guess** | "what does this cost?" | "I don't know" or a wrong guess (the page hid it) |
| **Next-action guess** | "what would you do next?" | they name a button that is not the primary one |

Run them with **five people who are not building the product**, ideally of the
target age. Record verbatim answers; do not summarise them into agreement.

Two more that are worth the time:

- **The sceptic read.** Give the page to someone whose job is to doubt claims
  (a teacher, a parent, a reviewer). Ask them to find one thing they do not
  believe. That sentence is your weakest claim.
- **The task read.** Ask a student to find the answer to one specific doubt using
  the page plus one click. Time it. If it takes more than a minute, the page is
  routing badly.

## 6. Benchmarks, used honestly

The only large public benchmark worth quoting is Unbounce's 2024 Conversion
Benchmark Report: 57 million conversions across 41,000+ landing pages, July
2023–July 2024, median conversion rate **6.6%**, with education at **8.4%** and
SaaS at **3.8%** `[E]`.

Three warnings before anyone puts that number on a slide:

1. **It is vendor data from lead-generation and signup pages**, not from
   "opened a chapter" actions on an education product for minors.
2. **The definition of "conversion" varies** across the pages in the sample.
3. **A median is not a target.** Half of the pages in a sample are below it by
   construction.

Use it to answer "is 2% catastrophically bad or normal?" — not to set a goal. Set
the goal from your own baseline, then improve it.

The same report finds a correlation between lower reading difficulty and higher
conversion (grade 5–7 copy at 11.1% median vs college-level at 5.3%) `[E]`. It
is a correlation across pages that differ in many ways, not a causal finding —
but it is consistent with the plain-language evidence, and it costs nothing to
write shorter sentences.

## 7. A/B tests

A landing-page test is only worth running if it can change a decision.

- **One variable per test.** Two changes and you learn nothing about either.
- **Vary the strategy, not the synonyms.** "See why the ray bends" vs "Watch the
  ray bend" is a wording test with a predictable null result. "Outcome headline"
  vs "objection headline" is a strategy test.
- **Decide the sample size and duration before you start.** Stopping when the
  numbers look good inflates false positives; this is arithmetic, not opinion.
- **Do not test while changing something else.** A deploy, a campaign change, or
  a school holiday contaminates the result.
- **Pre-register the decision rule**: "if variant B raises `chapter_open` by ≥X
  relative without lowering demo completion, ship B; otherwise keep A."
- **Never test honesty.** You do not A/B whether to disclose a limitation.

At low traffic, A/B testing is usually the wrong tool: five qualitative sessions
will find the problem faster than a six-week test that never reaches
significance. Say so in the plan rather than running a test that cannot conclude.

## 8. Metrics to refuse

| Metric | Why it is refused |
|---|---|
| Pageviews | measures traffic, not the page |
| Bounce rate (as a goal) | a one-page visit that converts is a success |
| Time on page (as a goal) | rewards confusion |
| Scroll depth (as a goal) | rewards length |
| "Engagement" score | undefined, and usually a composite of the above |
| Click-through on a secondary link | measures the wrong action |
| Social shares | not the job |
| Any number without a denominator | not a number |

## 9. The measurement plan

Put this in the PR, filled in:

```
Primary action:      <event>            (e.g. chapter_open)
Denominator:         <landing_view, unique session>
Window:              <28 days>
Baseline:            <current rate, or "none - first measurement">
Target:              <what would count as working>
Diagnostics:         <demo_play rate, offer reach %, faq_open top 3>
Qualitative:         <5-second test n=5, sceptic read n=2, dates>
Variant plan:        <none | one variable, decision rule, duration>
Privacy:             <consent gate, no child free text, no ad pixels>
Review date:         <when the numbers are read, by whom>
```

A page can ship without a target. It cannot ship without a denominator.
