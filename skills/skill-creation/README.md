# skill-creation (bundle)

A reusable method for **finding, evaluating, adapting, writing, testing, and
maintaining agent skills for anything** — not just this repo, and not just one
agent client.

It exists because discovery is the hard part. There are tens of thousands of
`SKILL.md` files, several competing directories, and no single trustworthy
index. Searching "the web" manually is slow, and registry search alone misses
most of the useful long tail. This bundle packages a tested search protocol, a
dated source catalog, a scoring rubric, and a validator so an agent can do the
whole loop without improvising it.

## Read order for an agent

1. This README (2 min) for layout and scope.
2. `SKILL.md` — the method. **Always.**
3. Open a `references/*` file only when the SKILL.md's reference map says the
   current step needs it.
4. Copy a `templates/*` file when you need an artifact (audit, search log,
   source entry, new skill).
5. Run `scripts/check_skills.py` before you call a skill done.

## Layout

```
skill-creation/
├── README.md
├── SKILL.md                     entry point: workflow, trust tiers, quality bar
├── references/
│   ├── source-catalog.md        dated catalog + what worked/failed
│   ├── source-catalog.csv       same catalog, machine-readable
│   ├── search-playbook.md       query patterns, GitHub/registry recipes, fallback ladder
│   ├── skill-format.md          Agent Skills spec + OpenCode/Claude/Codex differences
│   ├── evaluation-rubric.md     0–2 scoring, install/adapt/reject thresholds
│   ├── web-interaction-toolkit.md  tested stack: APIs → curl → Playwright → stealth
│   ├── provenance-and-licensing.md  what to record, copying vs adapting, no-license rule
│   ├── security-and-prompt-injection.md  threat model, scan list, sandbox protocol
│   └── maintenance.md           cadence, staleness triggers, versioning, deprecation
├── templates/
│   ├── skill-audit.md           filled-in scorecard for a candidate
│   ├── SKILL.md                 skill skeleton with description guidance
│   ├── search-log.md            resumable candidate log
│   └── source-entry.md          one catalog row with evidence fields
└── (validator lives at the repo root: `scripts/check_skills.py`)
```

The validator is repo-level on purpose: CI runs it, every bundle can share it,
and there is exactly one copy. It takes `--bundle <path>` so this bundle can be
gated strictly without touching legacy layouts.

## Quick start

```bash
# 1. validate this bundle (and any other strict bundle)
python3 scripts/check_skills.py --strict --bundle skills/skill-creation

# 2. scan the whole repo's skill folders without failing legacy layouts
python3 scripts/check_skills.py

# 3. run the validator's own tests
python -m unittest discover -s testing/skills -t .
```

Finding a skill, in one line each:

```bash
npx skills find "<capability>"                 # skills.sh index + install counts
curl -s 'https://registry.modelcontextprotocol.io/v0/servers?search=<q>&limit=5'
curl -s 'https://skillagent.dev/api/skills?q=<q>&limit=5'
curl -s 'https://findskills.org/api/v1/search?q=<q>'
```

Then read the candidate's `SKILL.md` before trusting any of it. The full
protocol, including GitHub code-search operators and the JS/bot-wall ladder, is
in `references/search-playbook.md`.

## Scope

**In scope:** skill discovery, source evaluation, format and triggering,
progressive disclosure, license and security review, adaptation, writing,
validation, provenance, maintenance, and the tooling to search for all of it.

**Out of scope:** implementing MCP servers (use an MCP-building skill), writing
ordinary documentation, and product-specific prompt design (this repo uses
`skills/prompting-and-agent-design/` for that).

## Evidence and maintenance

Every source claim in this bundle is dated **2026-11-14** and tagged with the
method used (API, curl, webfetch, Playwright, CLI). The catalog records what
failed as well as what worked — PyPI's search UI, Reddit's JSON endpoint,
Google's and DuckDuckGo's HTML endpoints, and several registry search APIs were
blocked or broken on that date. Re-check the perishable rows (limits, APIs,
directory status) before quoting them; the maintenance rules and review cadence
are in `references/maintenance.md`.

Security numbers cited in the bundle come from published research and vendor
audits, not from our own scan of the ecosystem: 26.1% of 31,132 analyzed skills
had at least one vulnerability in one 2026 study, and a Snyk audit of 3,984
skills found 36.8% with at least one flaw. Treat those as order-of-magnitude
warnings, not as a guarantee about any specific skill.

## License

Original text in this bundle is MIT, matching the other Zivon skill bundles.
Third-party sources are cited, not vendored; their licenses remain their own.
