# Source catalog — agent-skill and MCP discovery

Last full verification: **2026-11-14** (UTC). Every row was touched on that date
unless it says "listed only". Method codes match
[web-interaction-toolkit.md](web-interaction-toolkit.md):

- **API** — JSON endpoint read with `curl`
- **CLI** — official command-line client
- **CURL** — raw HTTP fetch
- **FETCH** — agent `webfetch` (HTML → markdown)
- **PW** — Playwright headless Chromium
- **PW-MCP** — Playwright MCP server over stdio
- **SEARCH** — the agent's built-in web search tool (engine not exposed; treat
  results as leads, verify the linked primary source)
- **GH** — GitHub REST API

"Listed only" means the page was seen in search results but not exercised; do
not treat those rows as tested.

The same data is in [source-catalog.csv](source-catalog.csv) (one row per
source, same IDs).

---

## 1. Official specifications and documentation

| ID | Source | URL | Good for | Access tested | Auth / limits | License / provenance | Quality signal | Caveats |
|---|---|---|---|---|---|---|---|---|
| SRC-001 | Agent Skills specification | https://agentskills.io/specification | Normative format: fields, constraints, progressive disclosure, validation | FETCH 200; `llms.txt` 200 | None | Open standard; site claims community-maintained | **Highest** — the reference the clients implement | Client behaviour still varies; spec is not enforcement |
| SRC-002 | Agent Skills best practices | https://agentskills.io/skill-creation/best-practices | Scoping, context economy, calibration, gotchas, templates, validation loops | FETCH 200 | None | Same as SRC-001 | High — practitioner guidance with concrete examples | Advice, not rules; test against your own agent |
| SRC-003 | Evaluating skill output quality | https://agentskills.io/skill-creation/evaluating-skills | Eval design: prompts, baselines, assertions, benchmark deltas, iteration loop | FETCH 200 | None | Same as SRC-001 | High — the only formal eval method found | Requires a runner that can isolate runs; no built-in harness |
| SRC-004 | Optimizing skill descriptions | https://agentskills.io/skill-creation/optimizing-descriptions | Trigger-rate testing and description wording | Listed only (index) | None | Same as SRC-001 | Medium-high | Not read in full; verify before quoting |
| SRC-005 | Anthropic Agent Skills overview | https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview | Claude's loading model, field limits, reserved names, description rules | SEARCH result; content quoted in results | None | Anthropic docs, all rights reserved | High for Claude behaviour | Product docs, not the neutral spec |
| SRC-006 | Anthropic skill authoring best practices | https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices | Description writing, third-person rule, naming, structure | SEARCH result | None | Anthropic docs | High | Claude-specific framing |
| SRC-007 | Anthropic skills repository | https://github.com/anthropics/skills | 19 reference skills incl. `skill-creator`, `mcp-builder`, `webapp-testing` | GH 200; raw files 200 | GitHub API 60/h unauth, 5,000/h auth | **No license field** (`license: null`); README points to per-skill terms | 194,238 stars; pushed 2026-11-06 | No repo-wide license — do not assume MIT; check each folder |
| SRC-008 | `skill-creator` skill | https://github.com/anthropics/skills/tree/main/skills/skill-creator | The most complete public skill-authoring workflow: interview, eval loop, description optimizer | CURL raw `SKILL.md` 200 (33 KB) | None beyond GitHub | See SRC-007; skill folder carries `LICENSE.txt` | Battle-tested by installs; 229K installs for sibling `pdf` | Very long; opinionated toward Claude Code subagents |
| SRC-009 | OpenCode skills docs | https://opencode.ai/docs/skills (V1) and https://opencode.ai/v2/docs/skills | Discovery paths, IDs, precedence, HTTP catalogs, permissions | FETCH 200 both; V2 page is the same content | None | OpenCode docs | **Highest for OpenCode behaviour** | V1 URL is what search returns; V2 URL is authoritative for V2 |
| SRC-010 | OpenCode V2 docs index | https://opencode.ai/v2/llms.txt | Machine-readable index of V2 docs | CURL 200 | None | OpenCode docs | High | `llms.txt` still points the Skills entry at the V1 path |
| SRC-011 | Claude Code plugins overview | https://code.claude.com/docs/en/plugins/overview | Plugin/marketplace model: skills, agents, hooks, MCP bundled as one unit | SEARCH result | None | Anthropic docs | High | Plugin ≠ skill; a plugin can contain several skills |
| SRC-012 | Claude Code marketplace reference | https://code.claude.com/docs/en/plugins/marketplace-reference | `marketplace.json` shape, source types, reserved names | SEARCH result | None | Anthropic docs | High | Long; only needed when publishing a marketplace |
| SRC-013 | Anthropic official marketplace catalog | https://github.com/anthropics/claude-plugins-official/blob/main/.claude-plugin/marketplace.json | 317 plugin entries with sources | CURL 200; JSON parsed | None | Anthropic repo | High | Catalog is a list, not a quality review |
| SRC-014 | OpenAI Codex build-skills docs | https://developers.openai.com/codex/build-skills | Codex skill locations (`.agents/skills`), system skills, plugins, `agents/openai.yaml`, context budget | FETCH 200 | None | OpenAI docs | **Highest for Codex behavior** | Product docs; standalone skills vs plugin distribution |
| SRC-015 | OpenAI `skills` repo (deprecated) | https://github.com/openai/skills | Historical curated/system/experimental skills | GH 200; README 200 | GitHub API limits | No repo-level license; per-skill `LICENSE.txt` | 28,732 stars; README says **deprecated** | Superseded by `openai/plugins`; do not build new work on it |
| SRC-016 | MCP specification | https://modelcontextprotocol.io | Protocol truth for servers/transports | CURL 200 | None | MCP project | Highest for MCP | Not a skill format |
| SRC-017 | Official MCP Registry docs | https://registry.modelcontextprotocol.io/docs | API reference (Stoplight page) | CURL 200 | None for reads | MCP project | High | Docs page is JS-rendered; OpenAPI JSON is easier |
| SRC-018 | Cursor rules docs | https://cursor.com/docs/context/rules | Cursor's own rule format: `.cursor/rules/*.mdc`, frontmatter, AGENTS.md | FETCH 200 | None | Cursor docs | **Highest for Cursor rules** | Cursor rules are **not** `SKILL.md`; skill support in Cursor comes from the shared `.agents/skills` convention, which Cursor's own rules page does not document |
| SRC-019 | OpenAI plugins build docs | https://developers.openai.com/plugins/build/plugins | Packaging skills for distribution in Codex/ChatGPT | Listed in SRC-014 | None | OpenAI docs | High | Listed only on this pass |

