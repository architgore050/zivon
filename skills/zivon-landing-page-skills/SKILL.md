---
name: zivon-landing-page-skills
description: Designs and critiques Zivon's landing page as an ad rather than a SaaS template - one promise, one action, a chosen narrative spine, honest proof, and Field Notes base-doctrine art direction. Use when writing or reviewing the landing page or any public hook page (homepage hero, above-the-fold hero, campaign page, waitlist page, for-schools page), when choosing a narrative framework, drafting headlines, subheads, CTAs, conversion copy or microcopy, storyboarding sections, art-directing a hero, auditing a claim or a piece of social proof, budgeting motion or Core Web Vitals, or scoring a page against the critique rubric. Also use when asked why the landing page is not converting, before a landing-page PR, a hero A/B test, or a founder visual verdict.
license: MIT
compatibility: Reads the repo's docs/frontend/design-doctrine.md, docs/product/ and docs/compliance/ for context; no network, secrets, or model calls. Research sources were fetched 2026-11-16 - re-verify perishable numbers (benchmarks, thresholds, platform rules) before citing them in a decision.
metadata:
  owner: zivon
  version: "1.0"
  evidence_date: "2026-11-16"
---

# Zivon Landing Page Skills

How to design a landing page that works like an ad: one person, one promise,
one action, and nothing on the page that has not earned its place.

The page is not a brochure and not a feature list. It is a single argument
delivered to a stranger who did not ask for it. Read it as an ad, judge it as an
ad, and cut it like an ad.

## The stance

Five claims this bundle is built on. Each is argued and sourced in
[references/sources.md](references/sources.md); `[E]` marks research or a
published standard, `[P]` marks practitioner opinion, and `[R]` marks a rule
this repo has already decided.

1. **A landing page is an ad, not a site.** It has one job and one audience.
   Everything that serves a second job dilutes the first `[P]`.
2. **The first ten seconds decide the visit.** Visitors triage pages ruthlessly
   and leave fast; a clear value proposition within ten seconds is what buys
   the next two minutes `[E]`.
3. **The first screen is the ad.** Above the fold, the offer, the proof, and
   the action; below the fold, only what the first screen promised `[E][P]`.
4. **Specificity is the cheapest credibility.** A number, a noun, a real
   screenshot, or a named source outranks any adjective `[E][P]`.
5. **Design is the argument's tone of voice.** A page that looks like a
   template argues that the product is a template `[P]`.

The corollary matters as much: **a beautiful page that cannot say what it is in
one sentence has failed, and so has an ugly page that says it perfectly.** The
two failures are equally expensive.

## When to use this

Use it when any of these is true:

- You are writing, redesigning, or reviewing the landing page (`/`) or any
  public hook page: campaign page, waitlist page, for-schools page, a new
  subject or class launch page.
- You need a hero, a headline, a subhead, CTA copy, or microcopy and want it to
  survive a value test rather than a taste argument.
- You are choosing a narrative structure (hook → tension → guide → plan →
  proof → offer → action, or PAS, AIDA, BAB, FAB, StoryBrand) and need to pick
  one instead of stacking them.
- You are storyboarding sections, deciding order, or deciding what to delete.
- You are art-directing a hero in Field Notes and need to know which doctrine
  rules bind and which devices are forbidden here.
- You are auditing claims, social proof, privacy copy, or "official" language.
- You are budgeting motion, measuring Core Web Vitals, or making the page work
  on a low-end Android phone.
- You are designing the measurement plan or scoring the page against the
  critique rubric before a PR or a founder verdict.

Do **not** use it for: the lesson-page design language (that is
`zivon-frontend-product-skills` plus doctrine §10), catalogue/search
information architecture, pricing page mechanics, backend contracts, or the
content pipeline. This bundle owns the argument and the first screen, not the
whole site.

## Non-negotiables

Each rule exists because of a failure it prevents; the reason is the rule.

1. **One primary action.** Exactly one primary CTA, repeated in the same words.
   A second equally-weighted action is a decision the page declined to make.
2. **One promise, and every section pays it.** The promise is stated in the
   hero; each section carries one claim; every claim has proof somewhere on the
   page. A claim without proof is a debt the reader will collect by leaving.
