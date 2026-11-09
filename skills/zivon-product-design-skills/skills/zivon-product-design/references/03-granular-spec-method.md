# Granular specification method - from feature to element to API

The user's standard: **every single element or piece of information the frontend
displays is mapped**, and each maps to a feature and to the backend capability that
supplies it. This file defines the artifacts, the ID scheme, and the completeness protocol.

## 1. ID scheme (stable, never reused)

| Thing | Pattern | Example |
|---|---|---|
| Feature | `F-<LAYER>-<AREA>-<NN>` | `F-ADD-VOI-04` |
| Screen / surface | `SCR-<AREA>-<NN>` | `SCR-LES-01` |
| Region | `<SCR>.R<n>` | `SCR-LES-01.R3` |
| UI element | `EL-<SCR>-<NNN>` | `EL-LES-01-014` |
| Information item | `INF-<NNN>` | `INF-032` |
| Copy key (i18n) | `<screen>.<element>.<state>` | `lesson.sim.reset.label` |
| API need (placeholder until the systems agent names it) | `NEED-<NNN>` | `NEED-017` |
| Entity need | `ENT?-<name>` | `ENT?-Session` |
| Analytics event | `EVT-<verb_noun>` | `EVT-sim_control_changed` |
| Decision-log candidate | `cand-<NNN>` | `cand-044` |

## 2. The five artifacts

1. **Feature card** - `templates/feature-card.md`. Why, for whom, how it behaves, how we know it works.
2. **Screen & region list** - every screen/surface, its entry conditions, its regions, layer(s) present. Include non-page surfaces: permission dialogs, toasts, the mic overlay, audio-only states, the consent flow, the admin views.
3. **UI element inventory** - `templates/ui-element-inventory.csv`. One row per *perceivable element per state family*. Columns explained in section 4.
4. **Information inventory** - `templates/information-inventory.csv`. One row per *datum* (a value or string whose content comes from data rather than static copy). Columns in section 5.
5. **Screen-state matrix** - `templates/screen-state-matrix.md`. Rows = screens/regions, columns = states. No blank cells; write "n/a (reason)" if truly impossible.

Then the **traceability matrix** (`templates/traceability-matrix.csv`) joins them all.

## 3. Completeness protocol - how to be sure nothing is missing

Walk each screen **top-left → bottom-right, in every state**, and for each of the
following "forgotten element" classes ask "is there a row?":

- Page title, `lang` attribute, meta/share text, favicon, document language fallback
- Navigation, breadcrumbs, back, progress indicators ("block 3 of 9")
- Headings, paragraphs, formulas (and their spoken form), units, symbols, numerals
- Images/diagrams: alt text, caption, long description, colour-key/legend
- Sim: canvas, each control + its label + its value readout + its units, reset, pause/step/speed, tools (ruler, stopwatch), trace toggle, "what changed" annotation, error painter, loading skeleton, accessible text mirror of the sim state
- Check: question, options, submit, correct/incorrect feedback, explanation, hint(s), retry, attempt count, skip
- Reveal/worked-example steps, expand/collapse affordances
- Language: selector, current-language indicator, "this block isn't translated" notice, machine-translation disclosure
- TTS: play/pause/stop, speed, voice, progress, highlight, "loading audio", "audio unavailable", data-saver warning
- Voice agent: mic button, permission prompt (browser-native + our pre-explanation), listening/thinking/speaking indicators, waveform, live transcript, final transcript, tutor text, anchor chip, interrupt, mute, end session, typed-input fallback, error/retry, "I didn't catch that", quota notices, session summary
- Personalization: "what the tutor knows" view, edit/reset, level/pace settings, opt-in explanation
- Consent & privacy: age gate, parent consent screens/status, privacy notice, data deletion request
- System feedback: toasts, snackbars, offline banner, update-available, reconnecting, rate-limit message, maintenance
- Non-visual: earcons, haptics, `aria-live` announcements, focus order and focus restoration, keyboard shortcuts
- Staff/admin (if in scope): content release state, run/test status, credit usage, error counts - each number is an information item