## 2. Skill registries and directories

| ID | Source | URL | Good for | Access tested | Auth / limits | License / provenance | Quality signal | Caveats |
|---|---|---|---|---|---|---|---|---|
| SRC-020 | skills.sh directory | https://www.skills.sh | Largest install-ranked skill index; leaderboard, official section, audits | FETCH 200; sitemap 200; **CLI tested** | robots disallows `/search`, `/api/`, `/internal/`, `/debug-security/`; use the CLI | Vercel-operated index; per-skill licenses vary | 20,000 skill URLs + 18,049 owner URLs in sitemaps | Install counts are telemetry, not quality; directory says it cannot guarantee safety |
| SRC-021 | `skills` CLI (`npx skills`) | https://github.com/vercel-labs/skills | Search, install, update, lockfile with SHA-256 per skill | CLI tested: `find`, `add` | Node 22.20+; no key for public skills | MIT (repo) | 39,275 stars; installs to `.agents/skills` + `skills-lock.json` | `find` has no `--json` in 1.8.1; output is human text |
| SRC-022 | findskills.org | https://findskills.org | 117k-skill index with safety labels; JSON search | API `GET /api/v1/search?q=physics` → 200 | No key for search; full fields need free key | Unknown site license; per-skill varies | Returns `safety_label`, category | Without key, records are truncated with a hint; safety label is not an audit |
| SRC-023 | SkillAgent | https://skillagent.dev | 15k skills/rules/MCP indexed from GitHub; JSON + MCP | API `/api/skills?q=physics&limit=3` → 200; MCP `POST /mcp` → 200 | Rate limited per IP; no auth seen | Unknown; per-skill licenses in records | Returns stars, license, `lastUpdated`, format, score | Score is heuristic metadata, not security |
| SRC-024 | SkillFed | https://skillfed.io/skills | Deduplicated skill index with MCP `find_skills` | CURL 200 | Unknown; site advertises MCP | Unknown | Claims 56,283 unique skills | Not deeply exercised; verify counts |
| SRC-025 | skillsadd.com | https://skillsadd.com | Install-ranked mirror of the ecosystem | SEARCH result only | Unknown | Unknown | Shows install counts | **Listed only**; likely derivative of skills.sh telemetry |
| SRC-026 | SkillGuide | https://skillguide.ai | Directory of skills, MCP servers, plugins | SEARCH result only | Unknown | Unknown | Weekly update claim | **Listed only**; ranks by repo stars, not installs |
| SRC-027 | Claude Marketplace | https://claude.com/marketplace | Anthropic's web catalog with install counts and verification marks | PW 200; cookie banner | None | Anthropic | High for Claude ecosystem | Consent overlay; catalog JSON (SRC-013) is easier to parse |

