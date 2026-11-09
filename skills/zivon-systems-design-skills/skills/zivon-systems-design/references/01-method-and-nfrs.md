# Method and NFRs

## 1. Reading the product handoff critically

Before designing, check the product document for: NEEDs with no caller; information items with no source; missing volume hints; features that quietly require identity; "real-time" claims with no latency number; retention left blank for child-related data; schema change proposals for the content factory that have no owner. Return a gap list. Where you must proceed, record an explicit assumption `[ASSUMPTION]` with the number you used.

## 2. Reliability, scalability, maintainability as the lens  [STRONG - Kleppmann, DDIA ch.1]

Reliability = continues correctly despite faults (hardware, software, human). Scalability = reasonable ways to cope with growth, measured in **percentiles** (p50/p95/p99), not averages. Maintainability = operability + simplicity + evolvability. Most trade-offs in this design are tensions among these three; name them in each ADR.

## 3. NFR table - fill with numbers (starter values are `[ASSUMPTION]`)

| Category | Requirement | Starter number / source | How measured |
|---|---|---|---|
| Voice latency | End-of-speech → first spoken audio | p50 ≤ 3 s, p95 ≤ 4 s (repo Gate C: "< ~4 s") | per-stage timers, server + client clocks |
| Voice stage budget | endpointing / STT-final / LLM first token / first sentence / TTS first byte / network | see `04` §4 | per-stage histograms |
| Content latency | Lesson page interactive on low-end Android | < 2 s load (repo budget) | synthetic + RUM |
| Content availability | Lesson bundles served | 99.9 % monthly `[ASSUMPTION]`; independent of voice stack | uptime probe |
| Voice availability | Voice session establishment success | ≥ 99 % `[ASSUMPTION]`; degrade to text on failure | success ratio |
| Concurrency | Simultaneous live voice sessions | decide from demo/judge traffic and credit budget; start with N ≈ 20-50 `[ASSUMPTION]` | load test |
| Durability | Lesson bundles, consent ledger, DB backups | ≥ 2 independent copies in ≥ 2 failure domains | restore drill |
| RPO | Relational DB | ≤ 5 min (WAL archiving) `[ASSUMPTION]` | archive lag metric |
| RPO | Immutable artifacts | 0 once "published" (publish waits for verified cold copy) | catalogue state |
| RTO | Full service restore from cold | ≤ 4 h `[ASSUMPTION]` | drill timing |
| Integrity | Cold-copy checksum verified on write and by periodic scrub | 100 % verified; scrub 1-5 %/day | scrub job |
| Capacity | SSD headroom | alert > 70 %, evict > 75 %, page > 90 % `[ASSUMPTION]` | volume metrics |
| Privacy | Raw child audio stored | none by default | data inventory test |
| Privacy | Subject deletion fulfilment | ≤ 90 days per DPDP (verify), target ≤ 7 days | deletion SLA |
| Security | Secrets in images/manifests | none (repo rule) | CI secret scan |
| Cost | Gnani credit burn per student-minute | measure; reserve ~40 % for demo/judges (repo) | credit ledger |
| Observability | Trace id spans client → WS → STT → LLM → TTS | 100 % of sessions | trace sampling |
| Maintainability | Deploy rollback | ≤ 10 min | drill |
| Accessibility of ops | Admin views display only aggregated, non-identifying data | by design | review |

## 4. Capacity method (back-of-envelope, template in `templates/capacity-model.md`)

1. Count **units**: lessons × languages × versions; audio blocks × voices × speeds; sessions/day × turns/session; events/session.
2. Size **each unit** (KB) from the product handoff's volume hints; if absent, estimate and tag.
3. Multiply for 1 day / 1 month / 1 year at three load levels (demo, pilot, growth).
4. Compute: SSD working set, cold total, egress/month, API calls/month, DB rows, event volume, Gnani credits/month.
5. Compare with NFRs; the **binding constraint** is the first to hit its limit - design around it, not around averages.

Typical sizes to sanity-check against (verify with real artifacts): compressed lesson HTML/JS/SVG bundle - tens to a few hundred KB; narration audio (speech, Opus ~16-32 kbps) ≈ 2-4 KB/s, so a 60 s block ≈ 120-240 KB; transcript text ≈ 1-3 KB per turn; learning event ≈ 0.3-1 KB; raw PCM 16 kHz mono ≈ 32 KB/s (why raw audio is expensive to keep).

## 5. Choosing components - the justification rule

A component enters the design only with a row: *requirement it satisfies → alternatives considered → why simpler options fail → operational cost → exit path*. Default to the simplest thing that meets the NFRs: a modular monolith (FastAPI) with clean module seams (audio/session, Gnani clients, LLM prompting, tutor logic, page-context anchoring, usage logging - as the repo already specifies) before any service split; managed or single-node Postgres before sharding; a worker + outbox before a message broker; add a cache or queue only when a measurement or an NFR demands it.

## 6. Decision records

Every significant decision gets an ADR (vendored `develop-adr`, `architecture-designer/references/adr-template.md`). Required fields: context, options (≥ 2 real alternatives), decision, consequences (including what becomes harder), revisit trigger, and the NFR(s) driving it.
