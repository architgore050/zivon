# Known tensions the author must resolve explicitly

Each is a real conflict between a principle, a repo constraint, and the new feature
set. Do not paper over them: write a short decision (options considered, choice, reason,
evidence tag) in the final doc. `Lean` is our starting guess, not a decision.

| ID | Tension | Why it matters | Options | Lean | Decider |
|---|---|---|---|---|---|
| T1 | **Mayer redundancy/modality vs TTS + on-screen text** | Narration + graphics beats narration + graphics + the same text, but captions help the deaf/hard-of-hearing, language learners, noisy rooms, and silent-phone use | (a) audio only; (b) audio + synced highlight on request; (c) always both | Default narration with visuals and *short labels only*; full captions/transcript on a toggle; remember per user | Product author, validate with kid test |
| T2 | **Language model of the product**: "Hinglish" as language vs style; fixed language bar vs ≥5 languages | Affects data model, content factory, TTS voice choice, STT language hints | Language list with autonyms + a "mixed explanation" style flag | Treat Hinglish as a *tutor speech style* plus a UI language option; decide orthography | Product author + founder |
| T3 | **Voice-first vs noisy/shared environments** | False triggers, other speakers, children's privacy | Push-to-talk default; hands-free opt-in | Push-to-talk default for children | Author |
| T4 | **Doctrine fonts vs Indic script coverage** | `docs/frontend/design-doctrine.md` names Courier Prime body and handwriting accents; Indic coverage may be missing | Fallback stack per script; adapt the 36 px rhythm; propose a Doc Change | Raise a **Doc Change Proposal**; never ship tofu boxes | Founder (doctrine owner) |
| T5 | **Personalization vs child-data law** | Behavioural monitoring/profiling of children is restricted; exemptions are narrow | Explicit-only personalization; session-scoped adaptation; guardian-consented memory; none | Explicit + session-scoped now; persistent inferred profile deferred pending counsel | Founder + counsel |
| T6 | **Identity vs "accounts out of scope"** | Consent, memory, cross-device language, and progress all want an identity; TIMELINE says no accounts/multi-user auth | Anonymous device-scoped profile + guardian link later; magic-link guardian; accounts post-challenge | Anonymous device profile now; model it so a guardian account can attach later | Founder |
| T7 | **Tutor controls the page vs user control/honesty** | Tutor setting a slider is powerful and surprising | Tutor may *highlight* only; may *set* with visible undo and narration | Highlight + suggest first; set-with-undo as P1/P2 | Author |
| T8 | **Build-time vs runtime translation and narration** | Cost, review, latency, schema changes | Build-time reviewed (lesson) + runtime (tutor) | As lean; list required content-factory/schema additions | Author + content-factory owner |
| T9 | **Socratic vs "just tell me"** (exam eve) | Pedagogy vs frustration | Mode toggle "Guide me / Tell me" with defaults by context | Socratic default, one tap to "explain directly" | Author |
| T10 | **New features vs the freeze and deadline** | Gate D (feature freeze) was Day 8; deadline 10 Nov 2026 11:59 PM IST | Tag every feature P0/P1/P2/post-challenge; keep P0 identical to the repo ladder | Do not expand P0; this document is the post-challenge roadmap unless the founder says otherwise | Founder |
| T11 | **Raw audio retention** | Child voice is sensitive; useful for debugging/quality | No raw audio by default; opt-in short-lived debug capture; transcripts only | No raw audio | Founder + counsel |
| T12 | **Correctness of AI speech** | Wrong physics hurts a learner | Provenance chip, "report", confidence-aware phrasing, anchor-only answers for on-page questions | Anchor + provenance | Author |

When you resolve a tension, record: the decision, the alternative rejected, the principle(s) that decided it, how we will know if it was wrong (a metric or a test), and whether it needs an ADR (systems-impacting) or a Doc Change Proposal (repo-doc-impacting).
