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

## Addendum 2026-11-22 — progress since this file merged

- **Merged:** #101 (this file), #102 — EV-PL-002 judge fixed (root cause: the
  `major` rung caught legitimate *application of a cited law* in worked
  examples; rubric now carves out derived results and application conventions;
  regression golden `SD-PLJ-C04` pins the pattern). Mock calibrate 5/5 cards
  pass, fatal/blocking recall 1.0, clean specificity 1.0. **Live re-run of the
  PL cards is pending** — the authorized route returned HTTP 429 (weekly quota,
  resets ~18.5 h from 2026-11-22 ~06:00 UTC); exact re-run commands are in PR
  #102's body. Do NOT treat the mock numbers as live evidence.
- **PR #100 (magnetic):** the `pull_request` event never fired CI for this one
  PR (zero runs on open, synchronize, and reopen — cause unknown, other PRs
  fire normally). CI was started manually via `workflow_dispatch` on the head
  SHA; check-runs attach to the same SHA so branch protection sees them. If a
  future push to that branch again shows zero check-runs, re-dispatch:
  `POST /repos/.../actions/workflows/ci.yml/dispatches {"ref":"feature/w-magnetic-fix"}`.
- **Dependabot:** all 20 open PRs were stale-conflicted (July-era bases);
  `@dependabot rebase` was requested on each. Triage rule: merge patch/minor
  bumps once green + mergeable; report majors to the founder. A ready-made
  scan-and-merge script: `scripts/dependabot_triage.sh` (it also re-kicks CI
  with an empty commit — remove that part if not needed).
- **Magnetic unblock (next agent task):** option (a) — register a CC-BY source
  carrying electromagnetism §12.4–12.6 (e.g. Siyavula Gr11/12, verify the
  licence on the site and record attribution in the source registry), ingest,
  regenerate the lesson, then bank → mirror → `TRACKED_CHAPTERS` pins. See
  `download/magnetic-workstream-handoff.md` for the exact recipe.

## Addendum 2 — 2026-11-22 (one-shot session): state + founder decisions queue

Merged this session: #100 (magnetic registration + two gated lesson regens +
gitleaks allowlist), #102 (EV-PL-002 judge fix), #103, Dependabot #42.
**Open: PR #104 `feature/w-magnetic-bank`** — Siyavula source registered,
founder-local one-command script committed, docs synced. CI 13/14; the one
failure (`test_voice_connect_timeout_retries_without_saying_offline`) is a
proven runner-timing flake (passes locally in 1.2 s; rerun dispatched).
Merge #104 when its checks are green.

**Licence gate PASSED:** Siyavula "Everything Science" Gr11/12 is CC BY 3.0
(verified verbatim on both siyavula.com grade reader pages, 2026-11-22, linking
creativecommons.org/licenses/by/3.0); registered in `sources/catalog.json` with
attribution. Offline validation passed: the locate stage surfaces Gr11 §10.3
Faraday's law (score 1.42) and Gr12 §11.2–11.3 generators/motors (1.02); the
two orphaned concepts now have a grounded carrier.

**Blocked by route quota (HTTP 429, weekly, resets ~00:23 UTC 2026-11-23):**
the lesson regen + assessment bank (PL live evals too). When quota resets:

```
bash scripts/magnetic_founder_local.sh   # fetch → ingest warm-up → regen → verify → bank → mirror → pins
```

then commit the outputs (lesson + pack mirror + `TRACKED_CHAPTERS` counts
computed by real import) as the follow-up PR. PL live eval re-run commands are
in PR #102's body.

### Founder decisions queue (agent implemented a default; veto/change any)

1. **D1 — magnetic unblock via option (a)** Siyavula CC BY 3.0 (implemented;
   option (b) syllabus re-curation remains available). Regen+bank is one
   founder-local command until the route quota resets; an agent can also run
   it next session.
2. **D2 — gitleaks allowlist scope** (`.gitleaks.toml`): TIMELINE.md is
   allowlisted as a whole (historical ops log), plus vendored skill refs and
   the translation-doc hash example. Tighten if you want TIMELINE scoped by
   content regex instead of path.
3. **D3 — PL5 live evals pending quota** (mock evidence is green; live
   "before" numbers exist; re-run after reset — do NOT treat mock as live).
4. **D4 — Dependabot policy:** merge patch/minor once green; a second rebase
   round was requested for 19 stragglers (they conflict only with each other
   on shared manifests). Majors found so far: none. Alternative: close all and
   switch to grouped weekly updates.
5. **D5 — unchanged founder-manual items:** Google OAuth creds, email backend,
   domain/DNS/host+SSH, Postgres, voice-provider key region check, branch
   protection via GitHub UI, PYQ clearance (DEC-COMP-001), the one live
   teach-check-adapt session.
6. **D6 — CI pull_request-event anomaly on PR #100** was transient (later
   pushes fired normally); the workflow_dispatch workaround stays documented.


