# Content-quality checklist

Work top to bottom. Each section names the contract, what to inspect, the evidence that closes it, and the usual severity. Skip a section only when the artifact cannot contain it (say which, and why).

Evidence labels: **confirmed** = opened, ran, or recomputed; **likely** = strong reading; **suspected** = a question.

## 1. Schema and ID integrity

| Check | Evidence | Default severity |
|---|---|---|
| The artifact validates against its schema (`GENERATED`, `BLOCKS`, `LESSON`, practice-pack, series-manifest, translation unit) | schema/unit test output, run artifact, or a direct validator run | blocker if the artifact cannot load; major otherwise |
| Every block carries `id` matching `^b-[0-9]{2}$`; ids are unique and stable across re-render and translation | `grep`/JSON walk over the page, manifest, i18n keys | major |
| Every payload lives under `spec`; no stale `content`/bare `question` field | `docs/content-factory/blocks-schema.md`; schema validator | major |
| Block type is one of `text`, `worked_example`, `check`, `reveal`, `diagram`, `simulation` | same | major |
| Manifest carries identity and provenance: `course_id`, `class`, `title`, `lesson_title`, `chapter.title`, `chapter.number`, `sources`, `run_id`, `generated_at`, `block_counts`, `pipeline_version` | `manifest.json`, `catalogue.json`, `courses.js` | major |
| `lesson_title` is present and is not a model headline or a data label; `chapter.title` is the chapter, never `"Grade"`, `"Chapter"`, `"Unknown"`, or an empty string | manifest + rendered H1/title | major |
| One topic per course+chapter; no stale duplicate directory for the same chapter | `factory/link.py` prune behaviour; `find frontend/courses -name manifest.json`; catalogue entries | major |
| Catalogue ordering is class → `chapter_number` → chapter → title; unnumbered last | `frontend/courses.js`; `factory/render.py::write_courses_js` | minor–major |
| Series/pack manifest counts match the items present; item ids unique; no duplicate stem | pack manifest + a uniqueness scan | major |

## 2. Citations and source grounding

The grounding law (`docs/content-factory/architecture.md`, "Traceability and accuracy rules"): the source pack is the whole universe of the page. The model's own Physics knowledge does not count.

- [ ] The source pack is the **right chapter**: `chapter.title`, `chapter.number`, `class`, and `book` match the request, and `matched_via` is `title_line`. A `body_phrase` match is a loud warning in stage 01 and needs manual verification; a class-11 "Motion in a Straight Line" page built from the Laws of Motion chapter is the failure this check exists for.
- [ ] Every factual block (`text`, `worked_example`, `check`, `reveal`) has `citations` with at least one real `claim_id`.
- [ ] Every `claim_id` exists in the run's ground truth; every ground-truth claim points to a passage in the source pack.
- [ ] The cited passage actually supports the sentence. A citation that exists but does not support the claim is **citation theatre** (major; blocker if the sentence is wrong).
- [ ] No concept from a later or earlier chapter is taught, tested, or named as background. Check the chapter inventory, not just the page's own vocabulary.
- [ ] The mandatory `uncertain` field is carried; it is not silently resolved by an invented fact.
- [ ] Numbers in a problem or question appear verbatim in the ground truth or primary source (whole-numeral match; `5` does not match `15`).
- [ ] Answers and options are **not** source-matched; they are recomputed (see §4).
- [ ] Source attribution is visible in the footer/manifest and respects the NCERT/public-domain licence; no copied copyrighted textbook passage.

Detection: `factory/checks.py::rule_citations`, `rule_numbers`, `rule_self_containment`; `evals/checkers/curator_checks.py`; `evals/cards/EV-CUR-001.yaml`.

## 3. Answer keys and explanations

For every `check` and every practice/test item:

- [ ] MCQ has exactly one correct option; `answer_index` points to it; `answer` text equals `options[answer_index]` (hard rule, `rule_answer_keys`).
- [ ] Numeric items use `format: numeric` with a bare-number `answer`; no units, prose, or equation in the answer field.
- [ ] The explanation says **why** the correct answer is correct and, where possible, why the tempting distractor is wrong. Empty, one-word, or answer-restating explanations are a defect.
- [ ] The explanation does not contradict the answer or introduce a second method that gives a different result.
- [ ] The stem does not leak the answer before commit; the answer is not in the narration, the `aria-label`, or an always-visible node.
- [ ] Distractors are plausible and each maps to a misconception where the schema allows it.
- [ ] The item is answerable from the chapter's taught content, not from general knowledge the chapter does not supply.
- [ ] One concept per item; no compound question that marks a learner wrong for a second unstated error.

Default severity: wrong key = **blocker**; missing explanation = **major**; thin explanation = **minor**.

