# Capacity & cost model — Zivon

Stage-2 systems design (2026-11-07). Back-of-envelope per the method (skill ref 01 §4):
units → sizes → day/month/year at three load levels → compare against NFRs → **binding
constraint**. All sizes from `backend-handoff.md` §5 volume hints (measured-ish) or tagged
`[ASSUMPTION]`. All money figures in USD; Gnani credits are the scarce currency.

**Load levels:** *demo* = challenge window (≤ 500 sessions/day, ≤ 10 concurrent voice, 6 topics,
A-07) · *pilot* = post-challenge school pilot (×10 sessions, 6 topics × 3 languages, `[ASSUMPTION]`)
· *growth* = multi-class rollout (60 topics × 11 languages, `[ASSUMPTION]`).

---

## 1. Storage units

| Unit | Count (demo / pilot / growth) | Size each | Hot working set | Cold total | Tier | Notes |
|---|---|---|---|---|---|---|
| Lesson bundles (topic×class×lang×version) | 18 / 540 / 20 k objects | 150–400 KB (measured gate) | ≤ 5 MB / 150 MB / 6 GB (U3+U1) | all versions: ~10 MB / 300 MB / 20 GB (U4 + git) | C1 | versions rotate ~3/topic/language `[ASSUMPTION]` |
| Narration audio (block×lang×voice×1.0×speed) | ~540 / 5 k / 500 k objects | 90–270 KB (measured hint) | 100–160 MB / 1.5 GB / 15 GB | same, origin copies | C2 | 45–90 blocks/topic `[ASSUMPTION]`; pace 1.0 only (Q4) |
| Language bundles | 0 / 180 / 20 k | 10–30 KB | negligible | rides C1 | C3 | SC-01 (P1) |
| Run evidence | 1–3 runs/day manual | 10–100 MB/run `[ASSUMPTION]` | last 10 runs ≤ 1 GB | archived forever: ~1 GB/mo `[ASSUMPTION]` | C4 | manual-trigger only |
| Transcripts (voice_turn) | 10 k rows/day | 1–3 KB | ≤ 140 MB (7-d TTL) | **none by design** | C6 | hot DB only |
| Session rows | 500/day | 0.5–1 KB | ≤ 15 MB (30-d) | rides backups | C20 | roll-up then delete |
| Telemetry events | 15 k/day | 0.3–1 KB | ≤ 810 MB (90-d) | ~15 GB/yr compressed `[ASSUMPTION]` | C10 | JSONL.zst ≈ 5–10× smaller |
| Credit ledger | 40 k/day | 100–200 B | ≤ 540 MB (90-d) | ~1 GB/yr | C11 | counts only |
| Abuse buckets | rolling | ~100 B | ≤ 50 MB | none | C19 | 72 h expiry |
| DB total (U2) | — | — | **~2–3 GB demo / ~10 GB pilot** | base 50–200 MB/day + WAL ~40 MB/day `[ASSUMPTION]` → 30-d window ≈ 3–7 GB | C14 | fits a 10 Gi `zivon-db` PVC with 70 % watermark headroom (demo) |
| Cold store total (U4) | — | — | n/a | **demo ≤ 8 GB · pilot ≤ 25 GB · growth ≤ 100 GB/yr** | U4 | demo fits **B2 10 GB free + R2 10 GB free** — $0 through the challenge |
| Model artifacts (Gemma quantized) | 1–2 versions | 15–30 GB `[ASSUMPTION]` | GPU host disk | 1 copy per version | C15 | cold copy ≈ $0.10–0.21/mo on B2 |

**Egress:** student-facing egress is nginx/hosting (not cold): demo ≈ 500 sessions × ~0.5 MB
pages+narration delta ≈ **250 MB/day ≈ 8 GB/mo** `[ASSUMPTION]` — ordinary hosting cost, tiny.
Cold egress = drills/restore only: B2 free ≤ 3× storage; R2 free always → **$0 planned cold egress**.

## 2. Voice load & compute

- Sessions: ≤ 500/day, ≤ 10 concurrent, ≤ 20 turns/session (A-07). Audio up: 2–10 s × Opus
  ≈ 4–20 KB/turn streamed; down TTS 30–90 KB/turn → **< 150 KB per turn** (handoff §5) →
  10 concurrent sessions ≈ < 2 Mbps — trivial for one pod; sizing voice pod 1 CPU / 512 Mi,
  1 replica (NFR-13) holds at 2× envelope `[ASSUMPTION]`; scale trigger: > 10 concurrent or
  event-loop p99 stall → 2nd replica + session-store revisit (ADR-0002).