## 3. MCP registries and directories

| ID | Source | URL | Good for | Access tested | Auth / limits | License / provenance | Quality signal | Caveats |
|---|---|---|---|---|---|---|---|---|
| SRC-030 | Official MCP Registry API | https://registry.modelcontextprotocol.io/v0/servers | Canonical server records with remotes, versions, publish status | API 200; `?search=pdf&limit=5` 200 | **No auth** for reads | MCP project; registry data | **Highest for MCP** | Schema is versioned (`2025-12-11`); v0 API may change |
| SRC-031 | Smithery | https://smithery.ai | Server catalog + hosted connector metadata | PW 200; `registry.smithery.ai/servers?pageSize=2` 200; `?q=` → **500** | None for list; search broken | Site terms | 20,769 entries claimed elsewhere | Search returns 500 on 2026-11-14; banner says MCP Proxy shut down Oct 31 |
| SRC-032 | Glama | https://glama.ai/mcp/servers | 120,903-server index with attributes, connectors, API | CURL `?q=pdf` 200; API `/api/mcp/v1/*` 302/401 | API needs Bearer key; docs say 100 req/s | Glama terms; attribution required for API data | Largest measured index; daily updates | HTML relevance for `?q=` looked poor; API is the reliable path |
| SRC-033 | PulseMCP | https://www.pulsemcp.com | Curated server directory + newsletters | CURL **403**; PW 200 (9.5 KB text, 109 pdf hits) | None for HTML; API legacy retired/key-gated | PulseMCP terms | 21,540+ servers shown | Listing submissions paused per banner; plain curl blocked |
| SRC-034 | mcp.so | https://mcp.so | Server + skill directory; sitemaps for bulk discovery | CURL 200; sitemap sections 200 | None | mcp.so terms | Server sitemap returns 1,000 URLs on the first page (pagination not documented); 268 skill URLs | No JSON API found; search is client-side; a third-party measurement claims 19,217 servers overall |
| SRC-035 | mcpservers.org | https://mcpservers.org | "Awesome MCP Servers" list with topics | CURL **403**; PW 200 (1 KB shell); cloudscraper 200 (58 KB) | None | Community list | Broad list | Search is form-driven; direct query URLs do not render results |
| SRC-036 | modelcontextprotocol/servers | https://github.com/modelcontextprotocol/servers | Reference server implementations | GH 200 | GitHub API limits | `NOASSERTION` (mixed per-folder licenses) | 91,977 stars; pushed 2026-11-12 | Reference implementations, not a skill library |
| SRC-037 | Smithery MCP registry API (base) | https://registry.smithery.ai/servers | List server records without auth | API 200 | None | Smithery terms | Structured JSON | `q` parameter 500s; pagination reportedly caps at 500 entries |
| SRC-038 | Glama directory API docs | https://glama.ai/mcp/reference | Auth, pagination, rate limits, data sources | CURL 200 | API key; 100 req/s | Attribution required | High — concrete contract | Requires an account for reads |

## 4. Code, awesome lists, and community

