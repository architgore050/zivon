# Proof and trust

Every claim on the page is a debt. This file is about paying it, or not making
it.

`[E]` marks a claim backed by a published rule or standard. The regulatory parts
are **not legal advice**; `docs/compliance/` is the repo's authority and
`CQ-##` questions go to counsel.

## 1. The claim ledger

Before layout, list every assertion the page will make. One row each.

| Field | What goes in it |
|---|---|
| **Claim** | the sentence exactly as it will appear |
| **Type** | capability · coverage · quality · safety · price · affiliation |
| **Evidence** | the artifact, source, test, or record that makes it true |
| **Location** | where on the page the evidence sits |
| **Owner** | the person or team who keeps the evidence true |
| **Expires** | the date it must be re-checked (numbers, coverage, prices) |

Rules:

- **A claim with no evidence row is deleted or rewritten as a limitation.**
- **A claim whose evidence is not on the page is not proof.** "See our
  methodology" only counts if the link is above the fold or beside the claim.
- **A claim with no owner is unowned**, and unowned claims rot. The first time a
  number goes stale the whole page becomes suspect.
- **`Expires` is not optional** for coverage, counts, prices and dates.

## 2. Five kinds of proof, strongest first

| Rank | Proof | Why it works | Its failure mode |
|---|---|---|---|
| 1 | **The product itself**, usable on the page | the reader verifies instead of believing | a demo that requires signup, or a fake "interactive" mock |
| 2 | **A real artifact** — screenshot, transcript, generated page, citation | undeniable and specific | a mockup presented as real |
| 3 | **A named source** — NCERT chapter, review gate, dated study | checkable by the reader | a citation the reader cannot follow |
| 4 | **A dated number** with its definition | specific and falsifiable | an undated count that was true once |
| 5 | **A person** — a named user with consent, or the founder in their own voice | human trust transfer | an unlabelled founder quote posing as a user |

Anything below rank 5 is decoration: logo walls, star ratings with no source,
"trusted by thousands", award badges nobody can verify, security seals that are
images.

**Rank 1 beats everything.** A page that lets the reader *do* the thing has less
to prove than any page that talks about it. This is why the frozen spec puts a
real 20-second voice turn and a live mini-simulation on the landing page: they
are the argument, not the illustration.

## 3. Testimonials and reviews

The rules here are legal, not stylistic.

- **Fake reviews and testimonials are prohibited.** The FTC's Rule on the Use of
  Consumer Reviews and Testimonials (16 CFR Part 465) took effect 21 October
  2024 and treats writing, buying, or disseminating a testimonial that
  misrepresents that a reviewer exists, used the product, or had the experience
  as an unfair or deceptive practice `[E]`.
- **Endorsements must reflect honest experience.** The revised Endorsement Guides
  (16 CFR Part 255, 2023) require that endorsements reflect the endorser's honest
  opinion and that material connections be disclosed clearly and conspicuously
  `[E]`.
- **Insider reviews need disclosure.** An officer, manager, or employee
  testimonial must disclose the relationship, unless the relationship is already
  clear to the audience `[E]`.

Zivon's operating rule, stricter than the minimum:

| Situation | Allowed? | How |
|---|---|---|
| A real student, named, with written guardian consent, quote verbatim | yes | name, class, date, and a link to the consent record |
| A real student, anonymised ("Class 10, Pune") | yes, with caution | label it as anonymised; do not imply the quote is representative |
| A teacher or parent | yes | state the relationship |
| The founder, in their own voice | yes | label it "the founder", never place it among user quotes |
| A model-written quote | **never** | it is a fabrication with a friendly face |
| A quote from a pilot user who used a different version | only with the version and date | otherwise it overstates the current product |
| A logo of a school or company that trialled it | only with written permission and a date | a logo implies endorsement |
| "10,000 students" | only with a dated count and a definition | who counts, since when, measured how |

**The tell.** Read the quote wall aloud. If every quote has the same rhythm,
length, and enthusiasm, one person wrote them. A reader notices this faster than
you think, and the cost is the whole page.

## 4. "Official", affiliation, and authority

Words that imply an institution are claims about a relationship. They are the
easiest to get wrong and among the most damaging.

- **Never claim CBSE affiliation, endorsement, or "official" status.** Zivon is
  not affiliated with CBSE. Generated items never claim official affiliation.
  This is a repo-level rule (`AGENTS.md`, `docs/compliance/`), not a preference.
- **NCERT material is attributed.** NCERT is officially free to use, and the page
  cites the chapter and the source. "Based on NCERT" is a claim about sourcing;
  keep it factual and link the source register.
