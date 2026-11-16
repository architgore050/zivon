# Compliance decision log

Decisions about third-party content reuse, in force for the Zivon build.
Read [`cbse-exam-content.md`](cbse-exam-content.md) for the reasoning and
[`sources.md`](sources.md) for the evidence. **Not legal advice** — see the
folder [`README.md`](README.md).

Status legend: **Active** = in force for engineering; **Blocked** = cannot be
used until a named event happens; **Superseded** = kept for history.

## Decisions

| ID | Decision | Status | Confidence | Evidence | Owner | Review |
|---|---|---|---|---|---|---|
| `DEC-COMP-001` | **Blueprint-only is the shipping default.** `EXAM_CONTENT_MODE=blueprint_only`. Verbatim CBSE past/sample questions and marking schemes may publish only in `attributed_verbatim` mode, with a clearance id that resolves in the register below (written CBSE permission or a written Indian-counsel opinion). A notice does not create permission. | Active | [MODERATE] | F-01, F-05, F-10, F-12, F-13, F-16; S-01, S-03, S-14, S-16, S-17 | C0 → founder | 2027-02-15 |
| `DEC-COMP-002` | **Attribution and non-affiliation are mandatory in both modes.** Every exam-style surface carries `N-01` or `N-03`; every verbatim item carries `N-02`. The CBSE name appears only in factual sentences. No logo, and no "official", "approved", "affiliated", "exact CBSE paper", or "actual board paper" claim for generated items. | Active | [STRONG] as a risk control | F-16; S-12, S-13 | C0 → F7/P3 | 2027-02-15 |
| `DEC-COMP-003` | **Verbatim means verbatim.** No edits, re-numbering, re-typesetting that changes wording/numbers/marks/options, and no typo fixes. A correction is a separate Zivon annotation, never a change to the item. | Active | [MODERATE] | F-12, F-14; S-03 | P3 | 2027-02-15 |
| `DEC-COMP-004` | **No re-translation of verbatim items.** Use CBSE's official Hindi paper where it exists; otherwise the Hindi rendering is a newly written Zivon item in blueprint mode and is never presented as the CBSE question. | Active | [MODERATE] | F-09; S-06, S-07 | P3 | 2027-02-15 |
| `DEC-COMP-005` | **Third-party material is excluded from verbatim use.** `third_party_content=true` blocks publishing even after clearance. Applies to partner-built item banks and to externally owned diagrams/passages inside a paper. | Active | [STRONG] | F-12, F-18; S-03, S-21 | P3 | 2027-02-15 |
| `DEC-COMP-006` | **Generated items are source-blind and similarity-gated.** The generator receives pattern metadata only, never source question text. An 8-gram/Jaccard gate plus reviewer sign-off blocks near-duplicates. The gate is a copying-prevention control, not a legal opinion. | Active | [STRONG] as an engineering control | F-11; S-16, S-17 | P3/P4 | 2027-02-15 |
| `DEC-COMP-007` | **Marking schemes follow the questions.** Same clearance and attribution as the question; Zivon explanations are labelled as Zivon's and are not attributed to CBSE (`N-04`). | Active | [MODERATE] | F-02, F-12; S-05, S-09 | P3 | 2027-02-15 |
| `DEC-COMP-008` | **Takedown is a first-class path.** Public contact `N-05`; acknowledge in 2 business days; hide the item the same day; decide within 5 business days; purge bank/manifest/CDN/sitemap; record in the register. | Active | [STRONG] as a mitigation (not a safe harbour — `CQ-08`) | F-16; S-12, S-13 | P3 → founder | 2027-02-15 |

**No clearance exists as of 2026-11-15.** Therefore `EXAM_CONTENT_MODE` stays
`blueprint_only` and `SERIES_EXACT_PYQ_ENABLED` stays `false`. Flipping either
without a row below is a publish-gate violation, not a configuration choice.

## Clearance register

