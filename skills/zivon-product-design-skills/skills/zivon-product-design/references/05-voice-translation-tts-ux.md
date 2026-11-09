# Voice agent, translation and TTS - interaction design

Everything here is a **hypothesis library** to be filtered by `02`, not a spec.
Evidence for voice-UI practice is practitioner-grade `[WEAK-MODERATE]`; the PhET and
Mayer implications carry the stronger evidence.

## 1. Voice agent

### 1.1 State machine to design every state of

`idle` → `requesting-permission` → `ready` → `listening` (user speaking) → `endpointing` → `thinking` → `speaking` → (`interrupted` → `listening`) → `ready` / `ended`; error branches: `no-input`, `no-match` (low-confidence transcript), `system-error`, `offline`, `quota-exhausted`, `mic-denied`, `mic-in-use`, `unsupported-browser`.
Each state needs: visual, audible cue (earcon), accessible announcement, copy keys (per language), exits, and the events it emits. A state without an exit is a bug.

### 1.2 Decisions to make explicitly

| Topic | Options / questions |
|---|---|
| Activation | Push-to-talk, tap-to-toggle, hands-free with voice activity detection. Kids in noisy rooms: which default? What does the UI do on false triggers? |
| Anchoring | What context does the tutor receive (current block, simulation variable values, last check result, language)? How is that shown to the student (anchor chip)? Can the student re-anchor ("ask about this paragraph/sim")? |
| Transcript | Live partial transcript? Final transcript editable before sending? Visible tutor text alongside speech (see tension T1)? |
| Barge-in | Student speech or tap stops the tutor immediately. Does the tutor resume, restart or drop? |
| Agency over the page | May the tutor highlight, scroll, set a slider, pause a sim, open a reveal? Each action must be visible, undoable, and narrated (honesty, user control). |
| Pedagogy | Socratic default? When does it just answer? How many hints before telling? How does it detect misconception vs typo? Does it ask the student to speak the answer before revealing? |
| Language | Mirrors the student's language; may switch mid-session; handles code-mixing; how is a spoken language change confirmed? |
| Limits | Session length, daily credit/budget, per-question length; what the UI says as limits approach (never a surprise cut-off). |
| Safety | Off-topic or unsafe prompts → age-appropriate redirect; no personal-data solicitation; clear "I'm an AI" identity; escalation for distress (design with counsel). |
| End of session | Summary: what was covered, one thing to try next, optional save; deletion controls. |
| Fallbacks | Text input when mic unavailable; read-only transcript; "try again" without losing context; offline message that preserves the lesson. |

### 1.3 Latency as UX
Target from the repo (Gate C): < ~4 s from end-of-speech to first spoken audio. Design what the student sees/hears at 0-300 ms (acknowledge), 300 ms-2 s (thinking), 2-4 s (still working, earcon/short filler), and > 4 s (apology + retry/typed option). Streaming means partial text can appear before audio; decide whether it may.

## 2. Translation (wrapper)

### 2.1 Scope decisions
Surfaces: UI chrome · lesson text · sim labels and units · diagram captions/alt · check questions/options/feedback · glosses · errors · tutor speech · student speech (recognition language) · TTS voice · metadata/page title.
For each surface: translated at **build time** (content factory, reviewable, cacheable, glossary-controlled) or **runtime** (machine, fresh but unreviewed, costs tokens/latency)? Record the trade-off. `[ASSUMPTION: build-time for lesson content, runtime only for tutor speech - validate]`

### 2.2 Behaviour decisions
- Language list and display: show each language in its own script (autonym), not only in English.
- Where chosen/remembered; whether the choice is per-device, per-profile, per-lesson; how a guardian sees it.
- **Hinglish**: decide whether it is (a) a UI language, (b) a spoken style of the tutor only, or (c) both. Note Hinglish has no single orthography (Roman vs Devanagari).
- Mixed content: keep the English physics term (the board-exam term) with a gloss in the learner's language; show both on first mention.
- Never translate: SI units, symbols (v, a, F, Δ), equations; do localize numerals only if the audience expects it (decide per language) and keep them consistent between text, sim readouts and TTS.
- Text expansion: Hindi/Tamil/Telugu strings are often longer than English; control labels have a hard budget (PhET: 1-3 words). Allocate pixel budget per label.
- Fallbacks: when a block lacks a translation, show English *and say so*; never mix silently. Indicate machine-translated vs reviewed content (honesty).
- Fonts: the repo's lesson doctrine specifies Courier Prime/Caveat/Kalam; check Indic script coverage and define fallbacks (see `07`, T4).
- RTL (e.g. Urdu): in or out of scope? State it.
- The language bar in the lesson doctrine is "fixed"; decide how it behaves with ≥5 languages.

### 2.3 Quality and risk
Physics terminology errors are a **correctness** risk, not a cosmetic one. Require a glossary, a reviewer step, and a visible "report a translation problem" path. Gate each language's launch on a review rate, not on availability of an LLM.

## 3. Text-to-speech (wrapper)

### 3.1 Scope decisions
What can be spoken: lesson text, worked-example steps, check questions and feedback, sim state narration, glosses, UI announcements, tutor replies.
Two very different sources:
1. **Static narration** of lesson content - deterministic, repeatable, same for every student in a language. → can be **pre-generated, stored and cached** (cost and latency win; no per-student credit burn). Specify per-block narration text (may differ from on-screen text - symbols and units need spoken forms).
2. **Live tutor speech** - generated per turn, streaming.
Decide the boundary and say what the student sees when audio is loading, missing or fails.

### 3.2 Controls and behaviour
Play/pause/stop; speed (0.75×-1.5×); seek by sentence/paragraph; highlight-follow; auto-advance or not; autoplay (browsers block it; and it is obtrusive - default off); remember settings; keyboard shortcuts; headphone vs speaker hint; audio focus (page audio pauses when the student speaks to the tutor and vice-versa); data-saver (don't prefetch audio); offline availability; volume/duck; captions on request.
Pronunciation: units ("metres per second squared"), symbols, scientific notation, Indian number formatting, mixed-language terms, formulas read in a learner-friendly order. Provide a per-term pronunciation override list.

### 3.3 Redundancy and accessibility
See tension T1. TTS is an accessibility feature (low literacy, visual impairment, language learners) *and* a Mayer-modality feature; design for both without forcing text+audio duplication on everyone.

## 4. Personalization

Define the smallest personalization that visibly helps: language, pace of speech, depth (hint-first vs explain-first), which topics to revisit, example themes. Distinguish **explicit** (student/guardian chooses) from **inferred** (system learns). Inference about a child's behaviour is the legally sensitive part (see `06`). Whatever is personalized must be: visible ("what the tutor knows"), editable, resettable, explainable ("why am I seeing this"), and absent-safe (the default experience is good). Start explicit-only; add inference only with a decision recorded and legal sign-off.