- DB writes/turn: 1 turn row + ~4 ledger rows + ~1.5 events/turn avg → ~7 rows/turn →
  70 k rows/day at envelope — single Postgres handles this with three orders of magnitude headroom.
- **GPU host (A-09):** warm instance serving Gemma 4 26B A4B at first-token < 1.2 s — the only
  significant compute line item (hosting cost open TIMELINE infra item; not a Gnani-credit item).

## 3. Gnani credits — the binding constraint

Only the **voice agent** burns credits (founder correction 1): Prisma STT seconds + Timbre TTS
characters (tags bill as characters). Narration is a **build-time** burn (A-15), never per student.

| Flow | Volume | Credit math |
|---|---|---|
| Voice turn | ≈ 15 s STT + ≈ 500 TTS chars (from handoff per-20-turn figures: 5 min STT + 10 000 chars) | per 20-turn session ≈ 5 min STT + 10 k chars ≈ **X credits** — unit prices unknown (A-01); calibration formula: `credits/session = stt_s × p_s + chars × p_c` to be filled from the dashboard before Gate-C rehearsal |
| Per-user cap | 30 credits/day | ≈ 1.5–2 full 20-turn sessions/user/day at typical pricing `[ASSUMPTION]` — free-trial scale as founder intended |
| Global tranche | 1 000 credits/day | ≈ 50–66 full sessions/day `[ASSUMPTION]` — above the 500-session envelope only because most sessions use < 20 turns or typed path |
| Demo profile | 1 000 global / 100 per-user (A-05) | judge-day bursts bounded |
| Total programme | **10 000 credits** (5 k × 2 members) | at full tranche 10 days = 10 000 → **the tranche is the ceiling, not the total**; repo rule: reserve ~40 % for demo/judges → enforced `reserved` bucket cap ≈ 4 000 credits; normal-mode burn budget ≤ 6 000 over the window |
| Narration build | 6 topics × ~15 k chars English ≈ 90 k chars one-time | capped ≤ **1 500 credits** (A-15, founder approval before first run); × 11 languages post-challenge ≈ 1 M chars — a **budgeted post-challenge tranche decision**, not challenge-window |
| Reconciliation | nightly | drift ≤ 2 % (AC-2); daily usage log (repo rule) |

**Binding constraint: Gnani credits** — it hits first by design (1 000/day tranche vs storage/
compute headroom). The guard architecture (ADR-0015) is built *around* this constraint: degrade
ladder instead of wall, typed path as the credit-free tutor fallback, narration pre-generated so
reading costs zero runtime credits.

## 4. Reconciliation against NFRs

| NFR | Capacity verdict |
|---|---|
| NFR-13 (10 concurrent / 500 sessions) | pod + DB sizing hold at 2× envelope; GPU host is the only scale question (A-09) |
| NFR-17/18/19 (RPO/RTO) | backup volumes 3–7 GB → restore drill ≤ 4 h plausible at demo scale `[ASSUMPTION]` |
| NFR-21 (watermarks) | demo PVCs: `zivon-db` 10 Gi (2–3 GB used), `zivon-cache` 5 Gi (≤ 1 GB), `zivon-frontend` existing — all < 70 % at demo scale |
| NFR-23/24 (retention/deletion) | hot-row volumes bounded by TTL jobs above; cold archives only from P1 |
| Cost row (credits/student-minute) | ≈ X credits/student-minute pending A-01 calibration; 40 % reserve enforced |

## 5. What would change the model (watch items)

1. **Judge-traffic spike** (submission day): tranche + demo profile absorb it; typed path is the
   credit-free overflow valve — the ladder must be exercised in rehearsal.
2. **Language expansion** (SC-01): narration credit burn scales × languages — post-challenge
   tranche decision (A-15), storage stays trivial.
3. **Unit prices (A-01)**: if `p_c` (per char) is high, shorten tutor replies (≤ 2 sentences
   ladder) before touching caps — prompt lever before budget lever.
4. **GPU hosting cost**: the only real money line; self-host vs managed — TIMELINE infra item,
   founder decision, outside this spec's authority.
