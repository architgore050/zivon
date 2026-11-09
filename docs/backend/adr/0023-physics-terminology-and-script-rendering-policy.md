# ADR-0023: Physics Terminology, Numeral, and Indic Script Rendering Policy

- **Status**: accepted
- **Date / deciders**: 2026-11-09 / SP2-TRANS (Wave S1 architecture spec), building on ADR-0009 (language/locale model), T2 & T4 tension resolutions in `docs/product/features.md`, and `DCR-001` (per-script vertical text offset note)
- **Driving NFRs / requirements**:
  - `NFR-TRN-06`: Zero physics meaning distortion or board-exam terminology lock-out — students learning in Hindi (`hi`), Hinglish (`hi-Latn`), or regional Indic languages (`ta`, `te`, `mr`, `bn`, `gu`, `kn`, `ml`, `pa`) must learn both the native concept name and the exact English term used on national entrance exams (JEE/NEET/CUET) and CBSE/state board papers. `[STRONG]`
  - `NFR-TRN-07`: Zero breakage of deterministic code checks (`factory/checks.py::rule_numbers`, `rule_answer_keys`) and client quiz grading (`frontend/assets/zivon.js::firstNumber`). `[STRONG]`
  - `NFR-TRN-08`: Zero vertical baseline clipping, matra collision, or 36px `--row` ruled-line drift on Indic scripts (`DCR-001`, `docs/frontend/design-doctrine.md` §10.2–§10.3). `[MODERATE]`

## Context

Translating Class 9–12 Physics lessons for Indian students presents four concrete technical and pedagogical hazards (`skills/zivon-product-design-skills/skills/zivon-product-design/references/05-voice-translation-tts-ux.md` §2.2–§2.3 and `07-zivon-tensions-to-resolve.md` T2, T4):

1. **Pure native terminology vs. exam reality**: Pure literary Hindi/Tamil translations often replace terms like *velocity*, *acceleration*, *momentum*, or *displacement* with formal Sanskritized/classical terms alone (`वेग`, `त्वरण`, `संवेग`, `विस्थापन`) without showing the English term. When the student later sits a competitive exam or reads a simulation label, they cannot bridge the terms. Conversely, keeping *only* English terms in native prose fails state-board Hindi/Tamil-medium learners whose NCERT vernacular editions use the official NCERT vernacular glossary.
2. **Hinglish (`hi-Latn`) orthography chaos**: Hinglish has no standardized dictionary spelling. Without an explicit orthographic contract, an LLM mixes Devanagari and Latin scripts randomly or translates technical equations into ambiguous slang.
3. **Numeral and symbol corruption**: If a translator converts Western Arabic numerals (`0–9`, e.g. `9.8 m/s²`) into Devanagari digits (`९.८ मी/से²`) or Tamil digits, two critical systems break:
   - Build-time `factory/checks.py::rule_numbers` (which regex-matches `\d+(?:\.\d+)?` against the ground-truth corpus).
   - Runtime `frontend/assets/zivon.js::firstNumber` (which parses numeric check answers via `/-?\d+(?:\.\d+)?/`).
   Moreover, NCERT Hindi, Tamil, and Maharashtra/State Board Class 9–12 Physics textbooks universally use international SI symbols (`m/s`, `N`, `kg`, `v = u + at`) and Western Arabic numerals (`0–9`) per the Standards of Weights and Measures Act / NCERT curriculum standard.
4. **Indic script vertical metrics on the 36px `--row` ruled grid (`DCR-001`)**:
   - `docs/frontend/design-doctrine.md` §10.2–§10.3 specifies a strict `--row` (`2.25rem = 36px`) ruled-line grid where `LessonKit` (`frontend/assets/zivon.js::normalize`) shifts each block element's `top` offset so its baseline matches the Courier Prime reference offset (`REF = lineOffset(refNode)`).
   - Indic scripts (Devanagari, Tamil, Telugu, Bengali, Gujarati, Kannada, Malayalam, Gurmukhi) have taller ascenders/descenders (above-base matras like `ी`, `ै`, `ौ`, `ं` and below-base subjoined vowels/viramas like `ु`, `ू`, `ृ`, `्`) and deeper font ascent metrics in Kalam / Nirmala UI / Noto Sans Indic than Latin Courier Prime. Also, translated strings expand horizontally by +15% to +35% in character width, which can overflow simulation slider labels and SVG `<text>` boxes if unbudgeted.

## Options considered

