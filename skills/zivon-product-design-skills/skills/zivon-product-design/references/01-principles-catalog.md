# Principles catalog

Pick the few that matter (Phase 1). Do not paste this whole file into the deliverable.
A principle earns a place in the "Principles applied" brief only if you can write
(a) a concrete UI/behaviour consequence and (b) a test. Wording below is paraphrased;
follow the links in `sources-and-evidence.md` for the originals.

Contents: A Rams · B Nielsen · C Norman (canonical) · D Mayer · E PhET · F Physics-education research · G Voice/conversation · H Children and honesty

## A. Dieter Rams - ten principles of good design  [WEAK as science, STRONG as craft doctrine]

Rams's list: innovative, useful, aesthetic, understandable, unobtrusive, honest,
long-lasting, thorough down to the last detail, environmentally friendly, as little
design as possible. (Shareable accurately under CC BY-NC-ND 4.0 - credit Vitsœ.)

| Principle | What it means for Zivon | Test |
|---|---|---|
| Useful | A feature exists only if it moves a student toward understanding or removes friction to it. Delight that doesn't serve learning is cut. | Decision-log row names the job it serves |
| Understandable | The product explains itself: a sim's controls are self-evident, the mic states are legible without text. | First-time student acts correctly with no help (PhET "intuitive" level) |
| Unobtrusive | The tutor and the wrappers are tools, not performers. Nothing autoplays over a student's thinking; the sim starts still. | No unrequested audio/motion on load |
| Honest | Say when a translation is machine-made, when the tutor is unsure, when a feature is unavailable. No fake "typing", no inflated progress, no promises the model can't keep. | Every limitation has visible, plain-language copy |
| Thorough to the last detail | Empty, error, offline, untranslated states are designed. Units, symbols, numerals are consistent. | State matrix has no blank cell |
| As little design as possible | Fewer controls, fewer screens, fewer words. Remove until it hurts, then restore one thing. | Removal test in the decision log |
| Long-lasting | Content is versioned and durable; no trend-chasing UI; don't depend on a vendor feature that may vanish. | Content survives a model/vendor swap |
| Innovative | Spend novelty only where it pays: simulation + voice anchoring. Be conventional everywhere else. | Novelty budget stated per feature |

## B. Nielsen's ten usability heuristics  [STRONG - 1994 factor analysis, stable since]

Visibility of system status · match between system and real world · user control and
freedom · consistency and standards · error prevention · recognition over recall ·
flexibility and efficiency · aesthetic and minimalist design · help users recognize,
diagnose and recover from errors · help and documentation.

| Heuristic | Zivon application |
|---|---|
| Visibility of status | Mic state (idle/listening/thinking/speaking) always visible *and* audible (earcon). Show "thinking" within ~300 ms; the 4 s latency gate (TIMELINE Gate C) must *feel* alive. TTS shows progress. Language switch shows what is/isn't translated. |
| Real-world match | Student vocabulary (Hinglish, "slider badhao"), not system jargon. Physics terms: keep the English term the board exam uses, gloss in the learner's language. |
| User control | Interrupt the tutor (barge-in), stop audio, undo a language change, reset a sim, skip a check. Never trap. |
| Consistency | One representation per physical object across all sims (PhET finding, section E). Same control in same place. |
| Error prevention | Constrain sim ranges to meaningful physics; disable mic if permission is denied rather than letting it fail silently; confirm destructive actions (clear memory). |
| Recognition over recall | Show the current page/block the tutor is anchored to ("Asking about: Simulation 2"). Show recent language, not a buried menu. |
| Flexibility | Push-to-talk and hands-free; typed fallback; keyboard control of every sim. |
| Minimalism | Max ~3 groups of ~3 controls per sim panel (PhET). No decorative chrome. |
| Error recovery | Speech not understood → re-ask in the student's language and offer typing. Plain words, constructive next step. "You can say…" help after repeated failures. |
| Help | Short, in context, on request (PhET: unsolicited help gets obeyed instead of exploring). |

## C. Norman's design concepts  [canonical; not re-fetched this session]

Affordances and **signifiers** (a draggable object must *look* draggable), **mapping**
(control layout matches effect), **feedback** (immediate, informative), **constraints**,
and the **conceptual model** (what the learner believes the system does). The last is
critical: a student must understand "the tutor can see this page but not hear the room's
other people" etc. State the conceptual model of each add-on in one sentence and design
the UI so it cannot be misread.

