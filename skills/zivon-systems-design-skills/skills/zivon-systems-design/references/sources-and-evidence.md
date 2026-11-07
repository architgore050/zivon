# Sources and evidence (dated 7 Nov 2026)

Status: **V** = opened/read this session; **S** = surfaced in search results only; **C** = canonical, cited from memory, re-verify before quoting. Paraphrased only.

| Source | Status | Supports |
|---|---|---|
| Kleppmann, *Designing Data-Intensive Applications* (O'Reilly) - reliability/scalability/maintainability, storage engines, replication lag and read-your-writes, sync vs async replication, unbundled/derived data via logs | S (multiple chapter summaries); C | `01` §2, `03`, `02` §3 |
| Nygard (2011), "Documenting architecture decisions" - ADR format | C (practiced in vendored `develop-adr`, `architecture-designer`) | `01` §6 |
| Google SRE book/workbook - SLOs, error budgets, golden signals | C | `05` §3 |
| Twelve-Factor App - config in env | C | repo already follows |
| PostgreSQL docs - continuous archiving/WAL, partitioning | C | `02` §3, `03` |
| Object-storage provider comparisons (blogs dated 2026: leanopstech, spendark, tech-insider, speedtesthq, dev.to) - R2 zero egress/single tier, B2 low storage price/egress allowances, Wasabi min retention, S3/Azure/GCS multi-tier | S - **marketing-grade, numbers unverified** | orientation for `02` §4; verify on official pricing pages |
| India DPDP Act 2023 and Rules 2025 (MeitY G.S.R. 846(E)) - summaries: Biometric Update, Mondaq, Sansa Legal, ORF, DSK Legal, India Briefing, Anantam IAS | Primary not read; secondary S | `05` §1, `06` |
| Conversation-design/VUI practice (Google, Alexa; Pearl 2016) | S | `04` §4 |
| Anthropic/community skill repos: Jeffallan/claude-skills (MIT), product-on-purpose/pm-skills (Apache-2.0) | V (cloned; licences read) | vendored subset |

Known weaknesses: provider facts change monthly; latency budgets are generic until measured against Prisma/Evon/Timbre; no primary-source legal reading; no load testing performed; the design assumes a single-region start.
