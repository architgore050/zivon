# Worked example: the Zivon landing page

A complete brief, storyboard and hero set produced with this bundle. It is a
**demonstration of the method**, not approved copy, not a spec, and not a
promise that any of these sentences ship. The founder gives the visual verdict
and the final copy call; the frozen product spec
(`tmp/full-frontend/REQUIREMENTS.md` §10.1, `FEATURE-MAP.md` PUB-01) fixes the
required sections.

Read `SKILL.md` and `references/page-anatomy.md` first. This file shows what
their output looks like.

---

## 1. Brief

```
Page:            /
Author:          landing-page skill (demonstration)
Date:            2026-11-16
Frozen spec:     REQUIREMENTS.md §10.1, PUB-01
Doctrine:        design-doctrine.md §1-§9 (§10 excluded)
```

### The four framing sentences

- **Who lands here, and how:** a Class 9 or 10 student, on a phone, in the
  evening, who got the link from a classmate who said "this one explains it
  properly" — or from a build-in-public post by the person who made it.
- **What they believe on arrival:** "There are a hundred apps that claim to
  teach me Physics. Most of them are videos, or a chatbot with a textbook
  stapled on. I'll give this thirty seconds."
- **The one action:** open a chapter and start reading, with no account.
- **What would have to be true:** the page must show, in the first screen, that
  this is a *page that answers*, not another video library — and that trying it
  costs nothing and needs no signup.

### Reader

```
Reader:                 Class 10 student, one link, one phone, low-end Android
Awareness:              solution-aware (knows tutoring apps exist; does not know us)
Honest emotion:         relief
Must not exploit:       fear of board exams; parental disappointment
Languages on this page: EN, हिन्दी, Hinglish (a real sample, not a badge)
Device:                 360 px, shared connection, possibly someone else's data
```

### Why not "search traffic"

Search traffic mostly lands on chapter pages (PUB-04), not on `/`. A student
searching "refraction class 10 numericals" wants the answer, and sending them to
a pitch would be a worse page for them and a worse bounce for us. The landing
page's job is the reader who has *heard of it* and needs to be convinced; the
chapter page's job is the reader who needs *this concept now*. Two pages, two
arguments — this is the split-by-URL rule from `audience-and-emotion.md`.

### The promise

> **Ask the page. Out loud. In the language you think in.**

Substitution test: put a competitor's name in it — it becomes false, because
they do not read the page you are on and they do not answer in Hinglish.
Pass.

## 2. Five hero variants

| # | Strategy | Headline | Proof line it needs |
|---|---|---|---|
| A | Mechanism | **Ask the page. Out loud. In Hinglish.** | a real 20 s turn, transcribed, with the anchor chip visible |
| B | Tension | **You read it. You nodded. You still can't do the numerical.** | the worked step, on screen, beside the same paragraph |
| C | Objection | **Not a chatbot with a textbook stapled on.** | the review gates + the citations on a real page |
| D | Outcome | **See why the ray bends, not just that it does.** | the mini-simulation, moving under a slider |
| E | Artifact | **Class 10 · Light. Ask it anything about this paragraph.** | a screenshot at 360 px with the highlight on the paragraph |

**Chosen for the first build: A.** It carries the mechanism (the page answers),
the modality (out loud), and the differentiator (Hinglish) in eight words, and
its proof line is the one artifact we already have to build anyway: the demo.

**Challenger: B.** It is the same promise sold through the reader's memory of
the failure, which is a different argument and a fair test. It risks sounding
negative for a 16-year-old at 11 pm, which is exactly what the test is for.

D is the safest and the weakest differentiator — every simulation product can say
it. E is the strongest if the artifact is good, and the weakest if it is not.

### Subhead (for A)

> Interactive NCERT Physics pages for Class 9–10, with a voice tutor that reads
> the page you are on. Free to start, no account.

Qualifies (Class 9–10, NCERT Physics), specifies (voice, anchored to the page),
de-risks (free, no account). Three jobs, two sentences.

