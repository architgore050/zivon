# zivon-product-design (skill)

Decide which features deserve to exist, then specify each down to the element, datum, API need and event.

**Start here:** read `SKILL.md` (≈80 lines). It has the 9-phase pipeline, the 10 hard rules and a reference map. Load other files only when the phase needs them.

```
zivon-product-design/
├── SKILL.md                     entry point - pipeline, rules, reference map
├── README.md                    this file
├── references/
│   ├── 01-principles-catalog.md        Rams, Nielsen, Norman, Mayer, PhET, PER, voice UX, child ethics → Zivon rules
│   ├── 02-feature-value-filter.md      layers, 8-question gate, KEEP/MERGE/DEFER/KILL, Kano, anti-patterns
│   ├── 03-granular-spec-method.md      ID scheme, 5 artifacts, completeness protocol, handoff, orphan checks
│   ├── 04-education-and-simulation-ux.md   per-block elements, sim rules, checks, learning metrics
│   ├── 05-voice-translation-tts-ux.md       voice states, translation scope, TTS scope, personalization
│   ├── 06-india-context-a11y-privacy.md     constraints, WCAG 2.2, perf, DPDP child-data flags
│   ├── 07-zivon-tensions-to-resolve.md      12 explicit conflicts to decide (T1-T12)
│   ├── 08-self-review-checklist.md          final gate
│   └── sources-and-evidence.md              bibliography, verification status, weaknesses
└── templates/                   feature card, element inventory, information inventory,
                                 state matrix, traceability matrix, decision log, principles brief, backend handoff
```

Typical use: Phase 0 → read repo docs; Phase 1 → `01` + `templates/design-principles-brief.md`; Phases 3-4 → `02` + `templates/decision-log.csv`; Phase 5 → `templates/feature-card.md`; Phase 6 → `03` + the CSV templates; Phase 7 → `templates/backend-handoff.md`; Phase 8 → `08`.

Hand-off target: the sibling skill `zivon-systems-design`, which consumes the backend handoff list.