3. **The value-addition test, applied three times: to every section, every
   element, and every word.** See below. The test has a defined pass condition;
   "it looks nice" is not one.
4. **Speak to one awareness stage.** A page that tries to serve search traffic,
   a friend's referral, and a parent at once serves none of them. Split by URL
   or campaign, not by adding sections.
5. **Honest or absent.** No invented testimonial, no unlabelled founder quote
   posing as a user, no countdown that is not real, no "official", no
   affiliation, no number you cannot source. Fabricated proof is illegal in
   several jurisdictions and corrosive everywhere.
6. **§10 never appears here.** Ruled-line lesson grid, handwritten Caveat body
   text, taped paper cards, the sticky lesson language bar, the voice dock:
   none of these belong on the landing page. They are lesson-page devices, and
   using them is a scope error, not a style choice.
7. **Readable with JavaScript off, audio off, and on a 360 px screen.** The
   page must explain itself before any island loads. A demo that requires JS is
   an enhancement, never the argument.
8. **Nothing autoplays sound, and every sound has a transcript.** Sound that
   starts without a gesture is a broken page on a bus, in a classroom, and in
   a house with a sleeping baby.
9. **One pen annotation.** One blue mark per screen, on the thing worth
   noticing. More than one and the isolation effect that makes it work is gone.
10. **Every number is dated or deleted.** "5,000 students" needs a date and a
    source or it does not go on the page.

## The workflow

### 0. Frame the decision before designing anything

Write four sentences, no more:

- **Who** lands here and how they got here (the traffic, not the persona).
- **What they already believe** when they arrive (their awareness stage).
- **What single action** this page exists to produce.
- **What would have to be true** for them to take it.

If you cannot write the fourth sentence, the page has no argument yet. Stop and
read [references/audience-and-emotion.md](references/audience-and-emotion.md).

### 1. Pick the awareness stage and the honest emotion

Open [references/audience-and-emotion.md](references/audience-and-emotion.md).
Name the stage in one word, name the emotion in one word, and write down what
you are *not* allowed to exploit. The banned list is part of the brief.

### 2. Choose ONE narrative spine

Open [references/narrative-frameworks.md](references/narrative-frameworks.md).
Select a spine, write why the others were rejected in one line each, and stop.
Stacking frameworks is the most common way a landing page becomes unreadable.

### 3. Storyboard the argument, not the layout

Open [references/page-anatomy.md](references/page-anatomy.md) and copy
[templates/storyboard.md](templates/storyboard.md). Each row is:
**section → claim → evidence → objection answered → value test → keep/cut.**
Order the rows so each section answers the objection the previous one raised.
A section that answers no live objection is deleted before layout begins.

### 4. Write the copy deck

Open [references/copywriting-and-microcopy.md](references/copywriting-and-microcopy.md)
and copy [templates/copy-deck.md](templates/copy-deck.md). Produce: one
promise, five headline variants from *different* strategies, the subhead, three
CTA variants, section claims, evidence lines, microcopy for every state, meta
title and description.

### 5. Art-direct against the base doctrine

Open [references/art-direction.md](references/art-direction.md) and
`docs/frontend/design-doctrine.md` §1–§9. The doctrine is the authority; this
bundle interprets it for a landing page and never adds a token. Sketch with
[templates/wireframe.md](templates/wireframe.md) at 360 px *first*, then at
1280 px.

### 6. Prove it before you polish it

Open [references/proof-and-trust.md](references/proof-and-trust.md). Build the
claim ledger: every assertion on the page, its evidence, where the evidence
sits, and who owns it. Any row without evidence is rewritten as a limitation or
deleted.

### 7. Budget motion and performance

Open [references/motion-and-performance.md](references/motion-and-performance.md).
Decide what may move, what must not, and the numbers the page must hit on a
low-end Android before it ships.

### 8. Measure and critique

Open [references/measurement.md](references/measurement.md) for the event set
and decision rules, then [references/critique-rubric.md](references/critique-rubric.md)
and [templates/critique-sheet.md](templates/critique-sheet.md). A page is not
done when it looks finished; it is done when it scores and the numbers move.

## The value-addition test

The base doctrine (§0.1) asks whether removing an element costs the user a
**capability**. A landing page is read, not used, so capability is the wrong
currency. The reader loses one of four things, or the element goes:

| Lose this | Test question | Example that passes |
|---|---|---|
| **A reason to believe** | Remove it: is any claim now unproved? | The screenshot of a real lesson page |
| **A reason to act** | Remove it: is the action now unmotivated or unclear? | The one line saying what happens when you press the button |
| **The ability to act** | Remove it: can the reader no longer do the thing? | The button, the form, the transcript toggle |
| **The answer to a live objection** | Remove it: does a doubt the reader actually holds go unanswered? | "Will this work on my phone?" |

If none of the four applies, delete the element. If two elements do the same
job, keep the one that survives at 360 px with JavaScript off.

Apply it three times: **section** (does this section answer anything?),
**element** (does this card, badge, or icon carry one of the four?), **word**
(does this adjective or clause change what the reader believes?). The third pass
is the one everyone skips and the one that removes the most.

## The argument chain

A landing page is not a list of sections; it is a chain. Each link raises the
next objection and answers it:

```
"What is this?"         -> first screen
"Why is it different?"  -> the mechanism, shown
"Does it actually work?" -> a real artifact, a real voice turn
"Can I trust them?"     -> sources, privacy, honest limits
"Is it for me?"         -> coverage and language, stated plainly
"What does it cost?"    -> the honest price of the action
"What do I do now?"     -> one button, no friction
```

Break the chain and the reader leaves at the break. This is why section order
is an argument decision, not a layout decision.

## Choose one spine, not seven

`HOOK → TENSION → GUIDE → PLAN → PROOF → OFFER → ACTION` is the default for a
cold landing page. The classic frameworks are lenses on single lines, not
alternative page structures: PAS on the hook, AIDA on the page's arc, BAB on
the transformation, FAB on a feature, 4U on a headline, StoryBrand on the
guide/plan relationship. Use one spine; use the others to sharpen sentences
inside it.

The failure mode is the **Frankenpage**: an AIDA hero, a PAS middle, a
StoryBrand plan, and a BAB close, each intact and none connected. It reads like
four pages stapled together and converts like none of them.

## Art direction: base doctrine, never the lesson extension

The brand is **Field Notes §1–§9**: paper-yellow ground, dark ink, graphite
labels, one blue pen annotation, red only for gaps and honest corrections,
Bricolage Grotesque for display and body, Courier Prime for notes and data,
square or 4 px corners, flat surfaces, generous empty space, left alignment.

The landing page is *not* a lesson page. Doctrine §10's ruled 36 px grid,
handwritten Caveat body and headings, taped simulation cards, sticky language
bar, and voice dock are lesson-only devices. A landing page wearing them is
cosplaying the product instead of selling it, and it also reads as broken
because those devices assume a page people study rather than scan.

Operation-level rules (asymmetry, the one annotation, real artifacts, the
360 px composition, the banned list) are in
[references/art-direction.md](references/art-direction.md).

## Anti-patterns and the test that catches each

Do not memorise the names; memorise the tests. Each test is answerable by
looking at the page for thirty seconds.

| Anti-pattern | The test that catches it |
|---|---|
| **SaaS hero** | Swap in a competitor's name. Does 80% of the copy still work? Then it says nothing. |
| **Gradient blobs** | Does any colour on the page not come from doctrine §3? Then the palette is decoration, not a system. |
| **Vague AI claims** | Can a competitor publish the identical sentence without lying? Then it is not a claim. |
| **Fake social proof** | Is every quote attributed to a named, dated, consenting person, or explicitly labelled as the founder's own words? |
| **Feature dump** | For each card: which job does it prove, and where is the evidence? More than five cards is usually a page that has not decided. |
| **Stock photos** | Is this the actual product, an actual artifact, or a person who actually uses it? If not, it is a lie with good lighting. |
| **Lesson-paper cosplay** | Is this device listed in doctrine §10? Then it is forbidden here. |
| **Motion for its own sake** | Remove the motion. Is information lost? If not, the motion was decoration. |
| **Two CTAs** | How many primary buttons are above the fold? More than one means the page has no priority. |
| **Pricing theatre** | Is the scarcity real, dated, and enforced by the system? If not, it is a dark pattern with a countdown. |
| **Testimonial wall** | Do the quotes sound like the same person wrote them? Then they did. |

## Output contract