## 4. Numeric tolerance, units, and significant figures

- [ ] Recompute every worked example and numeric answer from the equations the chapter states. Show the equation and the substituted values in the finding.
- [ ] Worked-example steps are coherent: each step follows from the previous, algebra is not skipped in a way that changes the result, and the final answer matches the last step.
- [ ] Declare tolerance for numeric items that expect a rounded answer. Use a relative tolerance (golden schema defaults to `0.02`) unless the item states an absolute one; justify a tighter or looser value.
- [ ] Units are present, correct, and consistent (m/s vs km/h, N vs kgf, J vs kJ); conversions are shown or stated.
- [ ] Significant figures and rounding are consistent with the data given; do not demand more precision than the inputs support.
- [ ] A unit mismatch or a missing conversion that changes the answer is a **blocker**; a units omission that does not change the answer is **major**.
- [ ] If an answer cannot be recomputed from the page's own equations, say `unverified:` and do not claim it is verified. A suspicion never becomes a fatal finding without evidence.

Contract note: `docs/content-factory/blocks-schema.md` still carries an older sentence that answer numerals are held to the verbatim rule; `factory/checks.py::rule_numbers` and `docs/content-factory/architecture.md` say answers and options are deliberately **not** code-checked and are recomputed by `03-check`. Follow the enforced code/architecture and hand the doc drift to `review-docs-sync`.

Golden anchors: `evals/goldens/topics/*/expected.json` → `canonical_numerical_anchors` (`expected_answer_values`, `tolerance_rel`).

## 5. Curriculum coverage, teach order, and block budget

The coverage contract (`docs/content-factory/architecture.md`; `03-check` coverage gate): inventory the chapter's titled sections, in-text questions, worked examples, and end-of-chapter exercise **types**; map each to a lesson section/check/worked_example/reveal; nothing may be dropped. Repeats may fold into the most instructive instance, but no type may be missing.

- [ ] Every titled section appears, in textbook order (or a justified pedagogical order that still teaches prerequisites first).
- [ ] Every exercise **type** appears; identical repetitions may share one block.
- [ ] Teach-before-test: every concept a check tests has been taught earlier on the page, or in a prerequisite section explicitly marked as such.
- [ ] Block sequence: 4–45 blocks; first block `text`; last block `check`; at least 3 checks spread through the page; diagrams/simulations interleaved where a teacher would put them.
- [ ] No padding: a block exists to teach, check, or show something in the chapter, not to fill a count.
- [ ] A coverage omission is **major**; omitting a whole exercise type or a section is **major** (blocker only when the page claims full coverage and the omission makes the page misleading).
- [ ] The block-budget tension is acknowledged: if the chapter inventory is larger than 45 blocks, the fold rule applies; do not demand a 70-block page.

## 6. Marks, sections, blueprints, and series volume

For papers, practice sets, and series manifests:

- [ ] Section structure matches the declared blueprint (number of sections, question types per section, choice rules).
- [ ] Marks per item match the type and the blueprint; section subtotals and the paper total add up.
- [ ] Duration is stated and plausible for the total marks; time priors (`expected_time_ms`) are non-negative and within sane bounds.
- [ ] Difficulty mix is within the declared bands; no all-easy or all-hard set.
- [ ] Every chapter in every full-paper series is represented; every concept in `AI Lesson` and `Challenge`/`Loop`; no chapter below the approved minimum volume (the working bar is at least 10 questions per chapter).
- [ ] Series manifests state counts, difficulty, languages, duration, marks, coverage, and source policy truthfully.
- [ ] No duplicate item across series unless the blueprint intentionally reuses a PYQ; if reused, say so.
- [ ] Marks mismatch or a missing chapter in a full-paper series is **major**; a total that does not add up is **major** (blocker if the paper is already published and a learner is scored on it).

## 7. Language coverage and script policy

Product rule (frozen language decision; `docs/product/features.md` T2, F-WRP-LAN-01): lessons, UI, AI tests, challenge, and loop are **EN + HI + Hinglish**; CBSE-style series are **EN + HI only**. Hinglish absence is not a defect on a CBSE-style paper; English-only on a lesson that claims `hi`/`hi-Latn` is.

