# Search playbook

Reusable recipes for finding skills, MCP servers, prompts, and agent workflows.
Every command below was run on **2026-11-14** unless marked otherwise; the
measured results are in [source-catalog.md](source-catalog.md) and
[web-interaction-toolkit.md](web-interaction-toolkit.md).

## 1. Start from the need, not from the keyword

Write the need as a sentence, then extract four kinds of terms:

| Slot | Question | Example (need: "check a physics lesson for factual errors") |
|---|---|---|
| Object | What is being worked on? | lesson, textbook chapter, PDF, source pack |
| Verb | What must happen? | verify, fact-check, review, cite |
| Domain words | What would an expert call it? | misconception, citation, curriculum, NCERT |
| Format words | What package might contain it? | skill, SKILL.md, agent skill, prompt, workflow, MCP server |

Then generate variants: synonyms (`fact-check` / `verify` / `review`), adjacent
ecosystem names (`claude skill`, `codex skill`, `opencode skill`, `cursor
rules`), and artifact names (`SKILL.md`, `AGENTS.md`, `CLAUDE.md`, `.cursorrules`,
`mcp server`, `plugin`, `prompt template`).

A query that names the *tool* ("pdfplumber skill") usually beats one that names
the *goal* ("document skill"). Try both.

## 2. The tiered search order

Cheapest and most trustworthy first. Stop when you have 5–10 candidates, not
when you have one.

1. **Official docs/spec/repo** for the format and for first-party skills.
2. **Structured registries** (APIs/CLI): skills.sh CLI, official MCP registry,
   SkillAgent, findskills.
3. **Curated directories** (HTML): Glama, mcp.so, PulseMCP.
4. **GitHub** topic/repo/code search and awesome lists.
5. **Package registries**: npm, PyPI JSON.
6. **Community**: Hacker News, blogs, papers.
7. **Built-in web search** for the long tail and for things the above index
   badly (practitioner posts, issue threads).

## 3. Registry recipes (copy-paste)

### Skills

```bash
# skills.sh index, ranked by installs (human output)
npx skills find "pdf extraction"
npx skills find "physics tutor"
npx skills find "skill creation"

# install one skill into a throwaway project and inspect it
mkdir -p /tmp/skill-trial && cd /tmp/skill-trial
npx skills add anthropics/skills --skill skill-creator -a opencode -y
cat skills-lock.json        # source + SHA-256 per skill
sed -n '1,80p' .agents/skills/skill-creator/SKILL.md
```

```bash
# SkillAgent: JSON with stars, license, lastUpdated
curl -s 'https://skillagent.dev/api/skills?q=physics&limit=10' | jq '.total, .skills[] | {name,repo,stars,license,lastUpdated}'

# findskills: JSON search; full fields need a free key
curl -s 'https://findskills.org/api/v1/search?q=pdf' | jq '.skills[] | {name,description,safety_label}'
```

```bash
# Complete skills.sh index (robots-allowed sitemaps):
curl -s https://www.skills.sh/sitemap.xml
curl -s https://www.skills.sh/sitemap-skills-1.xml | grep -o '<loc>[^<]*' | wc -l   # 10000
curl -s https://www.skills.sh/sitemap-skills-2.xml | grep -o '<loc>[^<]*' | wc -l   # 10000
```

Do **not** scrape `skills.sh/search` or `/api/`; robots.txt disallows them. Use
the CLI or the sitemap.

### MCP servers

```bash
# Official registry: canonical, no auth
curl -s 'https://registry.modelcontextprotocol.io/v0/servers?search=pdf&limit=5' \
  | jq '.servers[].server | {name,description,version}'

# Glama: largest index, HTML search (API needs a key)
curl -s 'https://glama.ai/mcp/servers?q=pdf' | grep -o '/mcp/servers/[^"]*' | head

# Smithery: list works, text search 500s (2026-11-14)
curl -s 'https://registry.smithery.ai/servers?pageSize=20' | jq '.servers[]? | {qualifiedName,description}'

# mcp.so: sitemap sections for bulk discovery
curl -s 'https://mcp.so/sitemap.xml?section=servers' | grep -o '<loc>[^<]*' | wc -l
curl -s 'https://mcp.so/sitemap.xml?section=skills'  | grep -o '<loc>[^<]*' | wc -l
```

### Packages (tooling, not skills)

```bash
curl -s 'https://registry.npmjs.org/-/v1/search?text=agent%20skills&size=10' \
  | jq '.objects[].package | {name,version,description}'
curl -s 'https://pypi.org/pypi/skills-ref/json' | jq '.info | {name,version,summary,license}'
```

## 4. GitHub recipes

### Repo search (no token: 10 req/min; token: 30 req/min)

