# CBSE past and sample paper reuse — compliance memo and decision

**Status:** decision memo for the Zivon exam-prep build (FEATURE-MAP SER-01/SER-06,
CNT-05; handshake Q-8). **Not legal advice.** Written by the C0 compliance
research agent on 2026-11-15 against `main` @ `e2977bc`. Every load-bearing claim
carries a confidence tag and a source id from [`sources.md`](sources.md).

**Decisions:** [`decision-log.md`](decision-log.md) (`DEC-COMP-001` … `008`).
**User-facing copy:** [`notices.md`](notices.md) (`N-01` … `N-05`).
**Counsel questions:** [`CQ-01` … `CQ-10`](decision-log.md#counsel-questions).

---

## 0. Bottom line — the five questions, answered

| # | Question | Answer | Confidence |
|---|---|---|---|
| 1 | May Zivon reproduce CBSE past papers, official sample papers and marking schemes **verbatim**? | **Not on the current record.** Question papers are copyrightable literary works, commercial republication of board papers has been enjoined in India, and no statutory education exception covers a paid platform distributing them at scale. The one permission-like statement — CBSE's Website Copyright Policy — is ambiguous in scope, sits on a different subdomain from the sample papers, and is undercut by CBSE's own history of licensing past-paper rights. Verbatim publishing needs **written permission from CBSE or a written counsel opinion**, recorded before the first item ships. | [MODERATE] |
| 2 | If verbatim is allowed, what conditions apply? | Exact reproduction (no edits, no re-translation), prominent source acknowledgement with year/paper/set/question, a clear non-affiliation notice, no third-party material, no logo or "official/approved" claim, a source URL and retrieval date per item, and a published takedown path. Draft copy: `N-01` … `N-05`. | [MODERATE] |
| 3 | If verbatim is not allowed, what is the fallback? | **Blueprint-only.** Keep official PDFs and extracted pattern metadata internally; generate **new** questions from structured pattern data (marks, section, type, chapter weightage, difficulty, command word) with the source text withheld from the generator; run a deterministic near-duplicate gate; publish under exam-pattern copy that never says "previous year question". | [STRONG] as an engineering control |
| 4 | What must P3 implement? | Two content modes behind one flag, per-item `source_type` + `source_ref`, a publish gate that blocks verbatim without a clearance record, a similarity gate for generated items, an admin status view, a takedown path, and locked public copy. Contract in §7. | — |
| 5 | Founder's desired outcome: direct past questions with a small legal notice? | **Not today, and a notice cannot make it lawful** — a notice is evidence of good faith, not a licence. The path to yes is a one-page permission request to CBSE (`Appendix A`) or a counsel opinion recorded in the decision log. Until then the product ships high-quality replicas, and the verbatim pipeline is built but dark. | [STRONG] on "a notice is not a licence" |

**What this changes in the product:** the exact-PYQ series cannot launch on
verbatim CBSE questions in R1. It can launch as an exam-pattern series now, and
switch to verbatim items the day a clearance record exists — no rebuild, because
P3 builds both paths.

---

## 1. Scope, method and limits

**In scope:** CBSE Class 10 Science (Physics section) and Class 12 Physics (042)
question papers, official sample question papers (SQPs), and marking schemes;
English and Hindi; the R1 five-year window (2022–2026 for past papers,
2014–2026 for SQPs).

**Out of scope (separate decisions):** ICSE/ISC and state-board papers; CBSE
competency item banks built with third parties (British Council, AlphaPlus,
ACER, Sri Aurobindo Society — treated as third-party material, see F-13);
NCERT textbook text (already governed by `sources/catalog.json` and AGENTS.md);
third-party "PYQ" websites (never a source).

**Method.** Primary sources first: the Act (S-01/S-02, dated via S-20), four
Indian judgments (S-14 … S-18), CBSE's published policies and archives (S-03 …
S-13, S-19), and the artefacts themselves (S-06, S-08, S-09). Secondary
commentary (X-01 … X-03) was used to find cases, never as the sole basis for a
finding. Retrieval method,
status, byte sizes and hashes are in [`sources.md`](sources.md); the TLS and
India Code caveats are recorded there rather than smoothed over.

