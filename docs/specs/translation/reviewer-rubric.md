# Translation Quality Gate, Reviewer Rubric & Repair Catcher (`10b-transcheck` & `10c-transrepair`)

- **Spec ID**: `SP2-TRANS` · `reviewer-rubric.md`
- **Governing Skill**: [`skills/prompting-and-agent-design/SKILL.md`](../../../skills/prompting-and-agent-design/SKILL.md) (4 control layers, calibrated reviewer rubrics, honest framing, `unverified:` escape hatch, progress-aware catchers)
- **Governing ADRs**: [`ADR-0017`](../../backend/adr/0017-translation-stage-placement-and-resumability.md), [`ADR-0018`](../../backend/adr/0018-translation-memory-and-cache-architecture.md), [`ADR-0019`](../../backend/adr/0019-physics-terminology-and-script-rendering-policy.md)

---

## 1. Architecture of the Translation Quality Gate

Per `skills/prompting-and-agent-design/SKILL.md` ("The four control layers — put every requirement in exactly one"):
- **Never ask an LLM judge to check what Python regexes and AST/DOM parsers can enforce 100% deterministically.**
- **Never let the translator model self-certify its own output**: `10b-transcheck` is an independent stage that combines **9 deterministic code rules** with **1 calibrated Evon v3.3 LLM-judge call per locale**, and routes any blocking (`fatal` or `major`) finding to the bounded **`10c-transrepair` catcher**.

```
10a-translate output (per locale)
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 10b-transcheck: Layer 1 — Deterministic Code Rules (factory/transcheck) │
│   R1: rule_trans_schema             R6: rule_trans_script_purity        │
│   R2: rule_trans_citations          R7: rule_trans_placeholders         │
│   R3: rule_trans_numbers            R8: rule_trans_svg_safety           │
│   R4: rule_trans_units_and_symbols  R9: rule_trans_length_budget        │
│   R5: rule_trans_mcq_integrity                                          │
└───────┬─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 10b-transcheck: Layer 2 — Calibrated Evon v3.3 LLM Judge (1 call/locale)│
│   Outputs {"issues": [...]} ONLY; harness computes verdict from         │
│   combined (model_issues + rule_issues) blocking count.                 │
└───────┬─────────────────────────────────────────────────────────────────┘
        │
        ├─► blocking_issues == [] ──► Write verified blocks to TM cache (sources/cache/tm/)
        │                             and proceed to 10d-transrender
        │
        └─► blocking_issues != [] ──► Route ONLY flagged (locale, unit_id) items
                                      to 10c-transrepair (progress-aware catcher)
```

---

## 2. Layer 1 — Deterministic Code Checks (`factory/transcheck.py`)

These 9 rules run both **inside `10a-translate`'s validation retry loop** (`extra_validator` in `LLMClient.call`) and **independently at `10b-transcheck`** on the full reassembled locale page:

| Rule ID | Function in `factory/transcheck.py` | What It Verifies Mechanically | Severity on Violation | Category Tag |
|---|---|---|---|---|
| `R1` | `rule_trans_schema` | Reassembled `blocks` validates against `factory/schemas.py::BLOCKS` and `meta` validates against `LESSON`; block count, `id` sequence (`b-01`..`b-NN`), and `type` sequence match English `1:1`. | `fatal` | `schema_integrity` |
| `R2` | `rule_trans_citations` | For every block `i`, `translated_block["citations"] == source_block["citations"]` (exact list equality; zero dropped or altered `claim_id`/`source_id` references). | `fatal` | `citation_loss` |
| `R3` | `rule_trans_numbers` | 1. Zero regional Unicode digits (`[\u0966-\u096F\u0BE6-\u0BEF\u0C66-\u0C6F\u09E6-\u09EF\u0AE6-\u0AEF\u0CE6-\u0CEF\u0D66-\u0D6F\u0A66-\u0A6F]`) anywhere in the translated unit.<br>2. For `worked_example.spec.problem`, `worked_example.spec.answer`, `check.spec.question`, and `check.spec.options[answer_index]`, the multiset of Western Arabic numerals (`re.findall(r"\d+(?:\.\d+)?", text)`) matches the English source field 100%. | `fatal` | `number_mismatch` |
| `R4` | `rule_trans_units_and_symbols` | Every equation (`ground_truth.equations[].expression` present in source block) and every SI unit token (`m/s`, `m/s²`, `m/s2`, `km/h`, `kg`, `N`, `J`, `W`, `Pa`, `Hz`, `Ω`) appearing in the source field is preserved in the translated field. | `fatal` | `unit_or_symbol` |
| `R5` | `rule_trans_mcq_integrity` | For `check` blocks: `format` and `answer_index` match English; for `mcq`, `len(options) == len(source_options)`, all options are distinct non-empty strings, and `spec["answer"] == spec["options"][spec["answer_index"]]`; for `numeric`, `spec["answer"] == source_spec["answer"]`. | `fatal` | `answer_key` |
| `R6` | `rule_trans_script_purity` | - For `hi-Latn`: zero Devanagari characters (`[\u0900-\u097F]`) (`fatal`).<br>- For Indic native-script locales (`hi`, `ta`, `te`, `mr`, `bn`, `gu`, `kn`, `ml`, `pa`): in `text`, `worked_example`, `reveal`, and `check.explanation` blocks, characters in the target Unicode script block must account for `>= 40%` of all alphabetic characters (excluding equations/units/parenthetical English glosses), catching untranslated English copy-pastes. | `fatal` | `script_violation` |
| `R7` | `rule_trans_placeholders` | Zero placeholder/truncation artifacts (`TODO`, `TBD`, `[TRANSLATE]`, `<translate>`, `{{`, `}}`, `undefined`, `null`, or trailing `...` when the source string does not end with `...`). For `sim_strings`, template placeholders (`{0}`, `{1}`, `{val}`) match the English template's placeholder set exactly. | `fatal` | `placeholder_leak` |
| `R8` | `rule_trans_svg_safety` | For `diagram` blocks: runs `factory/checks.py::rule_diagram_svg` (starts with `<svg`, no `<script>`, `<style>`, external URLs, `<image>`, `<foreignObject>`, `<use>`, or `on*=` handlers) AND verifies that the XML element tag sequence and all geometry attributes (`viewBox`, `d`, `x1`, `y1`, `x2`, `y2`, `cx`, `cy`, `r`, `points`, `transform`, `stroke`, `fill`) are byte-identical to the English `<svg>`. | `fatal` | `svg_integrity` |
| `R9` | `rule_trans_length_budget` | Enforces `ADR-0019` expansion budgets:<br>- `simulation.spec.controls[].label`: `len <= 32` chars (`major` if `33..40`, `fatal` if `> 40`).<br>- `diagram` `svg_texts[].text`: `len <= max(int(len(en) * 1.25), len(en) + 6)` (`major`).<br>- Card titles/headers: `len <= int(len(en) * 1.35) + 10` (`minor`). | `fatal` / `major` / `minor` | `length_budget` |

---

## 3. Layer 2 — Calibrated LLM Translation Reviewer (`10b-transcheck`)

### 3.1 Reviewer Output Schema (`TRANSLATION_REVIEW_CALL_REPORT`)

Following the 2026-11-08 `09-review` split in `factory/schemas.py:320`, the LLM reviewer outputs **issues only**; harness code computes the `pass`/`fail` verdict so verdict logic is a code guarantee, never prompt prose:

```python
TRANSLATION_REVIEW_CATEGORIES = [
    "physics_meaning",      # Translation alters or inverts a physical law, condition, or causal direction
    "glossary_term",        # Wrong physics term used, or missing required first-mention bilingual gloss
    "untranslated_leak",    # English clauses/sentences left untranslated in native-script locale (or vice versa)
    "hallucinated_content", # Translator added claims, steps, or examples not present in the English block
    "grade_register",       # Overly archaic/unnatural phrasing that a Class 9-12 Indian student cannot follow
    "awkward_phrasing",     # Minor grammar/gender/postposition stiffness that does not hurt physics accuracy
]

TRANSLATION_REVIEW_CALL_REPORT = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["issues"],
    "additionalProperties": False,
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["block_id", "severity", "category", "message"],
                "additionalProperties": False,
                "properties": {
                    "block_id": {
                        "type": "string",
                        "pattern": "^(b-00-meta|b-[0-9]{2})$",
                    },
                    "severity": {"enum": ["fatal", "major", "minor"]},
                    "category": {"enum": TRANSLATION_REVIEW_CATEGORIES},
                    "message": {"type": "string", "minLength": 15},
                },
            },
        }
    },
}
```

### 3.2 Calibrated Severity Ladder & Judge Escape Hatch

| Severity | Definition | Blocks Publish? | Required Evidence in `message` |
|---|---|---|---|
| **`fatal`** | **Physics meaning corruption or broken pedagogy**:<br>1. Reverses or distorts a physical relationship (e.g., translating *"velocity decreases while acceleration is constant"* as *"acceleration decreases"* or confusing *distance (दूरी)* with *displacement (विस्थापन)*, or *speed (चाल)* with *velocity (वेग)*).<br>2. Alters the meaning of an MCQ option so the correct option at `answer_index` is no longer physically true, or makes a distractor equally correct.<br>3. Drops a step, condition (`"assuming uniform acceleration"`), or negation (`"not"`, `"zero"`). | **Yes** (routes to `10c-transrepair`) | Must quote both the exact English phrase and the mistranslated target-locale phrase, and state the physical error. |
| **`major`** | **Terminology policy or comprehension barrier**:<br>1. Violates the `ADR-0019` bilingual first-mention gloss rule on a core chapter glossary term (e.g., omits `(acceleration)` on first mention of `त्वरण`, or uses an incorrect non-NCERT vernacular term).<br>2. Leaves a full clause or sentence in untranslated English inside a native-script locale (beyond allowed technical terms).<br>3. Adds unrequested explanations or examples not present in the English source block. | **Yes** (routes to `10c-transrepair`) | Must name the `block_id`, field path, expected glossary term, and what appeared instead. |
| **`minor`** | **Stylistic polish or unverifiable suspicion**:<br>1. Slightly stiff word order or synonym choice where the physics meaning and NCERT term are completely clear.<br>2. Any suspicion the reviewer is not 100% certain of must be prefixed with `unverified:` and marked `minor` (harness code automatically downgrades any `fatal`/`major` whose message starts with `unverified:` to `minor`). | **No** (logged to `issues_ledger.jsonl`, rides along) | Brief note. |

### 3.3 Reviewer Prompt Template (`factory/transcheck.py`)

Structured per `skills/prompting-and-agent-design/SKILL.md` (long context at top, goal + calibrated rubric + output contract at bottom, honest framing — never *"assume there is at least one defect"*):

```text
SYSTEM:
You are the Physics Translation Reviewer for Zivon (Class 9-12 NCERT Physics).
Your job is to verify that a localized lesson faithfully preserves the exact physics meaning, NCERT terminology, and learner clarity of the verified English source blocks.

USER:
=== TARGET LOCALE & POLICY ===
Locale: {locale} ({autonym} / {english_name}, script: {script})
Policy: {script_rule}

=== CHAPTER GLOSSARY (CANONICAL TERMS) ===
{glossary_json}

=== SOURCE (ENGLISH) vs TRANSLATED ({locale}) UNITS ===
{paired_units_json}

=== REVIEW GOAL & RUBRIC ===
Inspect each unit pair (b-00-meta and b-01..b-NN) once in order.
Hunt for REAL physics translation errors. If the translation is faithful, accurate, and clear for a Class {class_level} learner, return an empty issues array: {"issues": []}.

Report an issue ONLY when you can cite the exact English text and the exact translated text:
- "fatal": Distorts or inverts physics meaning (e.g. confuses speed/velocity or distance/displacement, drops a condition like "uniform" or "at rest", drops a negation, or makes the correct MCQ option physically wrong).
- "major": Uses the wrong physics term instead of the Chapter Glossary term, omits the required first-mention bilingual gloss "<Native Term> (<English Term>)" on a core glossary term, leaves an English sentence untranslated, or hallucinates extra claims not in the English block.
- "minor": Minor phrasing stiffness that does not mislead the learner. If you are uncertain about a regional nuance, prefix the message with "unverified:" and use severity "minor".

Do NOT flag Western Arabic numerals (0-9), SI units (m/s, m/s², N, kg, J), or Latin variable symbols (v, u, a, t, F) — keeping those in standard international form is mandatory policy.

Return ONLY a JSON object matching the schema:
{"issues": [{"block_id": "b-03", "severity": "fatal"|"major"|"minor", "category": "physics_meaning"|"glossary_term"|"untranslated_leak"|"hallucinated_content"|"grade_register"|"awkward_phrasing", "message": "..."}]}
```