### CTA

```
Primary:    Open a chapter
After:      the Class 9–10 catalogue, with what is live marked
Beside:     "no account" in the subhead, not a badge
Secondary:  none above the fold
Final CTA:  Open a chapter   (identical)
```

## 3. Storyboard

| # | Section | Claim | Evidence | Objection answered | Value test | Keep |
|---|---|---|---|---|---|---|
| 1 | Top bar | — | — | "where am I?" | navigation + the action | keep |
| 2 | Hero | Ask the page, out loud, in the language you think in | — | "what is this, and why would I?" | loses the promise | keep |
| 3 | Live specimen | It really answers, anchored to the paragraph | 20 s Hinglish turn + transcript + anchor chip | "does it actually work?" | "it works" becomes unproved | keep |
| 4 | Mechanism | Reads your page, answers in your language, shows the physics | a real page with the highlight, the sim, and the check | "is this just a chatbot?" | the differentiator becomes a claim | keep |
| 5 | Proof and sources | Every page is built from cited NCERT material and reviewed | a citation block, the review-gate summary, one honest limitation | "can I trust what it teaches?" | trust becomes assertion | keep |
| 6 | Coverage | Class 9–10 live; Class 11–12 in progress; EN/हिं/Hinglish | the chapter count, dated, with what is missing | "is my class here?" | false coverage is the fastest way to lose trust | keep, merged |
| 7 | Privacy | Audio is transcribed and discarded; no parent access; no ads | specific facts, the processor named | "is my voice recorded?" | a parent cannot act on it | keep |
| 8 | Founder note | One person is building this in public; here is the log | a real name + the log link + one limitation | "who made this?" | no reason to trust beyond the page | keep |
| 9 | FAQ | Six real doubts, answered with facts | each answer cites a behaviour, a cost or a limit | the residual doubts | the last objections go unanswered | keep |
| 10 | Final CTA | Same action, at maximum belief | — | "what do I do now?" | the reader must scroll up | keep |
| 11 | Footer | Legal, sources, contact, non-affiliation | links | "how do I verify or complain?" | rights become unreachable | keep |

### One proposed change, flagged not taken

