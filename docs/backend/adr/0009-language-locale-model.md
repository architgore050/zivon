# ADR-0009: Language data model = 11-value locale enum (Gnani 10 + `hinglish`) with fixed STT/TTS mappings (T2)
- Status: accepted — mapping verified at Gate-C rehearsal (A-04)
- Date / deciders: 2026-11-07, Stage-2 systems session, implementing the T2 revision of 2026-11-07 (product language set = all Gnani-supported languages; EN/Hindi/Hinglish were the demo subset, not the ceiling)
- Driving NFRs / requirements: NEED-006/008/016, F-WRP-LAN-01, addendum-12 verified model facts

## Context
Prisma accepts 10 language codes (`en-IN` accepts EN-HI mixed audio; v3.0 adds `indic-auto` +
`detected_language_code`). Timbre v3.0: every voice speaks all 10 languages. The UI has a third
value — **hinglish** (Roman-script house style, INF-017) — which is not a Gnani code. The data
model must carry the full set without inventing a fake language code.

## Options considered
| Option | Pros | Cons | Cost/ops burden | Fails which NFR? |
|---|---|---|---|---|
| **Locale enum = 10 Gnani codes + `hinglish`; seed maps `hinglish → en-IN` (STT) and `hinglish → hi-IN` on a polyglot v3.0 voice (TTS); STT default = `indic-auto` with `detected_language_code` feeding the mirroring rule** | honest to both model APIs; enum extensible; mapping is seed data (db-spec §8), changeable without migration | mapping is an assumption until rehearsal (A-04) | none | — |
| 3 demo locales only | smaller enum | contradicts the T2 revision; re-migration when SC-01 scales | — | product decision already made |
| Map hinglish to its own Gnani-style code | explicit | invents a code the APIs reject — request failures at the boundary | — | NEED-006/008 |

## Decision
Option 1. Per-string translation data model (the other half of T2): `language_bundle` JSONB keyed
`block_id + field → text` with mt/reviewed flags (db-spec §4.10, SC-01) — decided build-time in
ADR-0013.

## Consequences
Easier: adding a Gnani language is a seed row + bundle, no schema change. Harder: two mapping
tables to keep honest; UI must show *which* locale was served (English-fallback marker INF-087).
Monitor: Gate-C smoke test (30-min v3.0 test already scheduled).

## Revisit trigger (measurable)
Gate-C rehearsal shows `hinglish → en-IN` STT accuracy below the no-match threshold on real kid
speech → try `indic-auto` as the hinglish STT path (config change, no schema change).

## References
addendum 12 (docs.gnani.ai verified 2026-11-07); features.md T2 revision; db-spec §4 conventions + §8 seed.
