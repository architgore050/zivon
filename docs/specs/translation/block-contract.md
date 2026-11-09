# Per-Block Translation Contract (`10a-translate` & `10c-transrepair`)

- **Spec ID**: `SP2-TRANS` · `block-contract.md`
- **Governing ADRs**: `ADR-0013` (per-block Evon v3.3 translation via `llm_manager`), [`ADR-0017`](../../backend/adr/0017-translation-stage-placement-and-resumability.md), [`ADR-0018`](../../backend/adr/0018-translation-memory-and-cache-architecture.md), [`ADR-0019`](../../backend/adr/0019-physics-terminology-and-script-rendering-policy.md)
- **Enforcing Modules**: `factory/translate.py` (orchestration), `factory/schemas.py` (JSON Schemas), `factory/llm.py` (`LLMClient` adapter over `llm_manager`)

---

## 1. Design Principles of the Per-Block Contract

Following [`skills/prompting-and-agent-design/SKILL.md`](../../../skills/prompting-and-agent-design/SKILL.md):

1. **The Model Translates Strings; Code Owns Structure & Invariants**:
   - The LLM **never** receives or returns `citations`, `block.id`, `block.type`, `check.spec.answer_index`, `check.spec.format`, `numeric` check answers, `simulation.spec.controls[].min/max/step/initial`, or raw `<svg>` geometry.
   - Instead, `factory/translate.py` extracts a minimal **Translatable Payload** (`source_payload`) per unit, validates the model's **Translated Payload** (`translated_payload`) against a strict per-type JSON Schema (`additionalProperties: False`), and deterministically merges the translated strings back into a deep copy of the verified English block (`reassemble_translated_block`).
2. **All Calls Route Through `LLMClient` (`factory/llm.py`) → `llm_manager`**:
   - Zero hand-rolled HTTP calls (`AGENTS.md`).
   - Every per-block call uses `llm.call(stage_id="10a-translate", messages=..., schema=..., schema_name=..., extra_validator=..., round_tag=f"{locale}/{unit_id}")`, which automatically writes `attempts/<locale>/<unit_id>/attempt-NN/{request,response,meta}.json` and appends to `calls_ledger.jsonl`.
   - `LLMConfig` sets `max_tokens=4096` in code for the translator leg (`llm_manager/README.md` §Configuration) so a single block translation cannot ramble endlessly.

---

## 2. Prompt Context & Wire Request Envelope (`TRANSLATE_UNIT_PROMPT_CONTEXT`)

For each cache-missed `(locale, unit_id)` in `10a-translate`, `factory/translate.py` constructs a 2-message OpenAI chat-completions transcript (`system` + `user`) where the prompt context is structured as JSON inside the `user` message:

### 2.1 Logical Input Payload Assembled for the Prompt