A landing-page change is complete when the PR contains, in this order:

1. **Brief** ([templates/landing-brief.md](templates/landing-brief.md)) — the
   four framing sentences, awareness stage, emotion, banned appeals.
2. **Storyboard** ([templates/storyboard.md](templates/storyboard.md)) — one
   row per section with claim, evidence, objection, value test.
3. **Copy deck** ([templates/copy-deck.md](templates/copy-deck.md)) — promise,
   five hero variants, section copy, all state microcopy, meta.
4. **Wireframe** ([templates/wireframe.md](templates/wireframe.md)) — 360 px
   and 1280 px, with the annotation and the artifact placed.
5. **Claim ledger** — every claim, its evidence, its location, its owner.
6. **Measurement plan** — the primary action, the event set, the decision rule.
7. **Critique sheet** ([templates/critique-sheet.md](templates/critique-sheet.md))
   — scored, with blockers named.
8. **Evidence** — Lighthouse/field numbers on the weak-Android profile, the
   JS-off screenshot, the reduced-motion check, the 360 px screenshot.

A page with a beautiful hero and no claim ledger is not finished; it is a
mockup.

## Reference map

Read only what the current step needs. Every file below has a load condition.

| Read this | When |
|---|---|
| [references/audience-and-emotion.md](references/audience-and-emotion.md) | Before the brief: naming the awareness stage, the honest emotion, the objections, and what you may not exploit |
| [references/narrative-frameworks.md](references/narrative-frameworks.md) | When choosing the spine, or when a page reads as a list instead of an argument |
| [references/page-anatomy.md](references/page-anatomy.md) | When storyboarding, deciding section order, or deciding what to cut |
| [references/copywriting-and-microcopy.md](references/copywriting-and-microcopy.md) | When writing or reviewing any string, including errors, empty states and CTAs |
| [references/art-direction.md](references/art-direction.md) | Before any visual decision: composition, the one annotation, artifacts, the §10 guard, 360 px |
| [references/proof-and-trust.md](references/proof-and-trust.md) | When a claim, testimonial, number, privacy promise or "official" word appears on the page |
| [references/motion-and-performance.md](references/motion-and-performance.md) | When adding motion, audio, video, a demo island, or measuring Core Web Vitals |
| [references/measurement.md](references/measurement.md) | When defining the conversion event, the funnel, the A/B test, or what counts as a win |
| [references/critique-rubric.md](references/critique-rubric.md) | Before a PR, a review, or a founder verdict — and when two people disagree |
| [references/teardowns.md](references/teardowns.md) | When you need a reference page for a specific move, and to avoid copying a template |
| [references/sources.md](references/sources.md) | Before citing any number from this bundle, or when a source may have changed |

Templates: [brief](templates/landing-brief.md),
[storyboard](templates/storyboard.md), [wireframe](templates/wireframe.md),
[copy deck](templates/copy-deck.md),
[hero variants](templates/hero-variants.md),
[critique sheet](templates/critique-sheet.md).

Worked example: [examples/zivon-landing-brief.md](examples/zivon-landing-brief.md)
— a full Zivon brief, storyboard and hero set, written as a demonstration of the
method and explicitly not as approved copy.

## Gotchas

- **The page's look is judged in 50 ms; its argument is judged in 10 seconds.**
  Aesthetics buy the first glance; the first sentence has to buy the next ten
  seconds. Optimise the two separately and test them separately.
- **"Above the fold" is a moving target, not a pixel value.** Test at 360×640,
  390×844, and 1280×800. If the hero only works on a laptop, it does not work.
- **A real screenshot beats a drawing of a screenshot.** If the product is not
  ready to screenshot, the landing page is early - write the claim ledger first.
- **Founder quotes are not testimonials.** They are allowed and useful; they
  must be labelled as the founder's words, not presented as a user's.
- **Scroll depth is a diagnostic, not a goal.** A page that people scroll to the
  bottom and leave has a conversion problem, not an engagement win.
- **Hindi and Hinglish are not translations of the English page.** Translate
  the promise; a literal translation of an English headline usually reads like
  an advertisement for a different product.
- **The doctrine wins every conflict.** If this bundle and
  `docs/frontend/design-doctrine.md` disagree, the doctrine is right and this
  bundle has a bug.
