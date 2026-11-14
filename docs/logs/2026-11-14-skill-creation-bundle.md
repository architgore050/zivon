# 2026-11-14 — skill-creation bundle + tested discovery toolkit

## Done

- Added `skills/skill-creation/`: a generic meta-skill for finding, evaluating,
  adapting, writing, testing, and maintaining agent skills. Entry point is
  `SKILL.md`; depth lives in nine references and four templates.
- Ran a real discovery survey (56 catalogued sources, all touched on this date).
  What worked: `npx skills find/add` (lockfile SHA-256), the official MCP
  registry API, SkillAgent, findskills, skills.sh sitemaps, GitHub repo/code
  search, HN Algolia, npm, PyPI JSON. What failed: Google/DuckDuckGo/Bing HTML,
  Reddit JSON, PyPI search UI (CAPTCHA), PulseMCP/mcpservers curl (403), Cursor
  Directory curl (429 Vercel checkpoint), Smithery search (500).
- Tested the fallback stack for real: Playwright headless (PulseMCP 403→200,
  Cursor 429→200), Playwright MCP over stdio (31 tools, navigate+snapshot in
  4.0 s), `playwright-stealth` (no gain on PyPI/Google), `cloudscraper`
  (mcpservers.org 403→200, PyPI still blocked).
- Wrote `scripts/check_skills.py` (stdlib): frontmatter/name/description, links,
  secrets/PII, placeholders, body length, reference mentions, duplicate names;
  default scan warns on legacy/flat layouts, `--strict --bundle` is the opt-in
  gate. Added 20 unit tests under `testing/skills/` with good/bad fixtures.
- Wired CI: validator step in `quality`; `testing/skills` joins the path-guarded
  test loop. Updated `AGENTS.md`, root `README.md`, new `skills/README.md`, and
  `testing/README.md`.

## Not done / notes

- PyPI search remains CAPTCHA-blocked; the catalog points at the JSON API.
- Smithery search returned 500 throughout; its list endpoint works.
- Glama HTML `?q=` relevance was poor; its API needs a key.
- The security percentages in the bundle are from published studies, not our
  own scan; they are cited as order-of-magnitude warnings.
- `openai/skills` is deprecated (README) — Codex now points at
  `developers.openai.com/codex/build-skills` and `openai/plugins`.

## Next

- Re-run the catalog refresh quarterly (or when a registry changes status) and
  bump `metadata.evidence_date`.
- If a future agent installs a third-party skill, require the audit template and
  the strict validator before merge.