- [ ] Every promised locale is present for every user-visible string; `manifest.locales_available` and `translation_status` are truthful (`verified` vs `partial`/fallback ids).
- [ ] `hi` is Devanagari; native-script prose is at least 40% native characters (`rule_trans_script_purity`).
- [ ] `hi-Latn` contains **zero** Devanagari characters; it is Roman-script Hinglish, not Hindi in disguise.
- [ ] First mention of a Physics term is `<native term> (<English term>)`; subsequent mentions are consistent with the glossary (`docs/specs/translation/spec.md`; `ADR-0023`).
- [ ] Numerals, SI units, variables, equations, citations, and SVG geometry are never translated or transliterated.
- [ ] No silent fallback: an unavailable locale shows a disabled chip and an honest "not available yet" marker, never English pretending to be Hindi.
- [ ] No untranslated leak: a localized page has no English sentence in a body/check/explanation position unless it is a term, unit, or quoted source.
- [ ] Hinglish is natural code-mixing (English technical nouns, Roman Hindi clauses), not transliteration or stiff machine translation; technical terms stay in standard English spelling.
- [ ] `data-i18n` coverage is complete on localized routes; canvas strings use `ctx.t_str` where the block has `sim_strings`; SVG `<text>` labels are in `svg_texts`.
- [ ] Glossary terms are present in every promised locale; a missing glossary term is **minor**, a false "verified" claim is **major**.

## 8. Copy and claim compliance

- [ ] Generated items/papers say "close to the paper pattern", "built for practice", or "not an official CBSE paper". Never "official", "exact CBSE", "CBSE-approved", or "past paper" for generated content.
- [ ] "Exact PYQ" is used only when the item is an actual past question with source attribution and legal clearance; otherwise it is a claim violation.
- [ ] No guarantee of marks, rank, selection, or score; no fear/urgency/dark-pattern copy; no shaming of a wrong answer.
- [ ] No unsafe practical instruction (mains electricity, sharp objects, chemicals, unsupervised experiments); no medical/legal/financial advice; no stereotypes or discriminatory examples; no external brand promotion. A dangerous instruction is **blocker**; a stereotype or inappropriate example is **major**.
- [ ] Age-appropriate, encouraging tutor voice: patient, clear, step-by-step, Socratic; no sarcasm, no "obviously", no "you should already know".
- [ ] Source/licence attribution is present and accurate; NCERT copyright terms are respected; no copied copyrighted textbook text.
- [ ] Translation preserves the claim, not just the sentence: a translated page must not add or soften a promise.
- [ ] Claim violations are **major**; an official-endorsement claim or a guaranteed-score claim is **blocker** (legal/consumer risk).

## 9. Technical page integrity

- [ ] HTML has doctype, viewport, canonical + `hreflang`, `assets/zivon.css`, `main.zn-page`, header (kicker/title/objectives), ordered blocks, glossary, sources footer, `assets/zivon.js`, optional `page.js`/`page.css`.
- [ ] Every block has a stable `id="b-NN"`; `data-block-type`/`data-element-id`/`data-concept-id` are present where the PR/spec requires them.
- [ ] No inline `<script>` or `<style>`; all JS lives in `page.js`/`zivon.js` and loads from `'self'`.
- [ ] CSP: lessons/`/courses/` and `/privacy/` use the documented `connect-src`; every other location stays `connect-src 'none'`; no external hosts.
- [ ] No `eval`, `new Function`, `document.write`, dynamic `import`/`require`, `fetch`, `XMLHttpRequest`, `WebSocket`, `EventSource`, `sendBeacon`, or string-literal HTTP(S) URL in generated JS (`factory/lint.py::lint_js`).
- [ ] CSS has no `@import` or `url(http...)`; `page.css` stays inside the block's `.zn-sim-<id>` scope and does not size the canvas (`lint_page_css_scope`).
- [ ] Diagrams are inline SVG: start with `<svg`, presentation attributes only, no `<script>`, `<style>`, external URLs, embedded images, or event handlers; `aria-label`/caption present.
- [ ] Simulations use `ZivonSim.register("<block-id>", {init, draw})`, canvas 2D only, controls with `id/label/min/max/step/initial`, a `.zn-sim-read` live readout, a description, reduced-motion support, and the on-canvas error painter.
- [ ] Computed geometry (graphs, areas, trajectories) is computed in JS from the cited equations; a hand-placed SVG graph of computed data is a finding.
- [ ] Checks are keyboard-native fieldsets with `aria-live` feedback, retry, and a "Why?" explanation; numeric input parses the first number and reports a friendly error.
- [ ] Internal links resolve; locale hrefs point to an existing localized page or an honest English fallback; no `zivon.local` placeholder in a production path.
- [ ] `sitemap.xml`/`robots.txt` are generated, list real URLs, and are not hand-edited.

Any hard lint hit is **blocker**. A broken link is **major** (blocker if the page is the only route to the lesson).

## 10. Accessibility and performance

Use WCAG 2.2 AA as the working bar (`https://www.w3.org/TR/WCAG22/`), and the repo's own state matrix where it is stricter.