```json
{
  "task": "translate_physics_unit",
  "target_locale": {
    "code": "hi",
    "autonym": "हिन्दी",
    "english_name": "Hindi",
    "script": "Deva",
    "script_rule": "Write natural Class 9-12 NCERT Hindi in Devanagari script. On the FIRST mention of any glossary Physics term in this unit, write '<Hindi Term> (<English Term>)', e.g. 'वेग (velocity)'. On later mentions in the same unit, write '<Hindi Term>' alone. Keep ALL Western Arabic numerals (0-9), SI units (m/s, m/s², kg, N, J), variable symbols (v, u, a, t, Δ), and equations character-for-character identical to the source."
  },
  "topic_context": {
    "chapter_title": "Motion in a Straight Line",
    "class_level": 11,
    "unit_id": "b-03",
    "unit_type": "worked_example"
  },
  "glossary_subset": [
    {
      "english_term": "velocity",
      "native_term": "वेग",
      "first_mention_gloss": "वेग (velocity)",
      "short_label": "वेग"
    },
    {
      "english_term": "acceleration",
      "native_term": "त्वरण",
      "first_mention_gloss": "त्वरण (acceleration)",
      "short_label": "त्वरण"
    },
    {
      "english_term": "stopping distance",
      "native_term": "अवरोधन दूरी",
      "first_mention_gloss": "अवरोधन दूरी (stopping distance)",
      "short_label": "अवरोधन दूरी"
    }
  ],
  "neighbour_context": {
    "previous_unit_translated_excerpt": "जब त्वरण (acceleration) नियत होता है, तो हम गति के तीन समीकरणों का उपयोग कर सकते हैं: v = u + at, s = ut + 1/2 at², और v² - u² = 2as।",
    "next_unit_source_excerpt": "What happens to the stopping distance if the initial speed of the car is doubled while braking deceleration remains constant?"
  },
  "immutable_numbers_in_problem": ["126", "200", "35", "3.06", "11.4"],
  "source_payload": {
    "problem": "A car moving along a straight highway with a speed of 126 km/h is brought to a stop within a distance of 200 m. What is the retardation of the car (assumed uniform), and how long does it take for the car to stop?",
    "steps": [
      {
        "title": "Convert initial speed to SI units",
        "detail": "Initial velocity u = 126 km/h = 126 × (5/18) m/s = 35 m/s. Final velocity v = 0 m/s, stopping distance s = 200 m."
      },
      {
        "title": "Find uniform acceleration using v² - u² = 2as",
        "detail": "0² - 35² = 2 × a × 200 → -1225 = 400a → a = -3.06 m/s² (retardation = 3.06 m/s²)."
      },
      {
        "title": "Find time taken using v = u + at",
        "detail": "0 = 35 + (-3.06) × t → t = 35 / 3.06 = 11.4 s."
      }
    ],
    "answer": "Retardation = 3.06 m/s², Time taken = 11.4 s"
  }
}
```

### 2.2 Locale-Specific `script_rule` Directives

| Locale | `script_rule` Injected into Prompt |
|---|---|
| `hi` (`Deva`) | Write natural Class 9–12 NCERT Hindi in Devanagari script. On the FIRST mention of a glossary Physics term in this unit, emit `<Hindi Term> (<English Term>)`, e.g., `वेग (velocity)`. Keep Western Arabic numerals (`0–9`), SI units (`m/s`, `m/s²`, `N`, `kg`), and equations untouched. Never use Devanagari digits (`०-९`). |
| `hi-Latn` (`Latn` Hinglish) | Write natural conversational Hinglish in **Latin (Roman) script only** — zero Devanagari characters (`[\u0900-\u097F]`). Keep technical Physics nouns in standard English spelling (`velocity`, `acceleration`, `displacement`, `force`, `momentum`), with Romanized Hindi gloss in parentheses on first definition where helpful (`velocity (veg)`), and write explanatory clauses in clear Roman Hindi (e.g., *"Yahan initial velocity u = 35 m/s hai"*). Keep all numerals (`0–9`), SI units, and equations verbatim. |
| `ta`, `te`, `mr`, `bn`, `gu`, `kn`, `ml`, `pa` | Write natural Class 9–12 state/NCERT textbook prose in the target native script (`Taml`, `Telu`, `Deva`, `Beng`, `Gujr`, `Knda`, `Mlym`, `Guru`). On FIRST mention of a glossary Physics term in this unit, emit `<Native Term> (<English Term>)`. Keep Western Arabic numerals (`0–9`), SI units, and equations character-for-character identical to the source. |

---

## 3. Per-Unit Request & Response JSON Schemas (`factory/schemas.py`)

Each unit type has a strict JSON Schema enforced by `llm_manager.validation.run_validation_rounds`. The model outputs **only** the `translated_payload` JSON object matching the unit's schema below.

### 3.1 Unit `b-00-meta` (Lesson Envelope + Simulation Runtime Strings)

