# Personalized-learning goldens (PL2, 2026-11-18)

Hermetic recorded transcripts + a deterministic fixture index. Student text is
synthetic; no names, emails, or keys. The index version is content-addressed
over these exact chunks with the fixture embedder.

- `sessions/class-10-light-weakness/` — 3 transcripts (correct-first,
  wrong-then-adapt, skip-all) with expected stage sequences and honest mastery
  summaries; replayed through `backend/personalized/state.py` by DET-PL01-*.
- `sessions/class-9-motion-diagnostic/` — the bank diagnostic-first flow.
- `rag-index/` — the synthetic index fixture graded by DET-PL02-*.

Consumed by `evals/cards/EV-PL-001.yaml` and `EV-PL-002.yaml` (deterministic
checkers only; the judge is a full-suite, PL5-gated concern).
