# Local agent handover — Zivon prototype (2026-11-21)

Single handover file for the next local agent session. Everything below reflects
pushed GitHub state only — no disk-only facts.

## Where the project stands

Merged into `main` (in order): #94 auth/email, #96 series importer, #95 Class 10
assessment banks (Human Eye + Electricity), #97 deploy prep, #98 F11 hermetic E2E
suite (63 tests: 60 HTTP + 3 real Chromium), #99 PL5 personalized-learning judges
(EV-PL-001/002/004) with calibration + live-suite verdict.

Open PRs:

- **#100 `feature/w-magnetic-fix`** — Magnetic Effects: registration commit
  (`1256657`: syllabus slug + concept-map + test row), two gated lesson-regen
  attempts committed (`9614d6e`, `103eea5`, 16/16 stages ok, EN/HI/Hinglish),
  docs sync (`23b1574`). Merge once CI is green (CI was still running when this
  file was written).
- `docs/local-agent-handover` — this file + the TIMELINE status header (PR to be
  opened by the close-out).

## Standing rules (founder-issued, do not re-derive)

1. **Granular commits, pushed to GitHub immediately.** The sandbox wiped worktrees
   four times; disk-only state is treated as nonexistent. Never report back with
   finished work unpushed.
2. Never `git clean` (any form) and never `rm -rf` untracked/ignored paths
   (`runs/`, `sources/pdfs/`, `sources/cache/`, `tmp/`, `evals_runs/`).
3. Never push directly to `main`; PRs only. Never merge a PR without green CI.
4. Secrets are never printed, committed, or stored outside the env files. Master
   env lives in `/home/z/my-project/.secrets/zivon-cloud.env` (outside the repo).
   For LLM/pipeline runs use the shell-quoted rebuild (`/tmp/zivon-run.env`) —
   plain sourcing loses the JSON quoting of `ZIVON_EXTRA_HEADERS`.
5. Docs + TIMELINE updates ride in the same PR as the work they describe.

## Remaining agent todos

1. **Magnetic Effects bank (PR #100 follow-up).** Root cause, verified twice: the
   rationalised NCERT Class X book has ch12 sections 12.1–12.4 only — motor,
   electromagnetic induction, generator (old §12.4–12.6) are not in the corpus,
   so gate A2 correctly refuses with 2 fatal `concept.orphan`
   (electromagnetic-induction, electric-generator). Evidence in
   `runs/archive/magnetic-attempt1|2/` and the assessment run dir. Unblocks:
   (a) add a CC-BY source carrying those topics (Siyavula Gr11/12
   electromagnetism) and regenerate founder-side, or (b) a recorded syllabus
   re-curation. Then: bank → mirror six pack files → add `MAGNETIC` to
   `TRACKED_CHAPTERS` in `testing/backend/test_assessment_import.py` with counts
   computed by real throwaway-SQLite import (baseline 198 question rows / 36
   speaking prompts / 28 topic priors / 4 packs). Full resume recipe:
   `download/magnetic-workstream-handoff.md`.
2. **PL5 judge refinement.** Live verdict on PR #99: EV-PL-001/004 pass; EV-PL-002
   fails on a single judge false positive over a clean sample — tighten that
   judge's rubric/verify pass; the remaining failures are pre-existing non-PL
   cards (documented, not softened).
3. **Dependabot.** ~20 open PRs from the July era; triage: merge patch/minor with
   green CI, rebase the rest, close stale majors that break pinned versions.
4. **TIMELIAN maintenance.** Union-append new dated sections at the END; conflicts
   resolve by union (see `scripts/resolve_timeline_union.py` pattern).
5. **Founder-local eval session.** The one real teach-check-adapt run needs the
   live stack + keys; document evidence when it happens.

## Founder manual todos (cannot be done by an agent)

All with placeholders documented in `docs/deployment/founder-cutover-runbook.md`
(env contract table + 11 cutover steps + backup/restore + rollback):

- Domain purchase, DNS A/CNAME records, host + SSH access.
- Google OAuth console: create client, redirect URIs, paste client id/secret.
- Email backend choice + creds (SMTP/API key + domain verification).
- Postgres provisioning + `DATABASE_URL`.
- Voice-provider keys region check (Gnani endpoints are India-region) and the
  Gemini/OpenCode keys.
- GitHub UI: enable branch protection (require PR + status checks) — API cannot
  do this with current token scope.
- PYQ legal clearance decision (DEC-COMP-001) before any paper-pack work.
- Magnetic unblock decision (a) or (b) above, then the founder-local regen.
- The one live teach-check-adapt session for PL5 evidence.

## Repo pointers

- Deployment: `docs/deployment/founder-cutover-runbook.md`,
  `docs/deployment/prototype-deployment.md`, `docker-compose.prod.yml`.
- Content factory: `docs/content-factory/runbook.md`,
  `docs/content-factory/assessment.md`.
- Evals: `docs/specs/personalized-learning/evals.md`, `evals/` cards + judges.
- E2E: `testing/e2e/` (63 tests, `python -m unittest discover -s testing/e2e -t .`).
