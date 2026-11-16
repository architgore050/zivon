# Page anatomy

What each section is for, what order they go in, and when a section should not
exist. The frozen product spec (`tmp/full-frontend/REQUIREMENTS.md` §10.1,
PUB-01 in `FEATURE-MAP.md`) lists the landing page's contents. This file does not
change that list; it decides **what each item has to accomplish** and **what
deletes it**.

## 1. The first screen

The first screen is the ad. It has four jobs, in this order of visual weight:

1. **What it is** — a headline a stranger can repeat.
2. **Who it is for** — class, subject, language, in a subordinate line.
3. **Why it is different** — one mechanism, not a list.
4. **What to do** — one primary action.

Everything else on the first screen is competing with those four.

| Must be above the fold | May be above the fold | Must not be above the fold |
|---|---|---|
| H1, one-line subhead, primary CTA, one artifact or one proof | a secondary text link, language sample, a one-line honesty note ("free to start") | a cookie wall, a video that must play, a carousel, three CTAs, a newsletter modal |

**The artifact rule.** The first screen contains either a real product artifact
(a lesson page, a simulation, a transcript of a real voice turn) or a proof (a
named source, a real number). A hero with neither is a poster.

Why this is not negotiable: visitors spend the overwhelming share of their
attention above the fold, and the drop at the fold is large — roughly 57% of
viewing time above it in the 2018 eyetracking study, against 80% in 2010 `[E]`.
The fold softened; it did not disappear. Everything you put below it is read
only by people the first screen convinced.

**The 10-second contract.** A stranger who reads for ten seconds must be able to
say the promise and the next action `[E]`. If they can only say "it's about
learning", the hero is describing a category, not a product.

## 2. The argument chain

Sections are objections in sequence. Order them so each answers what the
previous one raised.

```
screen 1   "What is this?"              -> hero
screen 2   "Does it actually work?"     -> live specimen / demo
screen 3   "How does it do that?"       -> mechanism
screen 4   "Can I trust it?"            -> sources, review, honest limits
screen 5   "Is it for my class?"        -> coverage
screen 6   "Is it safe?"                -> privacy and child safety
screen 7   "Who made it, and why?"      -> founder / build-in-public note
screen 8   "I still have a doubt"       -> objections / FAQ
screen 9   "What do I do?"              -> final CTA
```

A section that answers nothing in this chain is furniture. Delete it before
layout, not after.

## 3. Section catalogue

Each row is the contract for that section: the job it does, the claim it must
carry, the evidence it needs, and the condition that removes it.

### 3.1 Top bar

- **Job:** orientation, not navigation theatre.
- **Carries:** wordmark, three or four real destinations, one sign-in link, one
  primary action.
- **Value test:** does removing any link cost the reader the ability to act or
  navigate? A link to a page that does not exist yet fails the test.
- **Omit when:** never — but it can be one line on mobile.
- **Failure mode:** a mega-menu on a page with one job; a "Pricing" link to a
  page that is a waitlist.

### 3.2 Hero

- **Job:** the ad. See §1.
- **Carries:** H1, subhead, primary CTA, artifact, optional one-line honesty
  note.
- **Value test:** remove the headline. Is there still a promise? Then the
  headline was decoration.
