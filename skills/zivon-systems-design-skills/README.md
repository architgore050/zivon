# zivon-systems-design-skills (bundle)

Skills for turning a product feature/element inventory into a **backend spec, a database spec and a storage-tiering plan** (backend SSD vs a separate cold-storage provider; when data syncs, how it is verified, evicted, restored, and deleted). Built for Zivon (FastAPI + WebSockets + Gnani Prisma/Evon/Timbre + Kubernetes), reusable for similar voice-first products with children as users.

## Read order for an agent

1. This README.
2. `skills/zivon-systems-design/SKILL.md` - method, hard rules, "pull the plug" test. **Always.**
3. `references/06-zivon-systems-constraints.md` - repo facts and what is *not yet built*. **Before proposing anything.**
4. Then `01 → 02 → 03 → 04 → 05 → 07` as the phase table directs.
5. `vendored/INDEX.md` for mechanics: ADRs, REST/OpenAPI, FastAPI, WebSocket protocol, Postgres, SRE, security, instrumentation.
6. Input comes from the `zivon-product-design-skills` bundle's backend handoff list.

## Layout
```
zivon-systems-design-skills/
├── README.md  NOTICE.md
├── skills/zivon-systems-design/        ← original, Zivon-specific
│   ├── SKILL.md  README.md
│   ├── references/  01 method+NFRs · 02 classification+tiering+sync · 03 DB spec · 04 API+realtime · 05 privacy/security/ops
│   │                06 repo constraints · 07 review checklist · sources-and-evidence
│   └── templates/   adr · data-classification.csv · sync-policy.csv · nfr-table · api-endpoint-card · ws-message-catalog
│                    failure-mode-table · capacity-model · backend-spec-skeleton · db-spec-skeleton
└── vendored/                           ← third-party, licences retained (see INDEX.md)
    ├── pm-skills/ (Apache-2.0)  develop-adr · measure-instrumentation-spec
    └── jeffallan-claude-skills/ (MIT)  architecture-designer · api-designer · fastapi-expert · websocket-engineer
                                         postgres-pro · database-optimizer · sre-engineer · secure-code-guardian
```

## Install
Copy `skills/zivon-systems-design/` into the Zivon repo's `skills/`; `vendored/` alongside (or outside). Claude Code: `.claude/skills/`. Update `AGENTS.md` and the README repo map in the same PR. If new top-level docs folders (`docs/backend/`, `docs/data/`, `docs/decisions/`) are created, update the `AGENTS.md` docs map as well.

## Verification status
Provider price/feature claims come from 2026 blog comparisons (marketing-grade) and **must be re-verified on official pages at decision time**. DPDP analysis is from secondary summaries; not legal advice. Latency/capacity numbers are tagged `[ASSUMPTION]` until measured.