One row per instrument that permits verbatim publishing. `EXAM_VERBATIM_CLEARANCE_ID`
must equal a `clearance_id` in this table. Scope is explicit: a clearance for
Class 12 Physics does not cover Class 10 Science, another language, or another
year range.

| clearance_id | Instrument | Scope (class / subject / years / language) | Issued | Review | Recorded by | Document ref |
|---|---|---|---|---|---|---|
| _(none)_ | — | — | — | — | — | — |

Instrument values: `written_permission` (CBSE letter/email), `counsel_opinion`
(written opinion from Indian counsel). A verbal assurance, a support reply, or a
public policy page read without an opinion is **not** a clearance row.

## Counsel questions

Put these to an Indian copyright lawyer before any verbatim launch. Each is
written to be answerable in one page rather than open-ended.

| ID | Question | Why it matters | Blocks |
|---|---|---|---|
| `CQ-01` | Does the CBSE Website Copyright Policy (`S-03`) license commercial republication of question papers and marking schemes, and does it reach content served from `cbseacademic.nic.in` (`S-11`)? | This is the only permission-like statement found. Its scope decides whether verbatim is possible without a signed licence. | `DEC-COMP-001` |
| `CQ-02` | Who owns copyright in each year's papers — CBSE under s. 17(c)/(dd), or the paper-setters under *Agarwala* (`S-15`) absent proved assignment? Does CBSE's chain hold for 2022–2026? | If CBSE does not own the rights, even a CBSE letter may not clear them. | `DEC-COMP-001` |
| `CQ-03` | Is copying individual questions inside a commercial bank infringement assessed per question, or against the paper as a compilation (the "substantial part" test)? | Decides whether short numericals are lower risk than full-paper reproduction. | `DEC-COMP-001`, `DEC-COMP-006` |
| `CQ-04` | Does s. 52(1)(i)(ii) ("as part of the question to be answered in an examination") cover reproducing past questions inside an online mock test? Does the commercial, on-demand nature matter? | This is the only statutory hook for a mock exam, and it is currently rated `[WEAK]`. | `DEC-COMP-001` |
| `CQ-05` | Do `N-01`/`N-03` neutralise the "misleading context" condition and passing-off risk, given the product teaches to the same exam? | Copy is the main mitigation available if verbatim ever ships. | `DEC-COMP-002` |
| `CQ-06` | Is translating an English paper into Hindi (where CBSE publishes no official Hindi version) an infringing translation under s. 14(1)(a)(v), notwithstanding s. 52(2)? | Blocks a translated verbatim series. | `DEC-COMP-004` |
| `CQ-07` | Is CBSE's "prior permission is required before hyperlinks" clause enforceable, or is it unenforceable boilerplate? | Affects whether the source line hyperlinks to CBSE or cites a bare URL. | `DEC-COMP-002` |
| `CQ-08` | Is there any Indian notice-and-takedown safe harbour for a publisher (as opposed to an intermediary)? | We must not claim statutory immunity we do not have. | `DEC-COMP-008` |
| `CQ-09` | Is any pending Copyright Act/Rules amendment likely to change the s. 52 analysis in the next 12 months? | A change could reopen the decision before launch. | `DEC-COMP-001` |
| `CQ-10` | How should Zivon identify third-party-owned material (diagrams, adapted passages, partner items) inside a CBSE paper? | Needed for the `third_party_content` flag to be reliable. | `DEC-COMP-005` |

## Takedown register

Append-only. One row per received request, including requests later rejected
(record the reason). Target: acknowledge in 2 business days, decide in 5.

| Date received | Channel | Item ids / URLs | Action | Decided | Notes |
|---|---|---|---|---|---|
| _(none)_ | — | — | — | — | — |

## Decision history

| Date | Change | Commit |
|---|---|---|
| 2026-11-15 | Research memo and source register landed as a WIP checkpoint | `b4386b4` |
| 2026-11-16 | `DEC-COMP-001`…`008`, clearance register, counsel questions, takedown register, notice copy, docs contract test | this PR |
