# Skill format and portability

What a skill is, which fields matter, how the major clients differ, and how to
validate one. Sources: the Agent Skills specification and best-practices pages
(SRC-001…SRC-003), OpenCode V2 docs (SRC-009, SRC-010), Claude Code docs
(SRC-005, SRC-006, SRC-011, SRC-012), Codex docs (SRC-014), Cursor rules docs
(SRC-018), and the reference validator (SRC-062). Checked 2026-11-14.

## 1. The portable core (Agent Skills)

A skill is a **directory** whose entry point is `SKILL.md`:

```
my-skill/
├── SKILL.md          # required: YAML frontmatter + Markdown instructions
├── scripts/          # optional: executable code
├── references/       # optional: docs loaded on demand
├── assets/           # optional: templates, images, data
└── ...               # any other files the skill needs
```

### Frontmatter

| Field | Required | Constraints | Notes |
|---|---|---|---|
| `name` | yes | 1–64 chars; lowercase `a-z`, `0-9`, `-`; no leading/trailing hyphen; no `--`; must match directory name | The skill ID in most clients |
| `description` | yes | 1–1024 chars; non-empty; no XML tags | The only thing always in context; it decides triggering |
| `license` | no | Short name or reference to a bundled license file | Recommended whenever content is shared |
| `compatibility` | no | 1–500 chars | Environment requirements (client, packages, network) |
| `metadata` | no | map of string → string | Client-specific fields; keep keys namespaced |
| `allowed-tools` | no | Space-separated pre-approved tools | **Experimental**; support varies; not a security boundary |

Reserved-name rules in Claude: a skill name cannot contain `claude` or
`anthropic`, and cannot contain XML tags. Those rules exist because frontmatter
is injected into the system prompt.

### Body

No format restrictions. The spec recommends: step-by-step instructions,
input/output examples, edge cases. Keep the body **under 500 lines / ~5,000
tokens**; move detail into `references/` and tell the agent when to open it.

### Progressive disclosure

1. **Metadata** — `name` + `description`, always loaded (~100 tokens).
2. **Body** — loaded when the skill triggers (<5,000 tokens recommended).
3. **Resources** — read only when `SKILL.md` points to them.

The third level is where a skill can be large without costing context. The rule
that makes it work: every reference gets a **load condition**, not just a link.
"Read `references/api-errors.md` if the API returns non-200" beats "see
references/".

### Description: the highest-leverage sentence

A description must state **what the skill does** and **when to use it**, in the
third person, with the words a user would actually say. The spec's example:

```yaml
description: Extracts text and tables from PDF files, fills PDF forms, and merges multiple PDFs. Use when working with PDF documents or when the user mentions PDFs, forms, or document extraction.
```