- **Omit when:** never.
- **Failure mode:** centred stack of headline + gradient + two buttons; a
  rotating headline; a headline that names the category ("The future of
  learning").

### 3.3 Live specimen / demo

- **Job:** replace the claim "it works" with the experience "here it is".
- **Carries:** a real 20-second voice turn (or a real excerpt) with transcript,
  a play control, and the page it is anchored to. If audio is not available,
  the transcript plus a mini-simulation still counts as a specimen.
- **Value test:** remove it. Is "it works" now unproved? If not, the demo was
  ornamental.
- **Omit when:** the only available recording is synthetic or acted. A fake
  demo is worse than no demo.
- **Failure mode:** autoplay; a video with no transcript; a demo that requires
  a signup; a "coming soon" play button.

Accessibility contract: no autoplay, a visible transcript, captions where there
is video, and a control that works by keyboard (WCAG 2.2 SC 1.2.1 and 1.2.2
`[E]`).

### 3.4 Mechanism / how it works

- **Job:** explain why this is different, in a way a competitor cannot copy.
- **Carries:** three to five steps that are *mechanisms*, not features:
  "it reads the page you are on and anchors the answer to that paragraph".
- **Value test:** swap in a competitor's name. Does the section still make
  sense? Then it describes the category.
- **Omit when:** the product's difference is genuinely visible in the specimen.
  A demo can replace the explanation.
- **Failure mode:** a five-step "Read → Learn → Succeed" list that describes
  every product in the category.

### 3.5 Proof

- **Job:** pay the claims made above.
- **Carries:** real artifacts, cited sources, review gates, dated numbers.
- **Value test:** remove a proof item. Does a specific claim become unsupported?
  If not, it was decoration.
- **Omit when:** never — but it can be small and quiet.
- **Failure mode:** a logo wall; five-star ratings with no source; "trusted by
  10,000+ students" with no date.

Full rules in [proof-and-trust.md](proof-and-trust.md).

### 3.6 Coverage

- **Job:** answer "is my class / chapter / language here?"
- **Carries:** classes, chapters, languages, and **what is not ready yet**.
- **Value test:** does the reader learn whether they are in the right place?
- **Omit when:** coverage is the entire product and the catalogue page already
  says it better — then link, do not duplicate.
- **Failure mode:** implying full coverage when only Class 9–10 is live. The
  reader finds out at the first click, and the whole page becomes suspect.

### 3.7 Privacy and child safety

- **Job:** answer the parent's and the student's real question: what is kept,
  who sees it, how it is deleted.
- **Carries:** specifics — audio not retained, transcript handling, no parent
  access, no ads, deletion path, the processing vendor named.
- **Value test:** could a sceptical parent act on this? Vague reassurance fails.
- **Omit when:** never for a product used by minors.
- **Failure mode:** "We value your privacy" with no facts; a shield icon.

### 3.8 Founder / build-in-public note

- **Job:** answer "who made this and why should I believe them?"
- **Carries:** one short paragraph, a real name, a link to the log, and one
  honest limitation.
- **Value test:** does it add a reason to trust that the rest of the page cannot
  supply? If it is only biography, move it to `/about`.
- **Omit when:** the page is a campaign page for warm traffic that already knows
  the maker.
- **Failure mode:** a founding myth; a photo of a whiteboard; "we're passionate
  about education".

### 3.9 Objections / FAQ

- **Job:** remove the last specific doubts.
- **Carries:** four to eight questions in the reader's words, each answered in
  one or two sentences with a fact.
- **Value test:** is this a question the reader actually holds? If it is a
  question the company wishes they held, delete it.
- **Omit when:** the objections are already answered inline, and repeating them
  adds length without removing doubt.
- **Failure mode:** "Is Zivon safe? Yes, absolutely!" — an answer with no
  information.

### 3.10 Final CTA

- **Job:** the same action, restated once, at the point of maximum belief.
- **Carries:** the same words as the primary CTA, plus what happens next.
- **Value test:** can the reader act without scrolling up? If yes, it earns its
  place.
- **Omit when:** the page is short enough that the first CTA is still on screen.
- **Failure mode:** a different action from the hero's.

### 3.11 Footer

- **Job:** legal, trust, and navigation to the non-marketing pages.
- **Carries:** privacy, terms, child safety, contact, status, sources,
  non-affiliation notice, language.
- **Value test:** can a reader verify a claim or exercise a right from here?
- **Omit when:** never.
- **Failure mode:** a sitemap of thirty links and no legal or contact
  information.

## 4. Order rules

These are constraints, not preferences. Each one exists because reversing it
creates a specific failure.

1. **Nothing may precede the answer to "what is this?"** A story, a statistic, or
   a manifesto before the product is named loses the reader who arrived from
   search.
2. **Proof may not precede the claim it proves.** Evidence for an unstated claim
   reads as noise.
3. **Price and cost may not be the last thing.** A reader who reaches the CTA and
   only then learns the cost feels tricked, even when the price is fair.
4. **The founder note may not appear before the product is explained.** It
   answers a question the reader does not have yet.
5. **The FAQ may not contain the primary objection.** If "is it free?" is only in
   the FAQ, it is buried.
6. **A second CTA may not sit beside the first.** Two equal buttons mean the page
   has no priority.

## 5. How long should the page be?

Long enough to close the argument, short enough to be read. The measurable
version:

- Every section has a named objection. Count them. That is the minimum.
- Any section whose removal leaves the argument intact is deleted.
- A page that needs more than about nine sections is usually two pages: the hook
  and the deep proof. Split, or move the deep proof to `/method`.

Length is a consequence of the number of real objections, not a target. A page
with three real objections and nine sections has six sections of filler.

## 6. Mobile order

Mobile is the default, not the adaptation. At 360 px:

| Section | Treatment |
|---|---|
| Top bar | wordmark + one action; navigation in a disclosure |
| Hero | headline, subhead, CTA, artifact — in that order, full width |
| Artifact | first, if the headline depends on it; otherwise immediately after the CTA |
| Demo | play control first, transcript collapsed but present in the DOM |
| Mechanism | one column; steps as a numbered list, not cards |
| Proof | one column; the strongest item first |
| Coverage | a table that wraps, or a list — never a horizontally scrolling grid |
| Privacy | short, factual, above the FAQ |
| Founder note | after privacy, before the FAQ |
| FAQ | `<details>` elements; the answers present without JS |
| Final CTA | full width, 44 px minimum height |

Never reorder by `order:` in CSS to fix a semantic order. Write the DOM in the
argument order and let the layout follow.

## 7. The one-screen-one-idea check

Cover everything except one screen. Can you state that screen's single idea in
one sentence? If the sentence needs "and", the screen is doing two jobs. Split
it or cut one.

Apply this to the hero first, because it is the screen where the failure is most
expensive.