- [ ] Every non-text element has a useful text alternative; decorative SVG is ignored by assistive tech (`1.1.1`).
- [ ] Structure is programmatic: headings in order, lists, fieldsets, `lang` on the page and on foreign-language parts (`1.3.1`, `3.1.1`, `3.1.2`).
- [ ] Colour is not the only signal; contrast is at least 4.5:1 for body text and 3:1 for large text/non-text controls (`1.4.1`, `1.4.3`, `1.4.11`).
- [ ] Reflow works at 320 CSS px (review at 360 px for the product); no horizontal overflow (`1.4.10`).
- [ ] All controls are keyboard reachable, focus is visible, no trap; target size is at least 24×24 CSS px (`2.1.1`, `2.1.2`, `2.4.7`, `2.5.8`).
- [ ] Names, roles, values are correct; status messages are announced politely (`4.1.2`, `4.1.3`); `aria-live` does not flood.
- [ ] Reduced motion is honoured; no autoplay audio; pauses are available (`2.2.2`, `2.3.3`).
- [ ] Page passes the weak-android profile: load/FCP/RSS/FPS, zero console/page errors, overflow within 2 px at 360/1280 (`factory/perf.py`; `testing/content_factory/perf/profiles/weak-android.json`).
- [ ] JS/CSS bytes are measured. Do not fail a PR for the pre-existing budget ambiguity (Q-4 in the handshake); do flag a new bundle that adds bytes without a measurement.
- [ ] Serious/critical axe findings or a keyboard trap are **major**; a page that cannot be read at 360 px is **blocker** if the content is unusable.

## 11. Narration (when the artifact includes audio)

Contract: `docs/specs/gaps/gap-register.md` §GAP-015; `docs/content-factory/architecture.md` stage 12.

- [ ] Speakable selection follows the block rules: `text` full prose; `worked_example` problem + steps + answer; `check` question + options and **never** the answer/explanation; `simulation` title + description + readout strings; `diagram` `svg_texts` only; `b-00-meta` title + objectives; `reveal` not speakable.
- [ ] No JS code, no raw SVG, no answer, no hidden explanation is read aloud.
- [ ] Unit pronunciation rules hold (`m/s²` → "metres per second squared"); numbers and symbols are spoken correctly.
- [ ] Timbre tags are from the 13-tag v3.0 catalog; unknown tags are stripped; no more than the documented cue budget.
- [ ] Every speakable block has an asset, or the manifest says `available: false` and the UI shows the disabled state; never a broken player.
- [ ] `narration-manifest.json` matches the topic manifest: block id, lang, hash, chars, duration_ms, path; the content hash matches the text.
- [ ] Audio paths are `audio/<course_id>/...`, immutable, and served with the documented cache policy.
- [ ] A narration failure never fails the page; it degrades honestly.
- [ ] Reading an answer aloud is a **blocker**; a missing asset that the manifest claims is present is **major**.

## 12. Eval, logging, and content-debt evidence

The eval contract is `docs/specs/evals/spec.md` (deterministic-first funnel, cards, regression store); `card-template.md` and `golden-sets.md` define the shapes.

- [ ] The PR has an eval card covering the stage/failure mode; deterministic checkers are registered and referenced; the card is not judge-only.
- [ ] Goldens exist and are registered (`evals/goldens/manifest.json`); seeded defects cover the new failure mode where applicable.
- [ ] `python -m evals run --suite smoke --mock` passes; `--fail-on-regression` is used where the PR is a regression check.
- [ ] Reviewer/prompt changes include calibration; recall/specificity is not worse than the last baseline.
- [ ] The PR links the eval run id and `eval_summary.md`; the run report and `issues_ledger.jsonl` are available.
- [ ] Human edit rate is recorded for a content batch where the workflow calls for it (`python -m evals record-edit ...`).
- [ ] Kid-test evidence, if any, uses the DPDP-validated payload; no raw audio, no names, no free text from a child.
- [ ] Stage events go through `logging_manager`; each has a row in `docs/specs/observability/instrumentation-map.csv`; no content/text/answers/prompts in `fields` (privacy class), no secrets.
- [ ] Content debt is recorded in `TIMELINE.md` or the PR body with artifact, owner, severity, and reproduction. No new TODO file; no hidden debt.
- [ ] Missing evidence for a new failure mode is **major**; judge-only coverage for a deterministic defect is **major**; a log field containing learner text or an answer is **blocker**.

## Final sign-off

| Question | Answer |
|---|---|
| Artifact and stage map written? | |
| Every answer key recomputed? | |
| Every factual block traced to a source passage? | |
| Coverage mapped to the chapter inventory? | |
| Locale coverage and script policy checked? | |
| Hard lints, links, CSP, and console clean? | |
| Accessibility and weak-android evidence present? | |
| Eval run id and ledger attached? | |
| Content debt recorded with owner? | |
| What was **not** reviewed? | |
