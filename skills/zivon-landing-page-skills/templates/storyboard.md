# Storyboard

The argument, before the layout. One row per section. Copy this into the PR and
fill every column; a blank column is a decision not made.

---

## The table

| # | Section | Job (one line) | Claim it makes | Evidence on the page | Objection it answers | Value test (what the reader loses if removed) | Keep / Cut |
|---|---|---|---|---|---|---|---|
| 1 | Top bar | | | | | | |
| 2 | Hero | | | | | | |
| 3 | Live specimen | | | | | | |
| 4 | Mechanism | | | | | | |
| 5 | Proof / sources | | | | | | |
| 6 | Coverage (syllabus strip) | | | | | | |
| 7 | Practice / test series | | | | | | |
| 8 | Privacy | | | | | | |
| 9 | Founder note | | | | | | |
| 10 | FAQ | | | | | | |
| 11 | Final CTA | | | | | | |
| 12 | Footer | | | | | | |

The practice/test-series row is a frozen section. If the brief proposes merging
it into Coverage, keep both rows and record the merge in the brief's "sections
we propose to cut or merge" field; do not delete the row silently.

## The value test

For each row, answer one of these or cut it:

- Removing it leaves a **claim unproved**.
- Removing it leaves the **action unmotivated or unclear**.
- Removing it leaves the reader **unable to act**.
- Removing it leaves a **live objection unanswered**.

"Removing it makes the page less pretty" is not an answer. Neither is "every
landing page has one".

## The chain check

Write the headings in order, joined with a connector. Every pair must work with
**so**, **but**, or **because**.

```
<heading 1>  ->  <heading 2>  ->  <heading 3>  ->  ...
```

```
1 -> 2:
2 -> 3:
3 -> 4:
4 -> 5:
5 -> 6:
6 -> 7:
```

If a pair cannot be joined, the order is wrong or one of the two sections does
not belong.

## The deletion check

For each section, ask: *if this were removed, would the page still argue
coherently?* If yes, cut it. Record the cut and the reason — a cut is a decision
worth keeping.

```
Cut:            <section>
Because:        <what it duplicated / what objection it did not answer>
Moved to:       <another page, or "nowhere">
```

## The one-screen-one-idea check

| Screen | Its single idea, in one sentence | Pass? |
|---|---|---|
| 1 | | |
| 2 | | |
| 3 | | |

A sentence that needs "and" means the screen is doing two jobs.

## Mobile order

The DOM order is the argument order. Record what changes at 360 px and why.

```
Section            Desktop position    360 px position     What changes
Hero
Artifact
Demo
Mechanism
Proof
Coverage
Practice / test series
Privacy
Founder
FAQ
Final CTA
```

Rules: nothing is reordered with CSS `order:`; the transcript stays in the DOM;
the CTA is reachable without scrolling past the artifact.

## Length

```
Sections in the chain:              <n>
Sections cut in this draft:         <n>
Estimated scroll height at 360 px:  <n screens>
Justification for length:           <the number of real objections>
```

A page with more sections than objections has filler. Say which sections answer
which objection, above, and the count takes care of itself.