```bash
# topic + star sort
curl -s 'https://api.github.com/search/repositories?q=topic:agent-skills&sort=stars&order=desc&per_page=20' \
  | jq '.total_count, (.items[] | {full_name,stargazers_count,pushed_at,license:.license.spdx_id})'

# recent + specific, better than star-sorted for maintenance
q='topic:agent-skills pushed:>2026-08-01 archived:false'
curl -s "https://api.github.com/search/repositories?q=$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "$q")&sort=updated" \
  | jq '.items[] | {full_name,pushed_at,description}'

# find repos that are themselves skill bundles
curl -s 'https://api.github.com/search/repositories?q=%22SKILL.md%22+in:readme&sort=updated&per_page=10'
```

### Code search (token required: 10 req/min)

```bash
# exact skill names
q='"name: skill-creator" in:file filename:SKILL.md'

# all skill entry points under a skills/ path
q='path:skills filename:SKILL.md'

# skills that declare tool permissions
q='filename:SKILL.md "allowed-tools:"'

# skills that declare a license (proxy for redistribution care)
q='filename:SKILL.md "license:"'

# OpenCode-specific mentions
q='filename:SKILL.md "opencode"'
```

Measured totals on 2026-11-14: 13,008 for the first query; 6,995,968 for
`filename:SKILL.md "name:"`; 1,986,560 for `path:skills filename:SKILL.md`;
580,608 for `allowed-tools:`; 1,112,064 for `license:`; 110,208 for `opencode`.
The huge totals are why code search is for **finding exact files**, not for
ranking quality.

Useful qualifiers: `in:file`, `in:path`, `path:`, `filename:`, `language:`,
`repo:`, `org:`, `user:`, `topic:`, `stars:>100`, `pushed:>YYYY-MM-DD`,
`archived:false`, `license:mit`.

### Awesome lists

```bash
curl -s https://raw.githubusercontent.com/ComposioHQ/awesome-claude-skills/master/README.md | head -100
curl -s https://raw.githubusercontent.com/VoltAgent/awesome-agent-skills/main/README.md | grep -i -A2 'skill'
```

Awesome lists are indexes, not audits. Follow every entry to its repo before
trusting the description.

## 5. Query patterns by intent

| Intent | Queries that worked | Where |
|---|---|---|
| Find a skill that does X | `npx skills find "X"`; `skillagent.dev/api/skills?q=X`; `"X" skill SKILL.md` | skills.sh, SkillAgent, code search |
| Find an MCP server for X | `registry.modelcontextprotocol.io/v0/servers?search=X`; `glama.ai/mcp/servers?q=X`; `site:github.com "MCP server" X` | official registry, Glama, GitHub |
| Find a Claude/Codex/OpenCode skill | `"claude skill" X`, `"codex skill" X`, `filename:SKILL.md "opencode"`, `topic:claude-skills` | web search, code search, topics |
| Find a prompt library | `X prompt library`, `X prompt template`, `site:github.com prompts X`, `langsmith prompt hub X` | web search, LangChain docs |
| Find an agent workflow | `X agent workflow`, `X playbook`, `"agent skills" X`, `awesome X agents` | web search, awesome lists |
| Find a meta-skill (skill for making skills) | `skill creator`, `writing skills SKILL.md`, `skill-authoring`, `agent skills best practices` | anthropics/skills, spec site, search |
| Find a skill for a niche tool | `"<tool> skill"`, `"<tool> SKILL.md"`, `"<tool> claude"`, `topic:<tool>` | code search, GitHub |
| Find what changed / what is current | `"<thing> 2026"`, `changelog`, `deprecated`, repo `pushed_at` | web search, GitHub API |

Query-shaping rules that repeatedly paid off:

- Put the rarest token first (`pdfplumber`, not `document`).
- Add the artifact name (`SKILL.md`, `AGENTS.md`, `marketplace.json`) when you
  want files, and the ecosystem name when you want directories.
- Search the error message or API endpoint verbatim; issue threads often name
  the exact skill or workaround.
- Try the singular and plural, and the vendor's spelling (`OpenCode` vs
  `opencode`).
- Use `site:` only in the built-in search tool; it is not supported by the
  registry APIs.

## 6. Fallback ladder for JS-heavy or bot-protected pages

Stop at the first rung that returns the content. Do not jump to stealth tooling
for a page that has an API.

| Rung | Method | When | Tested example |
|---|---|---|---|
| 0 | Look for an API/JSON endpoint or `llms.txt` | Always try first | `registry.modelcontextprotocol.io/openapi.json` 200 |
| 1 | `webfetch` (HTML → markdown) | Static docs, specs, blogs | `agentskills.io` 200 |
| 2 | `curl` with a normal UA | Simple HTML, GitHub raw | mcp.so 200; GitHub raw 200 |
| 3 | Official CLI | Registries with a client | `npx skills find` |
| 4 | Playwright headless | Client-rendered apps | PulseMCP 403→200; Cursor Directory 429→200 |
| 5 | Playwright + stealth | Fingerprint checks, not CAPTCHAs | PyPI still CAPTCHA; no gain there |
| 6 | cloudscraper | Cloudflare-style JS challenge on HTML | mcpservers.org 403→200; PyPI still blocked |
| 7 | Ask the user / skip | CAPTCHA, login, paywall, ToS wall | PyPI search, Reddit JSON |