#### Schema: `TRANSLATED_META_PAYLOAD`
```python
TRANSLATED_META_PAYLOAD = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["title", "objectives", "sections", "glossary", "sim_strings"],
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string", "minLength": 2},
        "objectives": {
            "type": "array",
            "minItems": 2,
            "items": {"type": "string", "minLength": 10},
        },
        "sections": {
            "type": "array",
            "minItems": 2,
            "items": {
                "type": "object",
                "required": ["id", "title", "paragraphs"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "pattern": "^sec-[0-9]{2}$"},
                    "title": {"type": "string", "minLength": 2},
                    "paragraphs": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "minLength": 20},
                    },
                },
            },
        },
        "glossary": {
            "type": "array",
            "minItems": 2,
            "items": {
                "type": "object",
                "required": ["term", "definition"],
                "additionalProperties": False,
                "properties": {
                    "term": {"type": "string", "minLength": 2},
                    "definition": {"type": "string", "minLength": 8},
                },
            },
        },
        "sim_strings": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "additionalProperties": {"type": "string"},
            },
            "description": "Map of simulation block_id -> {string_key: translated_label}.",
        },
    },
}
```

---

### 3.2 Block Type `text`

#### Source Payload Shape (`source_payload`)
```json
{
  "paragraphs": [
    "In physics, motion is a change in position of an object over time with respect to a reference point and a set of axes called a frame of reference.",
    "When an object moves along a straight line, we describe its position using a single coordinate axis (say, the x-axis)."
  ]
}
```

#### Response Schema (`TRANSLATED_TEXT_PAYLOAD`)
```python
TRANSLATED_TEXT_PAYLOAD = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["paragraphs"],
    "additionalProperties": False,
    "properties": {
        "paragraphs": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 10},
        }
    },
}
```
- **Code-side `extra_validator`**: `len(translated["paragraphs"]) == len(source["paragraphs"])`.

#### Example Response (`hi`)
```json
{
  "paragraphs": [
    "भौतिकी में, किसी निर्देश तंत्र (frame of reference) के सापेक्ष समय के साथ वस्तु की स्थिति (position) में होने वाले परिवर्तन को गति (motion) कहते हैं।",
    "जब कोई वस्तु एक सरल रेखा के अनुदिश गति करती है, तो हम उसकी स्थिति को एकल निर्देशांक अक्ष (जैसे x-axis) की सहायता से दर्शाते हैं।"
  ]
}
```

#### Example Response (`hi-Latn`)
```json
{
  "paragraphs": [
    "Physics mein, kisi frame of reference (nirdesh tantra) ke respect mein time ke saath object ki position mein hone wale change ko motion (gati) kehte hain.",
    "Jab koi object ek straight line ke along move karta hai, tab hum uski position ko ek single coordinate axis (jaise x-axis) se describe karte hain."
  ]
}
```

---

### 3.3 Block Type `worked_example`

#### Response Schema (`TRANSLATED_WORKED_EXAMPLE_PAYLOAD`)
```python
TRANSLATED_WORKED_EXAMPLE_PAYLOAD = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["problem", "steps", "answer"],
    "additionalProperties": False,
    "properties": {
        "problem": {"type": "string", "minLength": 10},
        "steps": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["title", "detail"],
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string", "minLength": 2},
                    "detail": {"type": "string", "minLength": 5},
                },
            },
        },
        "answer": {"type": "string", "minLength": 1},
    },
}
```
- **Code-side `extra_validator`**:
  1. `len(translated["steps"]) == len(source["steps"])`.
  2. Every numeral in `re.findall(r"\d+(?:\.\d+)?", source["problem"])` appears in `translated["problem"]` and vice-versa (`rule_numbers` invariant).
  3. Every numeral in `re.findall(r"\d+(?:\.\d+)?", source["answer"])` appears in `translated["answer"]`.

---

### 3.4 Block Type `check` (`mcq` and `numeric` Variants)

To make MCQ answer-key mismatches and numeric answer corruption **structurally impossible**:

#### Variant A: `check` with `format == "mcq"`

- **`source_payload` sent to model**:
  ```json
  {
    "question": "A ball is thrown vertically upwards with an initial velocity of 20 m/s. What is its velocity at the highest point of its trajectory?",
    "options": [
      "20 m/s upwards",
      "0 m/s",
      "9.8 m/s downwards",
      "10 m/s upwards"
    ],
    "explanation": "At the highest point, the ball momentarily stops before reversing direction, so its instantaneous velocity v = 0 m/s (even though acceleration due to gravity g = 9.8 m/s² downwards is non-zero).",
    "expected_understanding": "Distinguish between instantaneous velocity (zero at peak) and acceleration (constant g downwards)."
  }
  ```
- **Response Schema (`TRANSLATED_CHECK_MCQ_PAYLOAD`)**:
  ```python
  TRANSLATED_CHECK_MCQ_PAYLOAD = {
      "$schema": "http://json-schema.org/draft-07/schema#",
      "type": "object",
      "required": ["question", "options", "explanation", "expected_understanding"],
      "additionalProperties": False,
      "properties": {
          "question": {"type": "string", "minLength": 5},
          "options": {
              "type": "array",
              "minItems": 2,
              "items": {"type": "string", "minLength": 1},
          },
          "explanation": {"type": "string", "minLength": 5},
          "expected_understanding": {"type": "string", "minLength": 5},
      },
  }
  ```
- **Harness Reassembly (`reassemble_translated_block`)**:
  ```python
  spec_out = copy.deepcopy(source_block["spec"])
  spec_out["question"] = translated["question"]
  spec_out["options"] = translated["options"]
  # Deterministic lock: answer is ALWAYS options[answer_index]
  spec_out["answer"] = translated["options"][source_block["spec"]["answer_index"]]
  spec_out["explanation"] = translated["explanation"]
  spec_out["expected_understanding"] = translated["expected_understanding"]
  ```

#### Variant B: `check` with `format == "numeric"`

- **`source_payload` sent to model** (note: `answer` is omitted so the model cannot alter the numeric string!):
  ```json
  {
    "question": "A car accelerates uniformly from rest to 20 m/s in 5 s. Calculate its acceleration in m/s².",
    "explanation": "Using a = (v - u) / t = (20 - 0) / 5 = 4 m/s².",
    "expected_understanding": "Apply a = (v - u) / t with u = 0."
  }
  ```
- **Response Schema (`TRANSLATED_CHECK_NUMERIC_PAYLOAD`)**:
  ```python
  TRANSLATED_CHECK_NUMERIC_PAYLOAD = {
      "$schema": "http://json-schema.org/draft-07/schema#",
      "type": "object",
      "required": ["question", "explanation", "expected_understanding"],
      "additionalProperties": False,
      "properties": {
          "question": {"type": "string", "minLength": 5},
          "explanation": {"type": "string", "minLength": 5},
          "expected_understanding": {"type": "string", "minLength": 5},
      },
  }
  ```
- **Harness Reassembly**: Copies `spec_out["answer"] = source_block["spec"]["answer"]` (e.g. `"4"`) untouched.

---

### 3.5 Block Type `reveal`

#### Response Schema (`TRANSLATED_REVEAL_PAYLOAD`)
```python
TRANSLATED_REVEAL_PAYLOAD = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["title", "steps"],
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string", "minLength": 2},
        "steps": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["title", "detail"],
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string", "minLength": 2},
                    "detail": {"type": "string", "minLength": 5},
                },
            },
        },
    },
}
```
- **Code-side `extra_validator`**: `len(translated["steps"]) == len(source["steps"])`.

---

### 3.6 Block Type `diagram` (SVG String Extraction & Re-Injection Protocol)

