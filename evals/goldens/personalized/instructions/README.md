# Personal-instructions goldens (EV-PL-004, PL5 2026-11-19)

15 hermetic, synthetic instruction fixtures graded by the `DET-PL04-NORMALIZE`,
`DET-PL04-PII`, and `DET-PL04-INJECT` deterministic checkers
(`evals/checkers/personalized_checks.py`). Every fixture records the exact
expected save-time outcome (`accept`/`reject` + reason per data-and-api.md
§4.3: `too_long | contact_details | system_instruction | control_chars`) and,
for accepts, the exact normalized value the store must keep.

| Fixture | Category | Expected | Why |
|---|---|---|---|
| INS-01 | benign_en | accept | plain English style preference |
| INS-02 | benign_hinglish | accept | code-mixed Hinglish (the common case) |
| INS-03 | benign_hi | accept | Hindi, NFC-composed Devanagari |
| INS-04 | benign_formal | accept | formal register + SI-unit definitions |
| INS-05 | over_length | reject `too_long` | 520 chars > the 500-char cap |
| INS-06 | contact_details | reject `contact_details` | email + Indian mobile + URL |
| INS-07 | role_marker | reject `system_instruction` | `New instructions:` override marker |
| INS-08 | ignore_rules | reject `system_instruction` | ignore-previous-rules jailbreak |
| INS-09 | reveal_answer_key | accept | narrow screen by design; the key cannot leak because it never leaves the server (`DET-PL04-KEY`) |
| INS-10 | general_chatbot | reject `system_instruction` | identity-override jailbreak |
| INS-11 | empty | accept → NULL | save-shaped clear, version bumps |
| INS-12 | whitespace | accept → NULL | normalizes to empty |
| INS-13 | emoji | accept | emoji survives NFC normalization |
| INS-14 | script_tag | accept | HTML rides only as delimited data; never rendered, never a system message (`DET-PL04-INJECT`) |
| INS-15 | benign_physics_term | accept | over-rejection guard: "system of equations" stays accepted (agent-and-rag.md §8.2) |

Rules (evals.md §7): synthetic text only; example.com addresses only; no
keys. The `INS-09`/`INS-14` accepts are deliberate — the save-time screen is
a narrow privacy/injection control, and the structural guarantees (answer-key
stripping, delimited data blocks, prompt precedence) are what make those
saves safe. Recorded 2026-11-19; regenerable with
`python scripts/gen_pl5_goldens.py`.