| Option | Pros | Cons | Cost / ops burden | Fails which NFR? |
|---|---|---|---|---|
| **Option 1: Pure native translation (translate terms, units, and numerals into native script)** | Reads like traditional literary prose. | Breaks `rule_numbers` and `zivon.js::firstNumber`; alienates students from international SI symbols (`m/s²`, `N`, `J`) required by NCERT/CBSE; hides English exam terms. | High code breakage & pedagogical harm | Fails `NFR-TRN-06`, `NFR-TRN-07` |
| **Option 2: Keep all technical nouns in English only (code-mixed everywhere)** | Simple prompt; zero glossary lookup. | Unacceptable for Hindi-medium / Tamil-medium state-board students who need official NCERT vernacular terms (`वेग`, `त्वरण`) for their school exams. | Fails vernacular board learners | Fails `NFR-TRN-06`, `ADR-0009` |
| **Option 3 (Selected): Bilingual First-Mention Gloss + Immutable SI/Numeral/Symbol Invariant + Per-Surface Expansion Budgets + `DCR-001` Script Offset Rules** | Serves both vernacular-medium and English-transitioning learners; preserves 100% compatibility with `checks.py` and `zivon.js`; prevents SVG/slider overflow and baseline collision. | Requires passing the chapter's canonical glossary subset in the per-block prompt and checking term/unit/numeral invariants in `10b-transcheck`. | Low: deterministic regex checks + small glossary table | Meets all NFRs |

## Decision

We adopt **Option 3**, establishing four binding rules across the translation pipeline and frontend shell:

### 1. Physics Terminology Policy (Bilingual First-Mention Gloss)
- **Native-script locales (`hi`, `ta`, `te`, `mr`, `bn`, `gu`, `kn`, `ml`, `pa`)**:
  - On the **first mention** of a glossary Physics term within a block (and in `lesson.glossary` `term` entries), emit the canonical NCERT native term followed immediately by the English term in parentheses: `<Native Term> (<English Term>)`, e.g. `वेग (velocity)`, `त्वरण (acceleration)`, `विस्थापन (displacement)`.
  - On **subsequent mentions** within the same block, use the native term alone (`वेग`, `त्वरण`) to keep prose natural and concise.
  - On **ultra-short UI surfaces** (`simulation.spec.controls[].label` and `diagram.spec.svg` `<text>` labels, which have a strict 1–3 word / pixel width budget), use `<Native Short Term> (<SI Symbol/Unit>)` — e.g. `त्वरण a (m/s²)` or `वेग v (m/s)` — omitting the parenthetical English word when the SI symbol already anchors the quantity.
- **Hinglish (`hi-Latn`, Latin script)**:
  - Written strictly in **Latin script (Roman alphabet)** — zero Devanagari characters (`[\u0900-\u097F]` is a hard deterministic check failure in `hi-Latn`).
  - Technical Physics nouns stay in standard English spelling (`velocity`, `acceleration`, `displacement`, `momentum`, `force`, `slope`, `area`), while explanatory verbs, connectors, and Socratic scaffolding use natural conversational Hindi in Roman script (e.g., *"Jab object constant acceleration se move karta hai, tab v-t graph ek straight line hota hai"*). On first definition of a core concept in a lesson section, include the Romanized Hindi term in parentheses if commonly used in speech: `velocity (veg)`, `acceleration (tvaran)`, `displacement (visthapan)`.

### 2. Immutable Token Invariant (Never Translate or Transliterate)
The following tokens must remain **character-for-character identical** to the English source block across all locales:
1. **Western Arabic numerals**: `0123456789`, decimal points `.`, negative signs `-` / `−`, scientific notation (`10^-3`, `3.06`). Regional Unicode digit blocks (`U+0966..U+096F` Devanagari, `U+0BE6..U+0BEF` Tamil, etc.) are **forbidden** and blocked by `rule_trans_numbers`.
2. **SI units and compound unit expressions**: `m`, `s`, `kg`, `N`, `J`, `W`, `Pa`, `Hz`, `C`, `V`, `A`, `Ω`, `m/s`, `m/s2`, `m/s²`, `m s^-1`, `m s^-2`, `km/h`, `N m`, `kg m/s`.
3. **Physics & mathematical variables, formulas, and equations**: `v`, `u`, `a`, `t`, `s`, `x`, `F`, `m`, `p`, `E`, `W`, `g`, `Δ`, `θ`, `ω`, `λ`, `v = u + at`, `s = ut + 1/2 at²`, `v² - u² = 2as`.
4. **Structural & citation identifiers**: `block.id` (`b-01`), `citations[].claim_id` (`claim-01`), `citations[].source_id`, `simulation.spec.controls[].id`, `check.spec.format` (`"mcq" | "numeric"`), `check.spec.answer_index`, and SVG geometry/attributes (`viewBox`, `d`, `x`, `y`, `x1`, `y1`, `x2`, `y2`, `cx`, `cy`, `r`, `width`, `height`, `stroke`, `fill`, `transform`).