## D. Mayer's multimedia learning principles  [STRONG - decades of lab studies; 15 principles in the 3rd ed.]

Coherence (drop the extraneous) · signaling (cue what matters) · redundancy (graphics +
narration beat graphics + narration + the same text) · spatial contiguity · temporal
contiguity · segmenting (learner-paced chunks) · pre-training (names/characteristics of
key concepts first) · modality (narration over on-screen text with graphics) ·
multimedia (words + pictures) · personalization (conversational style) · voice (a
human-sounding voice) · image (the speaker's face isn't needed) · generative activity
(have the learner do something with the material).

| Principle | Zivon implication |
|---|---|
| Coherence | No background music, decorative animation, or "fun" breakage that distracts (PhET found such features hurt). |
| Signaling | Highlight the object/value the tutor is talking about, in sync. |
| Redundancy + modality | **Tension with TTS-plus-text** - see `07-zivon-tensions-to-resolve.md`. Default: narrate + visual, captions on request (also an accessibility need). |
| Contiguity | Controls sit on/next to the object they control. Labels adjacent to the thing labelled. Speech and the matching animation start together. |
| Segmenting | Lessons are blocks; the learner advances. Voice replies are short chunks, not monologues. |
| Pre-training | Show/name key terms and the sim's variables before the student manipulates them. |
| Personalization / voice | Conversational, friendly register; a natural Indian-accent voice (Timbre). |
| Generative activity | Predict-before-run, explain-after-run, speak-the-answer: the Socratic loop. |

## E. PhET interface research  [STRONG for interface-level claims: >200 think-aloud interviews, 89 students; the sim base is physics]

Paraphrased findings that translate directly into rules (details in `04`):
- Intuitive controls beat help text; click-and-drag on objects is the most natural action; students try to grab anything that looks usable.
- Sliders + a typed-value box; radio buttons; checkboxes (students rarely un-check). Pop-ups need a visible close (✕).
- Start the sim nearly still, in the simplest view; motion on load overwhelms and students stop experimenting. A short "wiggle-me" invitation, shown once, vanishing on first interaction, only when the key object isn't obviously grabbable.
- Few controls, in small groups (about three groups of about three); labels of one to three words; no abbreviations; students read text only when it is attached to a control.
- Everything on screen is treated as meaningful by a novice: remove irrelevant visual detail; colour is a stronger cue than a text label.
- Same object, same representation across sims; and don't reuse one look for different things.
- Make the sim break meaningfully at extremes - but not so entertainingly that it distracts.
- Play/pause/step controls are not found unprompted; make them prominent and consistent.
- Help: avoid needing it; if present, request-only, short, adjacent to the item, no science explanations; extensive "mega-help" was almost never used.
- Test with real novices - experts overlook misleading cues.

## F. Physics-education research  [STRONG]

- Interactive-engagement courses roughly doubled conceptual gain vs traditional lecture on the Force Concept Inventory in a 6,542-student survey (Hake 1998). Implication: *doing and predicting beats reading and watching.*
- Misconceptions are sticky; telling doesn't displace them. Use misconception-targeted distractors in checks, and make the student commit to a prediction before seeing the result.
- Retrieval practice, desirable difficulty, deliberate practice, and prior-knowledge activation improve retention [MODERATE-STRONG]. Make the student *recall and say* before the tutor reveals.
- Novices have small working memory; a lecture-style wall saturates it. This is the root reason for the product's existence.

## G. Voice and conversation design  [WEAK-MODERATE: practitioner guidance from Google/Alexa-era design, consistent across sources]

- Design beyond one turn; carry context ("what about the other ball?").
- Make turn-taking unmistakable (earcon/pause); support barge-in.
- Error types: no input, no match, system error - each gets its own recovery; never a dead end; after ~3 failures offer explicit "you can say…" help or another modality.
- Confirm understanding briefly; keep the persona consistent; brief mode for experts, fuller for novices.
- Latency is a UX dimension: acknowledge delay immediately.
- Write sample dialogues *before* prompts; they are the spec.

## H. Children, honesty and consent  [STRONG as ethics/law; implementation detail needs counsel]

- Minors are the users; India's DPDP Rules 2025 require verifiable parental consent for under-18s and bar tracking/behavioural monitoring of and targeted ads to children, with narrow purpose-based exemptions (see `06`). Substantive duties start about 14 May 2027 per secondary sources - design for it now.
- Honest design: personalization is visible and editable ("here's what the tutor remembers - clear it"). No simulated empathy beyond the tutor persona; no false urgency.