---

## 4. Layer 3 — Bounded Progress-Aware Repair Catcher (`10c-transrepair`)

When `10b-transcheck` produces one or more blocking issues (`severity in ("fatal", "major")` from either deterministic rules `R1`–`R9` or the LLM reviewer):

1. **Block-Scoped Isolation (Never Re-Translate Passing Blocks)**:
   - `10c-transrepair` groups blocking issues by `(locale, block_id)`.
   - Any unit `b-XX` with **zero** blocking issues in `10b-transcheck` is immediately marked verified, written to the persistent Translation Memory (`sources/cache/tm/<locale>/<tm_key[:2]>/<tm_key>.json`), and locked — it is **never** re-translated during repair rounds.
2. **Progress-Aware Loop (`factory/stages.py` Pattern)**:
   - Uses the exact same progress metric as `04-repair` and `10-reviewfix`:
     `score = sum(2 if i["severity"] == "fatal" else 1 for i in blocking_issues)`
   - Loop bounds:
     - `max_rounds = cfg.repair["translation_rounds"]` (default `6`, configurable `1..20`).
     - `stall_limit = cfg.repair["stall_rounds"]` (default `3`, configurable `1..10`).
   - In each round `r = 1..max_rounds`:
     1. For each flagged `block_id`, call `translate_single_unit(..., round_tag_prefix=f"repair-r{r:02d}", repair_feedback=block_issues)` passing:
        - The original English `source_payload`.
        - The rejected `translated_payload` from the previous round.
        - The exact list of `fatal`/`major` issue messages for that `block_id` ("Fix ONLY these violations while keeping valid translated sentences intact").
     2. Merge the repaired units into the locale's draft and atomically update `runs/<run_id>/10a-translate/blocks/<locale>/<block_id>.json`.
     3. Re-run `10b-transcheck` deterministic rules on the full locale page and re-run the `10b-transcheck` LLM reviewer **only on the repaired `block_id`s** (plus their 1-block neighbour context), merging the updated issues list.
     4. Compute `new_score`. If `new_score < best_score`, set `best_score = new_score` and `stalls = 0`; else `stalls += 1`.
3. **Terminal Failure vs Partial Fallback**:
   - If `blocking_issues == []`: write newly repaired blocks to `sources/cache/tm/`, mark `10c-transrepair` and `10b-transcheck` `"ok"`, and proceed to `10d-transrender`.
   - If `blocking_issues` remain after `rounds == max_rounds` or `stalls == stall_limit`:
     - If `locale in cfg.translation.optional_locales`: mark only the still-failing `block_id`(s) as `status = "fallback_en"` (rendered in English with `.zn-untranslated-notice` per `spec.md` §8.1 `FM-TRN-03`), log the unresolved issues to `issues_ledger.jsonl`, and proceed to `10d-transrender`.
     - Otherwise (required P0 locale `hi` or `hi-Latn`): raise `StageError("10b-transcheck", ...)` with the full repair history and resume hint. Because all passing blocks are already saved in `runs/<run_id>/10a-translate/blocks/<locale>/` and `sources/cache/tm/`, re-triggering the run resumes directly at the remaining broken block(s) with a fresh repair budget.