Because raw `<svg>` geometry must never be mutated by a translator call (`docs/content-factory/blocks-schema.md`: no `<script>`, no `<style>`, exact viewBox and clean strokes), `factory/translate.py` isolates text strings from the SVG DOM:

1. **Extraction (`extract_diagram_payload(block)`)**:
   - Parse `block["spec"]["svg"]` with `xml.etree.ElementTree.fromstring`.
   - Extract root `aria-label` (if present) as `svg_aria_label`.
   - Walk all `<text>` and `<tspan>` elements in document order. Skip any node whose stripped text matches the pure-symbol/numeral regex `^[\d\s.,+\-−=×÷/()^₀-₉⁰-⁹a-zA-ZΔθωλμ°%]+$` when it is a standalone symbol/quantity token (e.g. `"F"`, `"10 N"`, `"m₁"`, `"v (m/s)"`, `"t (s)"`, `"0"`, `"O"`, `"A"`, `"B"`).
   - For each remaining descriptive `<text>` node (e.g. `"Slope = acceleration"`, `"Uniform motion"`, `"Area = displacement"`), emit an item into `svg_texts`:
     `{"id": "t-0", "source": "Slope = acceleration", "max_chars": 26}` where `max_chars = max(int(len(source) * 1.25), len(source) + 6)`.

#### Source Payload (`source_payload`)
```json
{
  "caption": "Free-body diagram of a block resting on a rough inclined plane of angle θ.",
  "svg_aria_label": "Block on inclined plane showing normal reaction N, friction f, and weight mg",
  "svg_texts": [
    {"id": "t-0", "source": "Normal reaction (N)", "max_chars": 25},
    {"id": "t-1", "source": "Static friction (f)", "max_chars": 25},
    {"id": "t-2", "source": "Weight (mg)", "max_chars": 17}
  ]
}
```

#### Response Schema (`TRANSLATED_DIAGRAM_PAYLOAD`)
```python
TRANSLATED_DIAGRAM_PAYLOAD = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["caption", "svg_aria_label", "svg_texts"],
    "additionalProperties": False,
    "properties": {
        "caption": {"type": "string", "minLength": 5},
        "svg_aria_label": {"type": "string"},
        "svg_texts": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "text"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "pattern": "^t-[0-9]+$"},
                    "text": {"type": "string", "minLength": 1},
                },
            },
        },
    },
}
```
2. **Re-injection (`reinject_diagram_svg(source_svg, translated_diagram_payload)`)**:
   - Verifies `[x["id"] for x in translated["svg_texts"]] == [x["id"] for x in source_payload["svg_texts"]]` and `len(x["text"]) <= source_item["max_chars"]`.
   - Replaces only `.text` on the corresponding `<text>` nodes (XML-escaped by ElementTree) and `aria-label` on `<svg>`, adds `data-i18n="<block_id>.svg_texts.<id>"` to each localized `<text>` node, serializes back to `<svg ...>...</svg>`, and runs `factory/checks.py::rule_diagram_svg` to guarantee zero security/lint regressions.

---

### 3.7 Block Type `simulation`

#### Source Payload (`source_payload`)
```json
{
  "title": "Velocity-Time Graph Explorer",
  "description": "Drag the initial velocity and acceleration sliders to see how the slope and the shaded area under the v-t line change.",
  "learning_goal": "Understand that the slope of a v-t graph equals acceleration and the area under the curve equals displacement.",
  "controls": [
    {"id": "u", "label": "Initial velocity u (m/s)"},
    {"id": "a", "label": "Acceleration a (m/s²)"}
  ],
  "default_behaviour": "Shows a straight line starting at u = 5 m/s with slope a = 2 m/s² over t = 0 to 10 s."
}
```

