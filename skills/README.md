# Skills

Agent skill bundles used in this repo. Each folder is self-contained: a
`SKILL.md` (or a suite of them) plus references, templates, and sometimes
scripts. Read a bundle's own README before using it — that README is the source
of truth for its layout and rules; root `README.md` and `AGENTS.md` point here
and stay abstract.

| Bundle | What it is for | Entry point |
|---|---|---|
| [`skill-creation/`](skill-creation/) | Finding, evaluating, adapting, writing, testing, and maintaining skills for **any** domain; tested discovery toolkit + dated source catalog + validator | [`skill-creation/SKILL.md`](skill-creation/SKILL.md) |
| [`code-review/`](code-review/) | The agentic review suite: one orchestrator + seven specialist lenses (architecture, implementation, security, tests, docs-sync, production-readiness, content-quality) | [`code-review/code-review/SKILL.md`](code-review/code-review/SKILL.md) |
| [`prompting-and-agent-design/`](prompting-and-agent-design/) | Current-era prompting and agent-graph rules for the content factory and voice tutor (goal-first, contracts, harness vs prompt) | [`prompting-and-agent-design/SKILL.md`](prompting-and-agent-design/SKILL.md) |
| [`content-creation/`](content-creation/) | Build-in-public post skills (LinkedIn/X interviewers, photo/video edit directors, shared theme + tool lessons) | [`content-creation/README.md`](content-creation/README.md) |
| [`zivon-product-design-skills/`](zivon-product-design-skills/) | Feature decision + granular spec method (original skill + vendored PM skills) | [`zivon-product-design-skills/skills/zivon-product-design/SKILL.md`](zivon-product-design-skills/skills/zivon-product-design/SKILL.md) |
| [`zivon-systems-design-skills/`](zivon-systems-design-skills/) | Backend/DB/storage-tiering stage-2 spec method (original skill + vendored engineering skills) | [`zivon-systems-design-skills/skills/zivon-systems-design/SKILL.md`](zivon-systems-design-skills/skills/zivon-systems-design/SKILL.md) |
| [`zivon-audio-engineering-skills/`](zivon-audio-engineering-skills/) | Audio discipline for the realtime voice loop and build-time narration (flat skill: `README.md` carries the frontmatter) | [`zivon-audio-engineering-skills/README.md`](zivon-audio-engineering-skills/README.md) |
| [`zivon-backend-engineering-skills/`](zivon-backend-engineering-skills/) | Perishable backend ops: Alembic, Postgres durability, quota guards, rate limits, Job/CronJob semantics (flat skill) | [`zivon-backend-engineering-skills/README.md`](zivon-backend-engineering-skills/README.md) |
| [`zivon-frontend-product-skills/`](zivon-frontend-product-skills/) | **Full frontend implementation entry point**: Field Notes public pages and generated lessons, static/SSR split, app shell, auth, dashboard, lesson shell, practice, speaking, tests/series, progress, SWOT, settings, admin, the 11-state matrix, a11y/perf/SEO, and the founder visual-verdict protocol | [`zivon-frontend-product-skills/SKILL.md`](zivon-frontend-product-skills/SKILL.md) |
| [`zivon-frontend-skills/`](zivon-frontend-skills/) | SEO reference only (technical SEO, metadata, sitemaps, structured data, Core Web Vitals); the implementation entry point is `zivon-frontend-product-skills/` | [`zivon-frontend-skills/seo-optimization.md`](zivon-frontend-skills/seo-optimization.md) |
| [`zivon-pipeline-engineering-skills/`](zivon-pipeline-engineering-skills/) | Content-factory engineering: stage contracts, artifacts/resume, gate/catcher design, quality/evals, rendering/publishing, and logging | [`zivon-pipeline-engineering-skills/SKILL.md`](zivon-pipeline-engineering-skills/SKILL.md) |

## Validate

```bash
# scan everything; legacy/flat layouts warn, they do not fail
python3 scripts/check_skills.py

# strict gate for a bundle that opts in
python3 scripts/check_skills.py --strict --bundle skills/skill-creation

# the validator's own tests
python -m unittest discover -s testing/skills -t .
```

The validator is stdlib-only (`scripts/check_skills.py`). It checks frontmatter,
description presence/length, name rules, relative links, secrets/PII,
placeholders, body length, reference mentions, and duplicate names. It is not a
quality review: use `skills/skill-creation/references/evaluation-rubric.md` for
that.

## Adding a bundle

Follow the repo's build rules: a folder README (layout source of truth), a
`SKILL.md` at the entry point (or a suite with one per skill), references under
`references/`, executable helpers under `scripts/`, and templates under
`templates/`. Add a row above and update root `README.md` / `AGENTS.md` in the
same PR. New bundles should pass the strict validator.