Claude's authoring guide adds: do not write "I can help you…" or "You can use
this to…"; the description is injected into the system prompt, and inconsistent
point of view causes selection problems. Anthropic's own `skill-creator` notes
that models tend to **under-trigger**, so include explicit contexts ("even if
they do not say 'PDF'"). Keep it honest: over-broad descriptions steal triggers
from other skills.

## 2. Client differences

| | Claude Code / Claude | OpenCode V2 | Codex | Cursor |
|---|---|---|---|---|
| Discovery | `.claude/skills/`, `~/.claude/skills/`; plugins via marketplaces | `.opencode/skills/`, `~/.config/opencode/skills/`, plus `.claude/skills` and `.agents/skills` compatibility | `.agents/skills` from CWD up to repo root, `~/.agents/skills`, `/etc/codex/skills`; system skills bundled | Rules: `.cursor/rules/*.mdc`; skills: the shared `.agents/skills` convention (per the skills CLI, not Cursor's rules page) |
| Entry point | `SKILL.md` | `SKILL.md` (nested up to 6 dirs) or root `*.md` | `SKILL.md` | `SKILL.md` for skills; `.mdc` for rules |
| ID source | Directory name | **Path**, not frontmatter `name` | Directory name | Directory name |
| Frontmatter | `name` + `description` required by spec | All fields optional at runtime; **no description means never advertised** | `name` + `description` required; optional `agents/openai.yaml` | Rules use `description`/`globs`/`alwaysApply`; skills use spec fields |
| Trigger control | `disable-model-invocation` (Claude) | `metadata.opencode/autoinvoke: false` or `disable-model-invocation: true` | `agents/openai.yaml` `allow_implicit_invocation: false`; `[[skills.config]]` disable | Rule type (`Always`, `Intelligently`, `Specific Files`, `Manual`) |
| Plugin layer | `.claude-plugin/marketplace.json`, 317 entries in Anthropic's official catalog | HTTP catalogs: base URL + `index.json` with `version` + `files` | Plugins bundle skills + connectors; universal directory | `.cursor-plugin/marketplace.json` for rule/plugin distribution |
| Validation | `skills-ref` / `agentskills validate` | same, plus its own discovery rules | same | same for skills; rules are not `SKILL.md` |

### OpenCode V2 details that bite

- **The ID is the path**, case-sensitive: `.opencode/skills/release/SKILL.md` →
  `release`, even if frontmatter says `name: Git Release`. Mentioning
  `@skill-id` uses the path ID.
- A directory containing `SKILL.md` is **one** skill; OpenCode does not search
  inside it for more. Grouping is allowed (`skills/teams/release/SKILL.md`).
- Hidden dirs and `node_modules` are skipped; search stops six levels down.
- Precedence, low → high: built-ins, `.claude/skills`, `.agents/skills`,
  `~/.config/opencode/skills`, project `.opencode/skills`, explicit `skills`
  config entries. Duplicate IDs: later source wins.
- V2 does **not** enforce the kebab-case pattern, the 1–64 limit, name/dir
  match, or a description maximum. That is a portability risk, not permission
  to ignore the spec: the next client may enforce it.
- Permissions can `allow` / `ask` / `deny` a skill by ID (last matching rule
  wins). A denied skill is hidden from the model.

### Claude Code details that bite

- Plugin marketplaces are **catalogs, not stores**: a repo with
  `.claude-plugin/marketplace.json`. Anthropic's official marketplace is added
  automatically in interactive sessions; community is opt-in.
- A plugin can bundle skills, agents, hooks, MCP servers, and commands. A skill
  is one component, not the whole plugin.
- Reserved marketplace names and plugin-directory names are enforced to prevent
  impersonation (`claude-plugins-official`, `anthropic-*`, etc.).
- Nested skill loading changed in 2026: `.claude/skills` inside `--plugin-dir`
  plugins no longer load from a session started above them.

### Codex details that bite

- `openai/skills` is **deprecated** (README, 2026-11-14); the current path is
  `openai/plugins` and the Codex "Build skills" guide.
- Codex scans `.agents/skills` from the current directory up to the repo root,
  plus `~/.agents/skills`, `/etc/codex/skills`, and bundled system skills.
- Curated skills install via `$skill-installer`; `skill-creator` and
  `skill-installer` are system skills, invoked with `$`.
- Optional `agents/openai.yaml` controls display metadata, implicit invocation
  (`allow_implicit_invocation: false`), and tool dependencies.
- Disable a skill without deleting it via `[[skills.config]]` in
  `~/.codex/config.toml`; the last matching entry wins.
- Codex caps the initial skill list at ~2% of the context window (8,000 chars
  when unknown), and shortens descriptions first when many skills are installed.
  Keep descriptions front-loaded.
- Repo-level licensing is absent; each skill carries its own `LICENSE.txt`.

### Cursor details that bite

- Cursor **rules** are not Agent Skills: they are `.cursor/rules/*.mdc` with
  `description`, `globs`, and `alwaysApply`, and the agent reads them as
  system-level instructions. A plain `.md` in `.cursor/rules` is ignored.
- Cursor's own docs describe rules and `AGENTS.md`; they do **not** document
  `SKILL.md` discovery. The shared `.agents/skills` convention comes from the
  skills CLI, so verify support in the Cursor version you target before relying
  on it.
- Cursor supports `AGENTS.md` at the project root and in subdirectories, merged
  with more specific files taking precedence.
- For distributing rules, Cursor uses plugins and `.cursor-plugin/marketplace.json`.

## 3. Layout patterns that scale

**Single skill** — one folder, one `SKILL.md`, references only if needed.

**Suite** (this repo's `code-review/`) — an entry-point skill routes to
specialist skills, each with its own folder. The entry point must name the
others and say when to load each.

**Variant bundle** (multi-framework) — one `SKILL.md` with a selection table,
then `references/aws.md`, `references/gcp.md`, `references/azure.md`. The agent
reads only the variant it needs.

**Meta-skill** (this bundle) — a method plus templates plus a validator. The
body teaches the loop; references carry the depth; templates are copied into
the user's workspace; scripts are deterministic checks.

## 4. Validation

### Official reference validator

```bash
pip install skills-ref          # installs the `agentskills` CLI
agentskills validate ./my-skill
# Valid skill: ./my-skill
# or: Validation failed ... - Skill name 'Bad_Skill' must be lowercase
```

It checks: directory/`SKILL.md` presence, YAML parse, `name` rules, description
non-empty, allowed field types. It does **not** check description quality,
links, secrets, license, or safety.

### This bundle's validator

```bash
python3 scripts/check_skills.py --strict --bundle skills/skill-creation
```

Adds: required files, description length/style, relative links resolve, no
secrets/PII patterns, duplicate names, placeholders, body length, and
"references exist but are never mentioned". See
[../scripts/check_skills.py](../scripts/check_skills.py).

### What no validator can check

- Whether the skill actually improves output (run evals).
- Whether the description triggers on real user phrasing (test prompts).
- Whether the instructions are true for your environment (read them).
- Whether the source is trustworthy (provenance + security review).

## 5. Porting checklist (Claude ↔ OpenCode ↔ Codex ↔ Cursor)

1. Copy the folder; keep `SKILL.md` at the root.
2. Rename the directory to the portable kebab-case ID you want; if frontmatter
   `name` differs from the directory, fix it (OpenCode ignores `name` for the
   ID; other clients may not).
3. Re-check `description` length and third-person phrasing.
4. Replace client-specific tool names and paths (`Read`, `Bash`, `@skill`)
   with the target's equivalents or a neutral phrasing.
5. Move client-only frontmatter into `metadata` (e.g. OpenCode autoinvoke).
6. Verify scripts run under the target's interpreter and permissions; remove
   anything that assumes a specific sandbox.
7. Run `agentskills validate` and this bundle's validator.
8. Run 2–3 trigger prompts in the target client; confirm the skill loads and
   the output shape matches.
9. Record the port (source commit, target, changes) in the README.

## 6. Versioning

Use `metadata.version` (string) and a dated changelog in the README. Semver is
fine but not required by the spec. For distributed skills, pin the source commit
and record the lockfile hash (skills.sh writes `computedHash` SHA-256); that is
the only reliable way to know what you actually installed.