If a thing is perceivable (seen, heard, felt, announced), it gets a row.

## 4. UI element inventory - column meanings

`element_id` · `screen_id` · `region` · `feature_id` · `element_type` (text, label, button, toggle, slider, select, canvas, audio-control, badge, toast, dialog, earcon, aria-live, link, image, input) · `content_source` (static copy key | `INF-xxx` | derived expression) · `states` (list from: default, hover, focus, active, disabled, loading, empty, partial, error, offline, success, reduced-motion, untranslated) · `visible_when` (precise condition) · `interaction` (gesture/key → effect) · `emits_event` (`EVT-…`) · `needs_api` (`NEED-…`, or "none - client only") · `reads_entity` (`ENT?-….field`) · `i18n` (translate | transliterate | never; max expansion %) · `tts` (spoken? exact spoken text; order; interrupts?) · `a11y` (role, accessible name, keyboard, focus order, live-region politeness) · `perf_budget` (e.g. "≤1 frame of work", "≤30 KB") · `privacy_class` (none | pseudonymous | personal | child-voice) · `priority` (P0/P1/P2, from repo ladder) · `notes`.

## 5. Information inventory - column meanings

`info_id` · `name` · `description` · `shown_in` (element ids) · `source` (`ENT?-x.field` | computed from … | static) · `type_format` (string, int, ISO date, duration, locale number…) · `units_and_symbols` (SI; never translated) · `nullability_and_fallback` (what shows if absent) · `freshness` (static | per-lesson-version | per-session | live) · `localization_rule` (translate | transliterate | numerals per locale | keep English term + gloss | never) · `pii_class` · `retention_hint` (session | days | account-life | content-life; the systems agent decides the tier) · `visible_to` (student | guardian | staff).

## 6. Writing a good feature card (quality bar)

- **One sentence** a Class-9 student's parent would understand.
- **Job + moment + metric** are named, with the metric's event(s).
- **Principles applied** - 2-4, each with how it shaped a decision, not a name-drop.
- **Behaviour** in numbered, testable statements, ideally EARS ("When the student releases the mic button, the system shall…"). Use `feature-forge`'s EARS reference.
- **Acceptance criteria** (Given/When/Then) incl. at least one unhappy path and one a11y criterion and one low-end-device criterion.
- **States** table; **copy keys**; **elements** (ids); **info items** (ids); **backend needs** (as capability sentences: "retrieve the lesson bundle for topic T in language L at version V"); **entities**; **events**; **cost/credit impact**; **privacy class**; **dependencies**; **cut-line**; **open questions**.
- A backend need is stated as a *capability and its data shape*, not as an endpoint. Naming endpoints is the systems agent's job; you hand over needs.

## 7. Backend handoff list (end of Phase 7)

Produce, as its own section, the consolidated, de-duplicated lists the systems agent consumes:
1. **Capability needs** (`NEED-…`): purpose, caller (which element/feature), request shape, response shape, latency expectation, freshness, auth/consent requirement, failure behaviour the UI expects.
2. **Entity needs** (`ENT?-…`): fields implied by the information inventory, with types and nullability.
3. **Realtime needs**: streaming channels the voice agent / TTS require, message types, ordering and interruption semantics.
4. **Event catalogue**: every `EVT-…` with properties, trigger, and privacy class.
5. **Data volume hints**: expected size per item (audio seconds, transcript length, lesson bundle KB) and expected counts, so storage can be tiered.
6. **Retention and consent hints**: what the product *wants* to keep and why; the systems agent reconciles with law and cost.

## 8. Orphan checks (run before finishing)

- Every `EL-` has a `feature_id` that exists. Every feature has ≥1 element or is marked "no UI (backend only)".
- Every `INF-` is shown somewhere (`shown_in` non-empty) and has a source.
- Every `NEED-` is requested by ≥1 element or feature; every element with `needs_api` points at an existing need.
- Every `EVT-` is emitted by ≥1 element/feature and consumed by ≥1 metric.
- Every copy key used appears once in the copy table; no element has hard-coded text.