#### Response Schema (`TRANSLATED_SIMULATION_PAYLOAD`)
```python
TRANSLATED_SIMULATION_PAYLOAD = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": [
        "title",
        "description",
        "learning_goal",
        "controls",
        "default_behaviour",
    ],
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string", "minLength": 2},
        "description": {"type": "string", "minLength": 5},
        "learning_goal": {"type": "string", "minLength": 5},
        "controls": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "label"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "label": {"type": "string", "minLength": 1, "maxLength": 32},
                },
            },
        },
        "default_behaviour": {"type": "string", "minLength": 5},
    },
}
```
- **Code-side `extra_validator`**:
  1. `[c["id"] for c in translated["controls"]] == [c["id"] for c in source_payload["controls"]]`.
  2. Each `c["label"]` has `len(c["label"]) <= 32` (`ADR-0019` slider label budget).
- **Harness Reassembly**: Merges `translated["controls"][i]["label"]` into a copy of `source_block["spec"]["controls"][i]`, keeping `id`, `min`, `max`, `step`, and `initial` untouched.

---

## 4. On-Disk Checkpoint Envelope (`runs/<run_id>/10a-translate/blocks/<locale>/<unit_id>.json`)

Every completed unit translation is persisted on disk and in `sources/cache/tm/<locale>/<tm_key[:2]>/<tm_key>.json` using this canonical envelope:

```json
{
  "unit_id": "b-03",
  "unit_type": "worked_example",
  "locale": "hi",
  "source_content_sha256": "8f3c2a91e4b7d0192f45a61c88b310e74d921a0f5c63b8124e79d3015a6c9e12",
  "tm_key": "4a19d0c83b72f5610e94c82173b5a09d12f8e64c3091a7b5d82e410f6c39a2b1",
  "glossary_version": "1.0.0",
  "prompt_version": "1",
  "model_id": "evon-v3.3",
  "translation_source": "machine",
  "review_status": "machine_verified",
  "source_payload": { ... },
  "translated_payload": { ... },
  "reassembled_block": {
    "id": "b-03",
    "type": "worked_example",
    "citations": [{"claim_id": "claim-04"}],
    "spec": { ... }
  },
  "created_at": "2026-11-09T08:00:00Z"
}
```

---

## 5. `LLMClient` Invocation Pattern (`factory/translate.py`)

`factory/translate.py` calls `LLMClient` (`factory/llm.py`) without modifying `llm_manager/`:

```python
def translate_single_unit(
    cfg: Config,
    run_ctx: RunContext,
    llm: LLMClient,
    locale: str,
    unit_id: str,
    unit_type: str,
    source_block_or_meta: dict[str, Any],
    glossary_subset: list[dict[str, str]],
    neighbour_ctx: dict[str, str],
    round_tag_prefix: str = "init",
    repair_feedback: list[str] | None = None,
) -> dict[str, Any]:
    source_payload = extract_translatable_payload(unit_id, unit_type, source_block_or_meta)
    schema, schema_name = schema_for_unit(unit_id, unit_type, source_block_or_meta)
    messages = build_translate_messages(
        locale=locale,
        unit_id=unit_id,
        unit_type=unit_type,
        source_payload=source_payload,
        glossary_subset=glossary_subset,
        neighbour_ctx=neighbour_ctx,
        repair_feedback=repair_feedback,
    )

    def validate_invariants(candidate: dict[str, Any]) -> list[str]:
        return check_unit_deterministic_invariants(
            locale=locale,
            unit_id=unit_id,
            unit_type=unit_type,
            source_payload=source_payload,
            translated_payload=candidate,
            glossary_subset=glossary_subset,
        )

    round_tag = f"{locale}/{unit_id}" if round_tag_prefix == "init" else f"{locale}/{unit_id}/{round_tag_prefix}"
    translated_payload = llm.call(
        stage_id="10a-translate" if round_tag_prefix == "init" else "10c-transrepair",
        messages=messages,
        schema=schema,
        schema_name=schema_name,
        extra_validator=validate_invariants,
        round_tag=round_tag,
    )
    return reassemble_translated_unit(unit_id, unit_type, source_block_or_meta, translated_payload)
```