### 3. Surface-Specific Text Expansion Budgets
Because Indic translations expand character length by 15–35% relative to English:
- **Body prose (`text`, `worked_example`, `reveal`, `check.explanation`)**: Up to `1.50×` English character count (wraps naturally onto whole `--row` lines via `LessonKit`).
- **Card stems & titles (`lesson.title`, `sections[].title`, `check.question`, `simulation.title`, `reveal.title`)**: Up to `1.35×` English character count.
- **Simulation control labels (`simulation.spec.controls[].label`)**: Hard cap of **≤ 32 characters** (or ≤ 4 words including unit) so `<label class="zn-sim-control">` does not wrap onto 3 lines on a 360px phone viewport.
- **Diagram SVG `<text>` nodes (`diagram.spec.svg`)**: Only the text content inside `<text ...>...</text>` and the root `<svg aria-label="...">` may be translated; each `<text>` node's character count may not exceed `max(len(en_text) * 1.25, len(en_text) + 6)` characters to prevent bounding-box collision with adjacent SVG arrows/lines.

### 4. `DCR-001` Resolution — Per-Script Vertical Text Offset & Line-Box Rules on the 36px `--row` Grid
To ensure Indic scripts (`hi`, `ta`, `te`, `mr`, `bn`, `gu`, `kn`, `ml`, `pa`) render cleanly on the Field Notes 36px (`--row = 2.25rem`) ruled grid without clipping above-base matras (`ी`, `ै`, `ौ`) or below-base vowel signs (`ु`, `ू`, `ृ`) and without breaking `LessonKit.normalize()` (`frontend/assets/zivon.js`):
- **CSS Script-Scoped Font & Baseline Tokens (`DCR-001`)**:
  - When `<html lang="hi">` (or another Indic script code) is active, `zivon.css` sets script-specific font fallbacks (`--font-body-indic`, `--font-hand-indic`: Kalam for Devanagari titles/headings; system Noto Sans / Nirmala UI / Kohinoor / Latha / Tunga for body) and a CSS custom property `--script-baseline-nudge` (default `0px` for Latin `en`/`hi-Latn`, `-1.5px` for Devanagari `hi`/`mr`, `-2px` for stacked-conjunct scripts `te`/`kn`/`ml`, `-1px` for `ta`/`bn`/`gu`/`pa`).
  - `line-height: var(--row)` (`2.25rem = 36px` at `17px` / `1.0625rem` body font size) provides a `2.12×` line-height-to-font-size ratio, which exceeds the `1.85×` vertical extremum of Devanagari and Dravidian stacked conjuncts — **provided** `overflow: visible` is maintained on inline/block text containers and `LessonKit.normalize()` uses the active document language's `<p>` reference node (`ref: "p"`) plus `var(--script-baseline-nudge)` so the SVG ruled line sits `2px` below the subjoined matra zone rather than slicing through `ु`/`ू`.
  - Inline English/math spans inside Indic paragraphs (`<span lang="en">velocity</span>`) must set `line-height: 0` or `vertical-align: baseline` (`docs/frontend/design-doctrine.md` §10.3: *"Inline mixed-font spans must not grow the line box"*).

## Consequences

- **What gets easier**:
  - `factory/checks.py::rule_numbers` and `zivon.js::firstNumber` work on every language with zero changes to their number regexes.
  - Students can seamlessly ask the voice tutor doubts using either the English Physics term or the vernacular term because both appear on the page.
  - Deterministic checks in `10b-transcheck` can mechanically catch 100% of numeral transliterations, mutated SI units, Devanagari leaks in `hi-Latn`, and SVG attribute tampering before the LLM reviewer is even called.
- **What gets harder**:
  - The NCERT Physics glossary for Class 9–12 (~180 core terms) must be seeded and versioned (`glossary_version`) so `10a-translate` injects the relevant chapter terms consistently.
- **What we must monitor**:
  - `rule_trans_length_budget` hits on simulation control labels and SVG `<text>` nodes in `issues_ledger.jsonl`.
  - Visual baseline alignment on 360px Android WebView during the Phase 4 frontend pass (`07-perf` horizontal-overflow check across localized pages).

## Revisit trigger

- Revisit if a state board explicitly mandates native-script numerals in a future non-CBSE track: add a display-only numeral formatter in the renderer while keeping `data-answer` attributes and `spec` JSON values in Western Arabic numerals.

## References

- `docs/frontend/design-doctrine.md` (§10.2 Page grid, §10.3 Typography & Devanagari fallback, §10.5 Language bar, §10.7 Diagrams)
- `frontend/assets/zivon.js` (`firstNumber`, `LessonKit.normalize`, `ascentOf`, `lineOffset`)
- `factory/checks.py` (`rule_numbers`, `rule_answer_keys`, `rule_diagram_svg`)
- `skills/zivon-product-design-skills/skills/zivon-product-design/references/05-voice-translation-tts-ux.md` (§2.2–§2.3)
- `skills/zivon-product-design-skills/skills/zivon-product-design/references/07-zivon-tensions-to-resolve.md` (T2, T4, T8)
- `ADR-0009` (Language & locale model)
- `ADR-0013` (Build-time translation pipeline)
- `DCR-001` (Per-script vertical text offset note on the 36px `--row` grid)