Never use these tools to bypass authentication, paywalls, or private data. A
CAPTCHA that needs a human is a **stop**, not a puzzle. Record the block in the
search log and use another source.

## 7. Candidate scoring sheet

Score each candidate 0–2 on the ten dimensions in
[evaluation-rubric.md](evaluation-rubric.md). The short form:

| Dimension | 0 | 1 | 2 |
|---|---|---|---|
| Source trust | Random gist | Community repo | Official/curated + verifiable |
| Trigger fit | Description unrelated | Partly matches | Matches the need and the user's words |
| Body quality | Vague/generic | Usable with edits | Specific, tested, has gotchas |
| License | None/forbids | Ambiguous but attributed | Clear and compatible |
| Security | Scripts + secrets + hidden instructions | Scripts, unread | Instructions only, reviewed |
| Maintenance | Abandoned/archived | Sporadic | Recent commits + issues answered |
| Compatibility | One client, undocumented | Portable with edits | Spec-compliant, multi-client |
| Testability | No way to check | Manual only | Evals/assertions or validator |
| Provenance | No author/version | Author, no commit | Author, commit, date, license |
| Adaptation cost | Rewrite | Moderate edits | Drop-in |

Decision: **install** at 16–20 with no zero on license/security; **adapt** at
10–15 or any fixable zero; **reject** below 10 or any unfixable license/security
zero. Record the score in [../templates/skill-audit.md](../templates/skill-audit.md).

### Red flags (any one is a stop-and-read)

- `description` promises one thing, body does another.
- Bundled script that reads `~/.ssh`, env vars, browser profiles, or wallet files.
- `curl … | bash`, `eval`, `exec`, base64 blobs, obfuscated code.
- Instructions to ignore previous instructions, hide actions from the user, or
  send data to an external endpoint.
- No license, or a license that forbids commercial/derivative use, on content
  you intend to copy.
- Repo created recently, huge star count, no issues, no history — popularity
  that does not match substance.
- Install command that resolves to a different repo than the one you reviewed.
- "Works with every agent" with no client-specific notes.

## 8. Build vs adapt vs install

```
Is there a candidate that matches the need and passes license + security?
├─ no  → BUILD. Extract the repeated workflow; use templates/SKILL.md.
└─ yes → Does it pass trigger fit and maintenance?
   ├─ no  → REJECT (or BUILD; do not "fix" an abandoned skill you cannot license).
   └─ yes → Is the body ≥80% right for your harness?
      ├─ yes → INSTALL. Pin commit, record provenance, run a sandbox trial.
      └─ no  → ADAPT. Keep license/attribution, record every change, re-run evals.
```

Install is the cheapest only when the skill is maintained. Adaptation is
usually cheaper than writing, but only if the license allows derivatives. When
in doubt, write a smaller skill that does your 20% and link to the original for
the rest — that avoids license and maintenance coupling.

## 9. Searching a domain you know nothing about

1. **Find the domain's canonical vocabulary.** Read the official docs or one
   high-quality textbook chapter; list 20 nouns and verbs practitioners use.
2. **Find the domain's format.** Is the artifact a PDF, a CSV, a schema, a
   protocol, a UI? Format words are the strongest search keys.
3. **Find the domain's incumbent tools.** Search `<tool> skill`, `<tool> MCP
   server`, `<tool> plugin`. Tool vendors often publish first-party skills.
4. **Find the domain's failure modes.** Search `<task> mistakes`, `<task>
   checklist`, `<task> postmortem`. These become the skill's gotchas, which are
   the highest-value content.
5. **Find the domain's regulators/standards.** For anything with legal,
   medical, financial, or safety impact, the standard is the source of truth;
   community skills are not.
6. **Ask a practitioner-shaped question in search**: "what does a good <task>
   look like", "how do experts review <artifact>". Then verify names/claims
   against a primary source.
7. **Only then** search for a skill. You will recognize a good one because you
   now know what "good" means.

Time-box: 30–45 minutes of domain orientation before writing anything. A skill
written without it will be generic, which is the failure mode the spec's best
practices call out explicitly.

## 10. Keeping the search auditable

Log every query, every source, every candidate, and every dead end in
[../templates/search-log.md](../templates/search-log.md). A second agent should
be able to resume the search without repeating it. Include:

- date/time and method (API/CLI/curl/fetch/PW/search),
- exact URL or command,
- HTTP status or CLI exit,
- what was relevant, what was blocked, what was stale,
- candidate score and decision.

This is also how the source catalog improves: a dead end recorded once is not
re-explored next quarter.