| ID | Source | URL | Good for | Access tested | Auth / limits | License / provenance | Quality signal | Caveats |
|---|---|---|---|---|---|---|---|---|
| SRC-040 | GitHub Topics: agent-skills | https://github.com/topics/agent-skills | Broad repo discovery | CURL 200 | None for HTML | Repo licenses vary | 43,040 repos via API `topic:agent-skills` | Topic pages are popularity-sorted and noisy |
| SRC-041 | GitHub Topics: claude-skills | https://github.com/topics/claude-skills | Claude-specific repos | CURL 200 | None | Varies | Active topic | `awesome-claude-skills` is **not** a valid topic (404) |
| SRC-042 | GitHub Topics: mcp-server | https://github.com/topics/mcp-server | MCP implementations | CURL 200 | None | Varies | Very large topic | Mixed quality |
| SRC-043 | GitHub code search API | https://api.github.com/search/code | Find exact `SKILL.md` patterns across repos | GH 200 with token | **Auth required**; 10 req/min | GitHub terms | 13,008 hits for `"name: skill-creator" in:file filename:SKILL.md` | Totals are approximate (6.9M for `filename:SKILL.md "name:"`); noisy |
| SRC-044 | GitHub repo search API | https://api.github.com/search/repositories | Filter by topic, stars, recency | GH 200 | 30 req/min auth, 10/min unauth | GitHub terms | 43,040 for `topic:agent-skills` | Star inflation and star-farming are real; sort by stars surfaces new, loud repos |
| SRC-045 | ComposioHQ/awesome-claude-skills | https://github.com/ComposioHQ/awesome-claude-skills | 1,000+ curated skills, categorized, with authors | GH listing via SEARCH | GitHub limits | Repo license not confirmed on page | 79,431 stars | Curated ≠ audited; links can rot |
| SRC-046 | VoltAgent/awesome-agent-skills | https://github.com/VoltAgent/awesome-agent-skills | 1,000+ skills from official teams/community | SEARCH result | GitHub limits | MIT | 37,157 stars | Bulk-list quality varies; verify each |
| SRC-047 | travisvn/awesome-claude-skills | https://github.com/travisvn/awesome-claude-skills | Categorized official + community list | SEARCH result | GitHub limits | Unknown | 15,809 stars | Smaller, older |
| SRC-048 | addyosmani/agent-skills | https://github.com/addyosmani/agent-skills | Production-grade engineering skills | GH 200 | GitHub limits | MIT | 117,244 stars; pushed 2026-11-14 | One author's opinionated set; still verify fit |
| SRC-049 | vercel-labs/agent-skills | https://github.com/vercel-labs/agent-skills | React/Next.js/web design skills | SEARCH + CLI results | GitHub limits | MIT (CLI repo; per-skill check) | High install counts on skills.sh | Framework-specific |
| SRC-050 | Hacker News Algolia API | https://hn.algolia.com/api/v1/search | Practitioner discussion, launches, critiques | API 200 | None observed | HN content | 544/376/364-point threads on Agent Skills | Opinion, not evidence; links may be stale |
| SRC-051 | GitHub topic: awesome-mcp-servers | https://github.com/topics/awesome-mcp-servers | MCP list repos | CURL 200 | None | Varies | Broad | Lists overlap heavily |
| SRC-052 | punkpeye/awesome-mcp-servers | https://github.com/punkpeye/awesome-mcp-servers | Canonical MCP awesome list (Glama cites it as a source) | Listed only | GitHub limits | Check repo | Widely mirrored | **Listed only** on this pass |

## 5. Package registries

| ID | Source | URL | Good for | Access tested | Auth / limits | License / provenance | Quality signal | Caveats |
|---|---|---|---|---|---|---|---|---|
| SRC-060 | npm registry search API | https://registry.npmjs.org/-/v1/search?text=agent%20skills | Find CLI/tooling packages (`skills`, `skills-ref`) | API 200 | None observed | Per-package | Found `skills@1.8.1`, `skills-ref@0.1.5` | Packages are tools, not skills; names are squattable |
| SRC-061 | PyPI JSON API | https://pypi.org/pypi/<package>/json | Verify a Python package's metadata/license | API 200 for `skills-ref` | None | Per-package | `skills-ref` 0.1.1, Apache-2.0 | **Search UI is CAPTCHA-blocked**; use JSON per known package |
| SRC-062 | `skills-ref` / `agentskills` validator | https://pypi.org/pypi/skills-ref/json | Official reference validator | Installed + run | None | Apache-2.0 | `agentskills validate` passes good skill, fails bad with named errors | Checks format only, not description quality or safety |