The frozen spec lists the syllabus strip and the practice/test-series block as
separate sections. In this storyboard they merge into **Coverage** (6), because
at this stage they answer the same objection ("is my class here, and is there
something to do?") and two adjacent sections would each be thinner.

That is a change to a frozen list, so it is **proposed here and decided by the
founder**, not made silently. If it is rejected, both sections return and the
argument chain gets one more link.

### The heading read

> Open a chapter · Ask the page, out loud · It answers where you are reading ·
> Every page is built from a cited source · Class 9–10 today, 11–12 next ·
> What happens to your voice · Who is building this · Still have a doubt? ·
> Start with one chapter

Read top to bottom, that is the argument. It passes the heading test.

### The chain

| Pair | Connector | Works? |
|---|---|---|
| hero → specimen | "so here it is" | yes |
| specimen → mechanism | "but how" | yes |
| mechanism → proof | "because it is built from sources" | yes |
| proof → coverage | "so which chapters" | yes |
| coverage → privacy | "and your voice" | yes |
| privacy → founder | "and who says so" | yes |
| founder → FAQ | "but I still wonder" | yes |
| FAQ → CTA | "so start" | yes |

## 4. Claim ledger (excerpt)

| # | Claim | Evidence | Location | Owner | Expires |
|---|---|---|---|---|---|
| C1 | "Ask out loud, in Hinglish" | a real 20 s clip of a real doubt, transcribed | §3 hero proof line + §3 demo | voice | on any pipeline change |
| C2 | "Reads the page you are on" | the anchor chip visible in the screenshot and in the clip | §3 + §4 | frontend | on any shell change |
| C3 | "Class 9–10 live" | the catalogue count, dated | §6 | content | monthly |
| C4 | "Built from cited NCERT material" | the citation block on every page, linked | §5 | content | on any source change |
| C5 | "Audio is discarded" | the retention behaviour in the voice backend | §7 | backend | on any retention change |
| C6 | "No account to start" | the actual gate | §2 + §10 | product | on any auth change |

Every row has an owner and an expiry. A row without one is deleted before
launch.

## 5. What this page refuses

- **Fear of boards.** The exam is weeks away and the fear is already there. The
  page does not mention the exam to sell anything.
- **Parental disappointment.** No "make your parents proud", no comparison to
  cousins, no "your friends are ahead".
- **Shame.** No ranking, no streak, no "you're behind".
- **Fake urgency.** No countdown, no "seats", no "closing tonight".
- **Invented proof.** No testimonial until there is a real student, named, with
  guardian consent, and a date.
- **Borrowed authority.** No "IIT", no "official CBSE", no "teacher-approved".
  The NCERT citation is a sourcing fact, not an endorsement.
- **The category word.** "AI" does not appear in the hero. It is the category,
  not the promise, and it triggers the wrapper objection before the page has
  earned a hearing.

The one we were tempted by: **"Stop memorising. Start understanding."** It is
good copy and it is a reproach — it tells the reader that what they have been
doing is stupid. Cut.

## 6. Art direction

- **Hero:** asymmetric, type column left, artifact right; on mobile the headline,
  the subhead, the artifact, then the CTA.
- **Artifact:** a real Class 10 · Light page at 360 px, taped at two corners,
  2 px hard offset, with the anchor chip visible. Owner: frontend, re-captured
  on any shell change.
- **One pen annotation:** a pen-blue circle around the highlighted paragraph in
  the artifact — the thing the headline claims ("the page you are on"). Generated
  by the doctrine's §4.1 algorithm, not CSS.
- **Type:** the §3 derivation in `art-direction.md`; Bricolage for the headline,
  Courier Prime for the "20 s · Hinglish · transcript" data line.
- **No §10 anywhere:** no ruled grid, no Caveat, no taped simulation card as a UI
  element, no language bar, no voice dock. The tape on the screenshot is §6's
  proof device, not §10's card affordance.
- **Palette:** §3 only. No gradient, no blob, no stock photo, no 3D render, no
  glowing brain.

## 7. Measurement

```
Primary action:      chapter_open
Denominator:         landing_view, unique session
Window:              28 days
Baseline:            first measurement
Target:              defined after four weeks of baseline
Diagnostics:         demo_play rate, demo completion, scroll to §6, faq_open top 3
Qualitative:         five-second test n=5 (before launch), sceptic read n=2
Variant plan:        A vs B, one variable (headline strategy), pre-registered rule
Privacy:             consent-gated, no free text, no ad pixels
Review date:         four weeks after launch, read by the page owner
```

The decision rule, written before launch: *B ships if `chapter_open` rises by
15% relative with no regression in demo completion or the five-second test.*

## 8. Open questions for the founder

1. **Does the 20-second Hinglish clip exist, with a real student's voice and a
   real doubt?** The whole page leans on it. If it does not exist yet, the hero
   changes to variant D and the demo becomes "coming soon" — which fails the
   proof rule, so the honest alternative is to ship the page when the clip
   exists.
2. **Is the practice/test block merged into Coverage, or kept separate?** It is
   a change to the frozen section list.
3. **Does the parent-facing content live on this page or on `/for-parents`?** The
   brief assumes a linked page, with one labelled line on the landing page.
4. **Which chapter is the default deep link from "Open a chapter"?** It should be
   the strongest live page, not the first in the catalogue.

## 9. What this example is not

- Not approved copy. Every headline here is a draft for a decision.
- Not a visual design. It describes composition; the doctrine and the founder's
  verdict decide the pixels.
- Not evidence that any of it converts. Everything in §7 is a hypothesis with a
  test attached, and the test is the point.
