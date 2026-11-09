# ADR-0004: Cold storage = Backblaze B2 (primary) + Cloudflare R2 (second copy), separate provider with split credentials
- Status: accepted — India-residency question open (Q-L1, counsel)
- Date / deciders: 2026-11-07, Stage-2 systems session; founder requirement: cold store at a **separate service provider**
- Driving NFRs / requirements: NFR-16/18/19/20; storage-tiering §1 invariants; A-13; DPDP children's-data posture

## Context
U4 must hold: origin copies of published bundles + narration, WAL archives + base backups,
consent-ledger snapshots, event/ledger archives. Criteria matrix fully rendered in
`storage-tiering.md` §5 from official pages fetched 2026-11-07 (B2 pricing page; R2 pricing +
data-location docs). Wasabi page unreachable this session; AWS/GCS region price tables not
parseable — those cells are flagged [verify], no blog numbers used.

## Options considered (matrix in storage-tiering §5; summary)
| Option | Pros | Cons | Cost at our scale | Fails which NFR? |
|---|---|---|---|---|
| **Backblaze B2** | $6.95/TB-mo; **free Class A/B/C API calls** (WAL streaming costs nothing); no min duration/size; native versioning + Object Lock; free egress ≤ 3× storage; 10 GB free tier covers the whole challenge | **no India region** (US/EU only [verify]) | $0 through challenge; ~$7/TB-mo after | residency question only |
| **Cloudflare R2** | free egress always; 10 GB + ops free tier; Automatic placement + `apac` hint; Mumbai PoP for access; S3 first-class | no India **jurisdiction** guarantee (jurisdictions: EU/US/FedRAMP only); Object Lock/versioning absent [verify] | $0 | residency question only |
| AWS S3 ap-south-1 (Mumbai) | India region; Object Lock; IAM | highest storage price [verify]; egress paid; **fails provider-independence if compute later lands on AWS** | paid | — |
| GCS ap-south1 (Mumbai) | India region | interop S3 layer partial; egress paid [verify] | paid | — |
| Wasabi | cheap flat | 30-day minimum-duration policy [verify]; no India region; page unreachable this session | — | eviction/rewrite patterns collide with min-duration |

## Decision
**B2 primary** (all classes per storage-tiering §5), **R2 as the second copy** for the two
highest-value classes (C9 consent snapshots, C14 monthly pinned base backups) — two independent
providers, both free at challenge volumes. S3/GCS Mumbai remain the designated candidates **if
counsel rules India residency mandatory** (Q-L1); until then, child-adjacent archives are
envelope-encrypted client-side before upload (A-13), keys in-cluster only.

## Consequences
Easier: zero cold cost in the window; writer key cannot delete (B2 app-key permissions + version
keys); drills have free egress. Harder: two SDK configs; residency question must be answered
before any scale-up; B2/R2 multipart checksum semantics to confirm at build (SYNC-01 verify step).
Monitor: outbox backlog age, scrub drift, free-tier headroom (10 GB lines).

## Revisit trigger (measurable)
Counsel answer mandating India residency → migrate to S3 ap-south-1 or GCS ap-south1 (S3 API =
mechanical swap). Cold total > 10 GB on either provider → price re-run. Object Lock requirement
formalized → confirm B2 compliance-mode lock on official feature page before enabling.

## References (official, fetched 2026-11-07)
backblaze.com/cloud-storage/pricing · developers.cloudflare.com/r2/pricing ·
developers.cloudflare.com/r2/reference/data-location · aws.amazon.com/s3/pricing (partial fetch).