- **Exam-content statements follow `docs/compliance/`**, including the
  non-affiliation notice copy (`N-01`…`N-05` in `docs/compliance/notices.md`).
  Do not paraphrase those notices on a landing page; link them.
- **No borrowed authority.** "IIT-designed", "recommended by teachers",
  "research-backed" — each is a claim that needs a name, a date, and a document.
  If it has none, delete it. This is also an endorsement-guides issue: an
  expert endorsement must reflect a real expert's real opinion `[E]`.
- **"AI" is not authority.** It is a category. Saying a model is "frontier" or
  "reasoning" describes the vendor, not the reader's outcome.

## 5. Numbers

A number is the strongest small proof and the easiest thing to fake.

Every number on the page needs four things:

1. **A definition** — 10,000 what? Sessions, students, chapters, turns?
2. **A date** — as of when?
3. **A source** — measured where, by what?
4. **A stability** — is it still true next month? If not, who re-checks it?

| Says | Fails because |
|---|---|
| "Trusted by 10,000+ students" | no date, no definition, no source |
| "Used in 40 schools" | which schools? with permission? |
| "98% improve" | improve what, measured how, compared to what |
| "3× faster" | faster than what, on which task |
| "Class 9–12 covered" | if Class 11–12 are not live, this is false |
| "12 chapters live, updated 2026-11-16" | passes: defined, dated, checkable |

**Coverage is the number most likely to be wrong.** State what is live, what is
in progress, and when the next batch lands. A reader who discovers the gap at
the first click stops believing everything else — including the true parts.

## 6. Privacy and child safety

This is the section parents read, and the one that is easiest to make worthless
with reassurance.

- **Be specific or be silent.** "Your audio is transcribed and discarded; the
  transcript stays on this device unless you sign in" is proof. "We take your
  privacy seriously" is a promise the reader cannot verify.
- **Name the processor.** If a vendor transcribes the speech, say so. Naming
  Gnani on the privacy page is honest and is also a compliance requirement in
  spirit: the reader is told who processes their child's voice.
- **No raw audio retention by default.** Say it, and make sure the code agrees.
- **No parent access, no ads, no sale of data.** If those are true, they are
  strong differentiators; say them plainly.
- **Deletion is a path, not a policy sentence.** "Delete your data from settings
  in one step" beats "you may request deletion".
- **Children's data is an architecture constraint**, not a copy decision: private
  by default, minimised, no profiling beyond what the product needs. Claims that
  exceed the architecture are false claims, and the fix is the code, not the
  sentence.
- **Consent is device-local and reversible**; the landing page must not imply
  otherwise.

See `docs/backend/` for the data classification and retention rules this copy
has to match, and `docs/compliance/` for the exact notice wording.

## 7. Honest limitations are proof

A page that admits one true limitation buys credibility for everything else.

Examples of limitations that *increase* trust:

- "Class 11 and 12 are being written. Class 9 and 10 are live."
- "Voice works in English, Hindi and Hinglish. Other languages are not
  supported yet."
- "The tutor explains; it will not do your homework for you."
- "Audio is processed by a third party; the recording is not kept."
- "This is a prototype. Things will break, and the log says so."

Examples that *destroy* trust, because they are limitations in disguise:

- "Best experienced on a modern smartphone." (you did not optimise)
- "Results may vary." (you are not claiming anything)
- "Currently in beta" as a shield for defects with no fix path.

**Rule:** a limitation must be specific, true, and paired with what happens
instead. "Class 11–12: not yet. Get told when they land →" is honest and useful.

## 8. The proof audit

Run this before the page ships, and again whenever a claim changes.

1. Read every sentence on the page that asserts something. Highlight it.
2. For each highlight, find its ledger row. Missing row → the claim goes.
3. For each row, open the evidence. Is it on the page, or reachable in one
   click? If not, move it or downgrade the claim.
4. Check every number for definition, date, source, stability.
5. Check every person for name, consent, relationship, date.
6. Check every institutional word ("official", "affiliated", "certified",
   "recommended") for a document.
7. Check every privacy sentence against the actual behaviour in the code.
8. Re-read the page as a sceptical parent. Which sentence would you challenge
   first? That is the one to strengthen or cut.

## 9. When something turns out to be false

- **Fix the page first, then the record.** A wrong claim on a live page is a
  live harm.
- **Correct in public if it was public.** A dated correction note beats a silent
  edit when the claim was load-bearing.
- **Remove the source from the ledger** and note why, so the same claim is not
  reintroduced by the next person.
- **Check whether the same claim appears elsewhere** — the footer, the meta
  description, an OG card, a post. Copy propagates; corrections must too.