**Limits.** This is desk research by a non-lawyer. It does not review CBSE's
paper-setter contracts, does not know whether CBSE holds assignments for every
year, and cannot predict how a court would treat a notice-and-attribution
commercial product. Those are `CQ-01` … `CQ-10`.

---

## 2. Does copyright subsist, and who owns it?

**F-01 — Question papers are original literary works.** Copyright subsists in
"original literary … works" (s. 13(1)(a)); "literary work" includes tables and
compilations (s. 2(o)). The Supreme Court held that question papers, model
answers and evaluation instructions are literary works and "subject to a
copyright" (*ICAI v. Shaunak H. Satya*, S-14). The Allahabad High Court held the
same for examination papers and explained that "original" means originating from
the author, not literary merit (*Agarwala*, S-15). **[STRONG]**

**F-02 — A whole paper is a compilation; individual questions are short works.**
Each question is a small literary work; the selection and arrangement is a
compilation. Infringement can attach to either a substantial part of a question
or to the compilation as a whole (s. 14: "the work or any substantial part
thereof"). **[STRONG]** The practical consequence — whether copying 30 short
numericals is one infringement or thirty — is `CQ-03`.

**F-03 — Copyright is not lost by public release.** CBSE publishes past papers
and marking schemes on `cbse.gov.in` (S-04, S-05) and sample papers on
`cbseacademic.nic.in` (S-07). Public availability is not a dedication to the
public domain. The Act grants no such formality. **[STRONG]**

**F-04 — The papers are not a "Government work" on the plain text, and even if
they were, they are still in copyright.** Section 2(k) defines a Government work
as one "made or published by or under the direction or control of" the
Government, a Legislature, or a court. CBSE describes itself as "an autonomous
organisation under the Ministry of Education" (S-10 letterhead), not a Government
department. *Agarwala* refused to treat a board's papers as Government works
because the board did not direct or control how paper-setters worked (S-15).
Section 17(dd) separately makes a public undertaking the first owner of a work
"made or first published by or under the direction or control of" it, and the
Delhi High Court accepted both that CBSE is a public undertaking for this purpose
and that its papers are set under its "direction or control" (S-16). Either
classification keeps the 2022–2026 papers protected for decades (60 years from
publication under s. 28A, or the author's life plus 60 under s. 22).
**[STRONG] on "still in copyright"; [MODERATE] on the classification**

**F-05 — Assume CBSE owns or controls the rights.** In *Rupendra Kashyap* the
Delhi High Court accepted CBSE's evidence that paper-setters' rights vest in the
Board, held CBSE to be the first owner, and restrained a commercial publisher
from reprinting CBSE papers from 1990 onwards (S-16). *Agarwala* shows the
opposite result is possible where no assignment is proved (S-15), so ownership
is contract-dependent in principle. For product risk, the only safe assumption
is that **CBSE owns or exclusively licenses the papers**, because that is the
position CBSE will assert. **[MODERATE]**

---

## 3. Does any statutory exception cover republishing?

**F-06 — Fair dealing does not cover a publisher selling copies.** Section
52(1)(a) permits fair dealing for "private or personal use, including research",
criticism or review, and reporting current events. In *Rupendra Kashyap* the
court rejected the defence in terms that fit Zivon exactly: the defence protects
"the person conducting research or private study", not "a publisher [who]
publishes a book for commercial exploitation", even if students ultimately use
it (S-16). *Blackwood v. Parasuraman* reached the same result for commercial
guides (cited in X-02). **[STRONG]**

**F-07 — The education clause is narrower than it looks.** Section 52(1)(i)
covers reproduction "(i) by a teacher or a pupil in the course of instruction;
(ii) as part of the question to be answered in an examination; or (iii) in
answers to such questions". The Delhi High Court read clause (i) purposively for
a university's course packs, but grounded the reading in the teacher–pupil
relationship and drew the line at **profit**: "a publication would have the
element of profit, which would be missing in the case of reproduction of a work
by a teacher" (S-18). A subscription platform is not a teacher reproducing for
their own class. **[STRONG]** Clause (ii) is the only textual hook for a mock
exam, and it is a weak one: its evident purpose is to let an examiner quote a
passage inside a question, not to license a board's paper as the exam — `CQ-04`,
tagged **[WEAK]**.

**F-08 — The "short passages in a collection" clause does not fit.** Section
52(1)(h) requires a collection "mainly composed of non-copyright matter" and
caps passages per author; a past-paper series is composed mainly of the
copyrighted material itself. **[STRONG]**

**F-09 — Translations are a separate right, with a limited carve-out.** Making a
translation is an exclusive right (s. 14(1)(a)(v)). Section 52(2) extends the
52(1) exceptions to translations only where the underlying act is itself
excepted. CBSE publishes official Hindi versions of papers and sample papers
(S-06, S-07), so translation is unnecessary for coverage — and re-translating an
English paper is a derivative use with no clear permission. **[MODERATE]**

**F-10 — Commercial republication has been enjoined, repeatedly.** *Rupendra
Kashyap* (CBSE past papers, 1996), *Ravinder Singh & Sons* (ICSE past papers
reproduced "in the same sequence with commas and full stops", 2018), and
*Blackwood* (guides, 1958) all restrained near-verbatim reproduction; the 2018
court contrasted a genuinely transformative guide with a substitute for the
paper (S-16, S-17, X-02). **[STRONG]** The counter-example is a guide that adds
step-by-step original analysis and is held to be a different work — which is
closer to Zivon's *explanations* than to a bare question dump, but does not
authorise the bare dump ([MODERATE], X-02).

**F-11 — Facts and patterns are not protected; a close paraphrase can still be.**
Marks distribution, section structure, question typology, chapter weightage and
difficulty are ideas/facts, not expression. Independently written questions that
match a pattern are the low-risk route. But a "rewritten" question that tracks
the original's numbers, set-up and wording is a derivative or substantial
reproduction. **[STRONG] on idea/expression; [MODERATE] on where the line falls**

---

## 4. What CBSE's own terms say

**F-12 — There is one express permission-like statement, and it is conditional.**
The CBSE Website Policy says:

> "Material featured on this site may be reproduced free of charge in prescribed
> format or media without requiring specific permission. This is subject to the
> material being reproduced accurately and not being used in a derogatory manner
> or in a misleading context. Where the material is being published or issued to
> others, the source must be prominently acknowledged. However, the permission to
> reproduce this material does not extend to any material on this site, which is
> explicitly identified as being the copyright of CBSE, implementation partner and
> third party." — S-03

This is the strongest basis short of a signed licence. It grants reproduction
without a fee and without a request, but attaches accuracy, context and
attribution conditions. It is also **not obviously a licence to republish exam
papers commercially**: it speaks of "this site"/"this Portal", and CBSE's
conduct (an exclusive past-paper licence in 1991, enforcement in 1996 — S-16)
points the other way. **[STRONG] that the text says this; [MODERATE]–[WEAK] that
it authorises Zivon's use** → `CQ-01`.

**F-13 — The sample papers live on a subdomain with no policy.** SQPs and their
marking schemes are served from `cbseacademic.nic.in` (S-07 … S-09). That
subdomain publishes no copyright or terms page (four probes, all 404) and its
footer is only "© 2026 CBSE Academic Unit" (S-11). Whether a policy written for
"this Portal" (cbse.gov.in) travels to a different subdomain is unresolved →
`CQ-01`. **[MODERATE]**

**F-14 — CBSE does not apply one permissive rule to everything it publishes.**
A CBSE-published compendium states "The rights reserved — No part of this
publication may be reproduced … without prior permission of the copyright owner"
(S-19). CBSE's own books therefore sit under all-rights-reserved terms while the
website policy grants conditional reproduction. That inconsistency is why this
memo treats the policy as a factor, not a clearance. **[STRONG]**

**F-15 — CBSE frames sample papers as a teaching template, not as a public-domain
paper.** Its 2026-27 notification says SQPs "provide a broad template and serve
as a guide", give "a broad understanding of the question paper design", and
"need to be used for classroom teaching and learning activities" (S-10). That
supports blueprint reuse and classroom-style use; it does not grant commercial
republication. **[STRONG] on the framing; [MODERATE] on the inference**

**F-16 — The name and logo are policed.** CBSE has issued public advisories
against commercial look-alike pages and against handles using its name and logo
(S-12, S-13). Any use of "CBSE" must be a factual, nominative reference; no logo,
no implied endorsement, no "CBSE-approved". **[STRONG] on enforcement activity;
[MODERATE] on the doctrinal outcome** → `CQ-05`.

**F-17 — "Everyone else republishes them" is not a defence.** Dozens of
commercial sites host CBSE papers, and the presence of infringing copies on the
web does not create a licence. This memo does not rely on industry practice; the
informal survey behind that sentence is not evidence and is not cited as such.
**[STRONG] on the legal point; the survey is unsourced.**

**F-18 — Some CBSE question banks are partner-built.** CBSE Academic's own
competency pages state "Developed in collaboration with Sri Aurobindo Society and
ACER" and "Developed in collaboration with British Council and AlphaPlus", and
that practice papers were "developed by Education Initiatives in Collaboration
with CBSE" (S-21; the page spells the company "Education Initiatives" — it is
Educational Initiatives). If P3 ever ingests those banks, the Website Policy's
carve-out for "implementation partner and third party" material applies and
permission must come from the partner. For board papers the same caution means an
item-level check for externally owned diagrams or passages (`CQ-10`). **[STRONG]**

---

## 5. Content-type matrix

`✓` = may display to students, `—` = may not, `int.` = internal/admin only.

| Content | Internal store | Blueprint mode (default) | Verbatim mode (after clearance) | Conditions in verbatim mode |
|---|---|---|---|---|
| CBSE past paper PDF (S-04, S-06) | ✓ | — | ✓ (as extracted items, not the PDF) | Exact text; source line `N-02`; series notice `N-03`; no third-party item; set code recorded |
| CBSE official SQP + MS (S-07 … S-09) | ✓ | — | ✓ | Same as above; label as "sample paper", not "board paper" |
| CBSE marking scheme answer | ✓ | — | ✓ | Reproduced as published; Zivon explanations labelled separately (`N-04`) |
| Derived pattern metadata (marks, type, chapter, difficulty) | ✓ | ✓ | ✓ | No source text in the generator input |
| Newly written question to the pattern | — | ✓ | ✓ | Similarity gate; no "PYQ" claim; `N-01` |
| Official Hindi paper (where CBSE publishes it) | ✓ | — | ✓ | Same conditions; `language=hi` |
| Zivon Hindi translation of an English paper | ✓ (draft) | ✓ (as new item) | — | Not permitted as a verbatim item (`DEC-COMP-004`) |
| Third-party item inside a paper (partner content, external passage/diagram) | ✓ (flagged) | — | — | `third_party_content=true` blocks verbatim publish |
| NCERT textbook extract | — | — | — | Separate source policy; never bundled into exam items |

---

## 6. Decision

**DEC-COMP-001 — Blueprint-only is the shipping default; verbatim is a cleared
mode, not a setting.** R1 publishes exam-pattern content only. The verbatim
pipeline is built and tested internally, but no verbatim item reaches a student
or a public page until a **clearance record** exists in
[`decision-log.md`](decision-log.md): either (a) written permission from CBSE, or
(b) a written opinion from Indian counsel that the intended use is permitted,
including under the Website Copyright Policy. Confidence in the decision:
**[MODERATE]** (it is a risk decision on ambiguous law, deliberately
conservative).

*Why not launch verbatim on the policy alone:* a court would weigh the express
policy, but against it sit (i) the subdomain gap (F-13), (ii) CBSE's exclusive
licensing and enforcement history (F-05, F-10), (iii) the "misleading context"
condition in a commercial product that teaches to the same exam (F-12), and
(iv) the absence of any statement that commercial reuse is permitted. The
downside is an injunction and a credibility hit on a children's product; the
upside of waiting is a one-page permission letter.

**DEC-COMP-002 — Attribution and non-affiliation are mandatory in both modes.**
Every exam-style surface carries the series notice; every verbatim item carries
a source line. The CBSE name appears only in factual sentences. No logo, no
"official", "approved", "affiliated", "exact CBSE paper", or "actual board
paper" for generated items. Copy: `N-01` … `N-04`.

**DEC-COMP-003 — Verbatim means verbatim.** No edits, no re-typesetting that
changes wording, numbers, marks or options; typos are preserved. A correction
becomes a separate Zivon annotation, never a change to the item. This satisfies
the policy's "reproduced accurately" condition and avoids moral-rights exposure
under s. 57.

**DEC-COMP-004 — No re-translation of verbatim items.** Use CBSE's official
Hindi paper where it exists. If it does not, the Hindi version is a newly written
Zivon item in blueprint mode and is never presented as the CBSE question
(F-09).

**DEC-COMP-005 — Third-party material is excluded.** An item with
`third_party_content=true` cannot publish in verbatim mode even after clearance;
the policy carve-out (F-12) and the partner-built item banks (F-18, S-21) make
this non-negotiable.

**DEC-COMP-006 — Generated items are source-blind and similarity-gated.** The
generator receives pattern metadata only, never source question text. A
deterministic near-duplicate check runs before review; a human/agent reviewer
signs off. Thresholds in §7.4.

**DEC-COMP-007 — Marking schemes follow the questions.** Same clearance, same
attribution. Zivon's explanations are labelled as Zivon's and are not attributed
to CBSE (`N-04`).

**DEC-COMP-008 — Takedown is a first-class path.** Public contact, 2-business-day
acknowledgement, same-day hide, 5-business-day review, permanent removal with
cache/CDN purge and sitemap refresh, register entry. Copy: `N-05`; process: §7.6.

**What this does not change:** the AGENTS.md content-sourcing rule. Since the W0
reframe landed (2026-11-15), that rule reads "NCERT (officially free) and
public-domain sources only", plus a CBSE clause: nothing is ingested, reproduced
or published until this memo lands, and P3 ingest/publish stays behind a feature
flag until then. This memo meets that condition, so the operative rule for exam
content is now `DEC-COMP-001` — blueprint-only, with verbatim blocked on the
clearance register — and the sourcing sentence still forbids verbatim
publication. If the founder ever approves verbatim mode, that AGENTS.md sentence
must be amended in the same change.

---

## 7. What P3 must build

P3 owns `factory/exam/**`, `sources/exam/**`, and the exam test set. This section
is the contract; nothing here is implemented by C0.

### 7.1 Modes and flags

| Flag | Values | Default | Behaviour |
|---|---|---|---|
| `EXAM_CONTENT_MODE` | `blueprint_only` \| `attributed_verbatim` | `blueprint_only` | Gates every verbatim publish path |
| `EXAM_VERBATIM_CLEARANCE_ID` | string or empty | empty | Must reference a row in the [clearance register](decision-log.md#clearance-register); empty blocks `attributed_verbatim` |
| `SERIES_EXACT_PYQ_ENABLED` | `true` \| `false` | `false` | Hides the past-year series entirely until both the mode and clearance are set |

The build must fail closed: an unknown value, a missing clearance id, or
`attributed_verbatim` without a clearance row is a startup error, not a silent
fallback.

### 7.2 Per-item metadata

Every item in the bank carries the same fields regardless of mode, so a mode
switch is a publish-time decision, not a migration:

```yaml
item_id: phy12-2024-55-1-1-q23
source_type: generated_blueprint   # generated_blueprint | generated_pattern |
                                   # verbatim_cbse_paper | verbatim_cbse_sqp |
                                   # verbatim_cbse_ms
source_ref:
  board: CBSE
  class_num: 12
  subject: Physics
  subject_code: "042"
  year: 2024
  paper_type: main            # main | compartment | sample (the paper the item came from)
  set_code: "55/1/1"          # papers only; null for SQPs
  language: en                # en | hi
  question_no: "23"
  section: C
  marks: 3
  source_url: https://www.cbse.gov.in/...
  retrieved_at: 2026-11-15
  file_sha256: "<sha256 of the stored PDF>"   # example value, not a real digest
  page: 7
  third_party_content: false
licence_basis: none           # none | cbse_website_policy | written_permission |
                              # counsel_opinion
permission_ref: null          # decision-log row id when licence_basis != none
pattern_ref: null             # archetype id for generated_* items
similarity: null              # {"max_ngram_overlap": 0.0, "checked_at": ...}
```

Rules: `verbatim_*` requires a non-null `source_ref` with `page`, `set_code`
(where applicable), `source_url`, `retrieved_at`, `file_sha256`;
`generated_*` requires `pattern_ref` and a passing `similarity` record;
`third_party_content: true` blocks verbatim publishing.

### 7.3 Publish gate (two stages)

1. **Schema + provenance** — every item has the fields above; verbatim items have
   a source artefact hash that matches the stored PDF; generated items have a
   pattern reference.
2. **Compliance** — `verbatim_*` items additionally require
   `EXAM_CONTENT_MODE=attributed_verbatim`, a valid `EXAM_VERBATIM_CLEARANCE_ID`
   matching `permission_ref`, and `third_party_content=false`. Any failure is a
   hard publish error naming the item id, never a warning.

A publish manifest records the mode, clearance id, item counts by `source_type`,
and the copy version (`N-01`…`N-05`) so an audit can reconstruct what shipped.

### 7.4 Similarity gate for generated items

- Normalise (lowercase, strip punctuation, collapse whitespace, map digits to
  `#`), then compute 8-word shingles.
- Block publish when any generated item shares an 8-gram with a stored source
  item, or when shingle Jaccard against the nearest source item exceeds 0.20.
- Report the nearest source item id and the overlap on failure, so the repair
  loop can rewrite rather than guess.
- Run at ingest time and again at publish time (sources change).

Thresholds are a starting point; P4/P3 may tighten them after measuring the
first generated batch. They are not a legal safe harbour — they are a
copying-prevention control.

### 7.5 Review gate and clearance record

- Every verbatim item needs a reviewer sign-off recorded in the item store
  (`reviewed_by`, `reviewed_at`, `evidence_ref`).
- The clearance itself is a row in [`decision-log.md`](decision-log.md) with the
  instrument (permission letter or counsel opinion), date, scope (classes,
  years, languages), and reviewer. `EXAM_VERBATIM_CLEARANCE_ID` points at it.
- Clearance is scoped: permission for Class 12 Physics does not cover Class 10
  Science.
- Admin (ADM-05) shows mode, clearance id, counts by `source_type`, and any
  blocked items. No student-facing surface exposes these internals.

### 7.6 Takedown path

Public entry point (`N-05`) → ticket → same-day hide → review → permanent
removal or restoration with a written reason → register entry in
[`decision-log.md`](decision-log.md#takedown-register). Removal must purge the
item from: the question bank, any static series manifest, the CDN/cache, and the
sitemap if the page becomes empty. Target: acknowledge in 2 business days,
resolve in 5.

### 7.7 Events and evals (handoff, not implemented here)

P3/P4 add map rows and cards for: `exam.item.ingested`,
`exam.publish.blocked` (reason: `missing_clearance` | `third_party` |
`similarity` | `schema`), and `exam.takedown.received`. Eval coverage under the
Q-5 additive ids: `EV-EXM-###` for source compliance (attribution present,
verbatim text matches source exactly, generated items below the similarity
threshold) and `EV-SER-###` for series assembly. No model judge is needed for
the provenance checks — they are deterministic.

### 7.8 Copy

Ship the exact strings from [`notices.md`](notices.md). Placeholders are resolved
at render time; an unresolved `{{...}}` is a publish error. The publish gate
compares the rendered notice version against the manifest.

---

## 8. What the student sees

**Blueprint mode (R1 default).** A series called "Exam-pattern practice" (not
"PYQ"). Each item looks like a board question, carries marks and a section
label, and the page ends with `N-01`: questions are Zivon's, written to the CBSE
pattern, not CBSE questions, no affiliation. The student still gets the exam
experience — same structure, marks, difficulty and chapter mix — without a claim
we cannot support.

**Verbatim mode (after clearance).** The same series gains a "Past-year
questions" filter. Each item shows the source line `N-02` under the question and
the series intro `N-03`; the year and set are visible so the student can trust
it. Marking-scheme answers carry `N-04`. Nothing else in the UI changes.

**Never, in either mode:** the CBSE logo, "official", "CBSE-approved",
"affiliated", or an unqualified "previous year paper" on a generated item.

---

## 9. Residual risk register

| Risk | Likelihood | Impact | Mitigation | Owner |
|---|---|---|---|---|
| CBSE (or a licensee) sends a notice over verbatim items | Medium if verbatim ships without clearance; Low in blueprint mode | High (injunction, removal, reputational) | `DEC-COMP-001` gate; takedown path; no verbatim in R1 | Founder / P3 |
| A generated item is a close paraphrase of a source question | Medium without a control | Medium | Source-blind generation + 8-gram/Jaccard gate + reviewer | P3/P4 |
| The similarity gate is treated as legal clearance | Medium | High | Stated in §7.4 and in the decision log: it is a copying-prevention control, not a legal opinion | C0 / P3 |
| Name/logo use reads as endorsement | Low with `N-01`/`N-03` | Medium | Nominative use only; no logo; non-affiliation sentence on every surface | F7 / P3 |
| Hindi rendering of a verbatim item is a translation | Medium | Medium | `DEC-COMP-004`: official Hindi only, else new item | P3 |
| Third-party item inside a paper slips through | Low | Medium | `third_party_content` flag + reviewer checklist | P3 |
| Law changes (2026 amendment activity) | Low for s. 52 | Medium | Quarterly review; watch item X-03 | C0 |

---

## 10. Counsel brief

The ten questions are in [`decision-log.md`](decision-log.md#counsel-questions).
The short version to put in front of a lawyer:

1. Does the CBSE Website Copyright Policy license commercial republication of
   question papers, and does it reach `cbseacademic.nic.in`?
2. Who owns the papers — CBSE under s. 17(c)/(dd), or paper-setters under
   *Agarwala*?
3. Is per-question copying inside a commercial bank infringement, or is the
   substantial-part test applied to the paper as a compilation?
4. Does s. 52(1)(i)(ii) cover questions reproduced inside an online mock exam?
5. Does the `N-01`/`N-03` copy neutralise "misleading context" and passing off?
6. Is translating an English paper into Hindi (no official Hindi version)
   infringing?
7. Is the hyperlink-permission clause enforceable, or boilerplate?
8. Is there any Indian notice-and-takedown safe harbour for a publisher, or is
   takedown purely mitigation?
9. Any pending amendment that would change the analysis?
10. How do we identify third-party material inside a paper?

Until answers 1–4 are in writing, `EXAM_CONTENT_MODE` stays
`blueprint_only`.

---

## 11. Review triggers

Re-open this memo when any of these happens: a new CBSE session's papers/SQPs
are published; CBSE updates its Website Policy; CBSE replies to the permission
request; counsel opines; a takedown or legal notice arrives; the Copyright Act or
Rules are amended; or the product changes commercial model (free → paid, or
paid → free). Otherwise review quarterly.

---

## Appendix A — permission request letter (ready to send)

> To: The Secretary / Director (Academics), Central Board of Secondary
> Education, Shiksha Kendra, 2 Community Centre, Preet Vihar, Delhi 110092
>
> Subject: Request for permission to reproduce CBSE question papers and marking
> schemes in an educational practice product
>
> Dear Sir/Madam,
>
> Zivon is an independent online Physics learning platform for Classes 9–12. We
> would like to include questions from CBSE Class 10 Science (Physics section)
> and Class 12 Physics (042) question papers, official sample question papers and
> marking schemes, for the years 2022–2026, in our practice and mock-test
> features.
>
> We would reproduce the questions accurately and without modification, display
> the paper year, set and question number with each item, state prominently that
> the material is published by CBSE, and state clearly that Zivon is not
> affiliated with or endorsed by CBSE. We would not use the CBSE logo. The
> material would be available only to registered students for practice, and we
> would remove any item on a written request from CBSE.
>
> We request your written permission for this use, or guidance on the terms you
> would require. We are happy to provide a sample of the proposed display and
> attribution.
>
> Yours faithfully,
> [Name], [Role], Zivon, [email], [phone]

Send from a monitored address, keep the acknowledgement, and record the outcome
in the decision log. **No reply is not permission.**

---

## Appendix B — what was not verified

- Whether CBSE holds assignments from every paper-setter for 2022–2026 (F-05).
- Whether the Website Policy is intended to cover PDFs (as opposed to HTML
  pages) and commercial reuse (F-12).
- Whether `cbseacademic.nic.in` has an unlinked policy document; the four
  conventional paths returned 404 and the homepage links none (F-13).
- Whether any 2026 amendment bill will change s. 52 (X-03).
- Whether CBSE's 2022–2026 papers contain third-party-owned diagrams or adapted
  passages; this needs an item-level review, not a desk review (F-18, `CQ-10`).
