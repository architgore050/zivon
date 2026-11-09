# India context, accessibility, performance and child data

## 1. Context facts that shape features  (from the repo; do not re-decide)

- Users: Class 9-12 students, CBSE/ICSE/state boards, often Hindi/Hinglish-first, many in Tier-2/3 cities, often on **low-end Android** (target: ~4 GB RAM), variable connectivity, shared phones, noisy homes.
- Budgets already set by the repo: page load < 2 s, animation ~60 fps, no jank on 4 GB phones; voice end-of-speech → first audio < ~4 s.
- Models: Prisma v2.5 (STT), Timbre v2.5 (TTS) mandatory in the voice loop; Evon v3.3 or Gate-A fallback for reasoning. Gnani credits are limited and metered - every live voice second has a cost; reserve ~40 % for demo/judge traffic.
- Out of scope per TIMELINE: mobile app, accounts/billing, full course platform, code sandbox, multi-user auth. (See tension T6: consent and personalization pressure this boundary.)

## 2. Accessibility baseline  (WCAG 2.2 AA is the target)  [STRONG as standard; criteria below not re-fetched this session - verify numbers against w3.org/TR/WCAG22 before quoting]

- Contrast ≥ 4.5:1 text (the doctrine already validates this); don't carry meaning by colour alone - **force/quantity arrows need shape/label cues too** (colour-blindness) even though colour is the strongest cue for novices.
- Keyboard: every control, including sim sliders and draggable objects, operable without a pointer. WCAG 2.2 adds a requirement that drag actions have a single-pointer alternative - **every draggable sim object needs a non-drag path** (arrow-key nudge, +/- buttons, typed value).
- Target size: WCAG 2.2 sets a 24×24 CSS px minimum; for children on cheap touchscreens design to ~44-48 px.
- Focus visible and not hidden behind sticky bars (lesson doctrine has a fixed language bar - check overlap).
- Reduced motion honoured (the runtime supports it): static start state + step-through.
- Screen readers: canvas has a text alternative that updates (state mirror); `aria-live` politeness chosen deliberately (don't interrupt the tutor's speech with a live-region flood).
- Captions/transcripts for all spoken output; no audio-only information.
- Language attributes per block (`lang`), important when mixing English terms into Hindi.
- Timeouts: no time-limited checks by default.

## 3. Performance as a feature requirement

Every feature card states its cost on: JS/CSS bytes, main-thread work per frame, network (and whether it works offline), battery (mic/audio loops), memory. Wrappers and add-ons **load lazily** and must not regress Core's budgets: translation loads only the chosen language; TTS audio is fetched on demand; the voice SDK loads on first mic tap, not at page load.
Data-saver is a first-class mode: no audio prefetch, lower sim frame rate cap optional, text-only tutor option.
Offline/poor network: define what works (read, simulate, previously fetched audio), what degrades (live tutor), and what the UI says.

## 4. Child data - product-side requirements  [STRONG as law; implementation needs counsel]

Secondary sources reviewed (dated Nov 2025-Jan 2026 summaries of India's DPDP Rules 2025, notified mid-Nov 2025):
- Verifiable parental/guardian consent is required before processing the personal data of anyone **under 18**; the method must be reliable and technology-neutral.
- Tracking, behavioural monitoring and targeted advertising directed at children are barred; limited purpose-based exemptions exist for certain bodies (e.g. educational institutions, for educational activities). **Whether Zivon qualifies is a legal question - do not assume it.**
- Most substantive duties (consent, safeguards, children's data, breach handling) apply about 18 months after notification, i.e. around **14 May 2027**; breach notices to the Board within 72 hours; responses to access/erasure requests within 90 days.
- Primary text: DPDP Act 2023 and DPDP Rules 2025 (MeitY, G.S.R. 846(E)). Read them, or have counsel read them, before turning any of the below into a hard requirement.

Implications to build into feature cards (as *flagged requirements*, not legal conclusions):
1. Anything that stores a child's voice, transcript, progress or inferred profile is a **consent-bearing feature**: show who consents, how, and what happens without consent (a useful default experience).
2. **Data minimization by default**: prefer not storing raw audio; store only what a feature needs, for as short as it needs. Decide the retention hint per information item.
3. **No behavioural profiling or engagement tracking of children** unless counsel clears a specific, purpose-limited exception. This directly limits "personalization" (see T5); prefer explicit settings and session-scoped adaptation.
4. Provide guardian-facing surfaces: consent status, what's collected, delete/export. Even if post-challenge, the data model must not preclude them.
5. Honest copy: say plainly that the tutor is an AI, that speech is processed by third-party models (Gnani) and what is kept.
6. Instrument learning events with pseudonymous identifiers; keep analytics free of free-text child speech.
7. No ads, no third-party trackers, no sale/sharing; third-party SDKs are a data-flow decision, not a convenience.

## 5. Safety of the tutor itself

Wrong physics is a harm. Features should expose provenance ("from page block 4"), allow "report a problem", and let the tutor say "I'm not sure - let's check the page". Off-topic and unsafe queries get a gentle, age-appropriate redirect. Distress signals need a defined, counsel-reviewed response.
