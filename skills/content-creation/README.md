# Content-creation skills

Agent skills for Zivon's build-in-public posts. Each skill lives in its own folder with a `SKILL.md` entry
point; shared rules live at this level. This README is the source of truth for the folder's layout and rules —
root `README.md` and `AGENTS.md` point here and stay abstract.

## Layout

- `linkedin-post-interviewer/`, `x-post-interviewer/` — one folder per skill; `SKILL.md` is the entry point,
  each with its own hooks-and-formats reference.
- `theme.md` — the rules every Zivon post follows (identity, visual system, voice, cadence, safety). Read it
  before any post, video, or photo work; it overrides a skill's built-in defaults.
- `asset-and-edit-brief.md` — shared asset-capture and Kinocut MCP edit-brief methodology used by every skill.
- `tools.md` — the editing lessons store for Kinocut and GIMP: consult before writing MCP edit steps, append
  what you learn after each edit run.

## Invariants

- Interview before drafting (Depth Gate); never fabricate facts; never post on the founder's behalf without
  explicit approval of the exact text.
- **Kinocut MCP (video) and GIMP MCP (image editing) are the decided editing tools** — do not evaluate or
  propose alternatives. GIMP MCP requires GIMP 3.2 running with its MCP plugin started (Tools > Start MCP
  Server); check_server confirms reachability.

When you add or rename a file here, update this README only; the root docs do not list individual files.