## 6. Adjacent ecosystems (rules, prompts, plugins)

| ID | Source | URL | Good for | Access tested | Auth / limits | License / provenance | Quality signal | Caveats |
|---|---|---|---|---|---|---|---|---|
| SRC-070 | Cursor Directory | https://cursor.directory/rules | Cursor rules and plugins | CURL **429** (Vercel checkpoint); PW 200 | None for browser | Site terms | 93.6k+ developers claimed | Plain HTTP blocked; browser works |
| SRC-071 | LangChain Hub / LangSmith Prompt Hub | https://docs.langchain.com/langsmith/prompt-context-hub | Prompt discovery | Docs SEARCH; old API `/prompts` → 404 | API needs key | LangChain terms | Established prompt ecosystem | API path changed; docs say treat pulled prompts as untrusted |
| SRC-072 | LlamaHub | https://llamahub.ai | LlamaIndex tools/integrations | CURL 200 (redirect notice) | None | LlamaIndex | Moved | Old hub retired; new location is developers.llamaindex.ai |
| SRC-073 | OpenAI plugins repo | https://github.com/openai/plugins | Codex skill/plugin examples (replacement for openai/skills) | Listed in SRC-015 README | GitHub limits | Check repo | Current OpenAI path | **Listed only** on this pass |

---

## What did **not** work (tested, failed, or blocked)

| Target | Method | Result on 2026-11-14 | What to do instead |
|---|---|---|---|
| Google web search | PW headless | `/sorry/index` "unusual traffic" | Use the built-in search tool (SRC: SEARCH method) |
| DuckDuckGo HTML | CURL + PW | 403 / 202 challenge | Use the built-in search tool |
| Bing HTML | PW | 200 but irrelevant results for a technical query | Use the built-in search tool; do not trust Bing HTML for code topics |
| Reddit search JSON | CURL | 403 | Use HN Algolia or the built-in search tool |
| PyPI search UI | CURL, PW, PW+stealth, cloudscraper | CAPTCHA / "Client Challenge" / JS-disabled page | `pypi.org/pypi/<pkg>/json` per known package |
| PulseMCP | CURL | 403 | Playwright, or its API with a key |
| mcpservers.org | CURL | 403 | cloudscraper or Playwright (list page only) |
| Cursor Directory | CURL | 429 Vercel Security Checkpoint | Playwright with a real browser UA |
| Smithery search API | CURL `?q=` | 500 | List endpoint + local filtering, or another registry |
| Glama read API | CURL | 401/302 without key | HTML directory, or request a key |
| mcp.so API | CURL | 404 on 3 guessed paths | HTML/sitemap |
| LangChain Hub old API | CURL | 404 | LangSmith docs / UI |
| LlamaHub | CURL | Redirect notice only | developers.llamaindex.ai |
| `npx skills find --json` | CLI | No JSON output in 1.8.1 | Parse human output or use skills.sh pages/CLI exit codes |
| GitHub code search (no token) | GH | 401 | Authenticate; 10 req/min budget |

## Trust hierarchy (use this order)

1. **Official spec/docs** (SRC-001…SRC-016): normative for format and client
   behaviour.
2. **First-party registries with structured data** (SRC-030, SRC-020/021,
   SRC-022/023): good candidates, still unverified.
3. **Curated marketplaces and awesome lists** (SRC-040…SRC-052): breadth;
   ranking signals are weak.
4. **Individual repos and blogs** (SRC-007, SRC-008, SRC-048): read the code and
   the history.
5. **Search snippets, social posts, aggregator scrapes**: leads only.

A source can be in tier 1 for *format* and tier 4 for *quality*: the official
spec tells you what a valid skill is, never whether a particular skill is good.
