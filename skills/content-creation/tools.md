# Editing MCP lessons store (Kinocut + GIMP)

The decided editing tools for this repo's content work: **Kinocut MCP** for video (trim, concat, subtitles,
audio, export) and **GIMP 3.2 MCP** for image editing (stills, cards, posters, annotated screenshots, text on
images). Do not evaluate, compare, or recommend other editing tools or MCP servers. This file is a lessons
store: it records what we have learned about using these tools so every later edit run is faster and safer.

## How to use this file
- Before writing the MCP step list (asset-and-edit-brief.md, Step 2b), read the lessons below and reuse proven
  tool names, argument shapes, and export settings.
- After every real edit run, append new lessons under the matching "Lessons learned" section: what worked
  (exact tool call patterns), what failed and how it was fixed, gotchas, and settings that met the brief. One
  dated bullet per lesson, concrete (commands and arguments, not vibes).
- Correct or delete a lesson only when a later run proves it wrong, and note the correction in place.

## Known Kinocut basics (verify against the installed server before relying on them)
- Kinocut (formerly mcp-video): an MCP server exposing 205 tools with `KINOCUT_TOOLS=all`, covering trim,
  crop/scale, concat, subtitles from .srt, audio normalisation, effects, repurposing, preflight checks, and
  export. AI extras (transcribe, stems, upscale, object matte) and the Hyperframes CLI are installed on this
  host.
- The tool list is large: express each edit as a short ordered chain of atomic operations, one tool call each,
  and smoke-test one operation ("trim clip.mp4 from 2s to 9s and export") before running the full edit brief.
- Default path: video_doctor / video_info -> plan (video_intent or cutfile) -> render -> video_quality_check
  -> human review. Never publish without QC and the human gate.

## Known GIMP basics (verify against the live server before relying on them)
- GIMP 3.2 MCP (gimp3-mcp): 80 tools for image work — new_canvas / open_image, layers, selections, painting,
  text layers, colour adjustments, filters, and export (PNG/JPEG/WEBP, social-media kits, icon sizes).
- Requires GIMP 3.2 running with its MCP plugin started (Tools > Start MCP Server); check_server tells you
  whether it is reachable.
- Colours are hex (#rrggbb) or the 16 basic names; the design doctrine's palette values
  (docs/frontend/design-doctrine.md) pass directly.
- Verify results with get_state_snapshot between edit batches instead of guessing.

## Lessons learned — Kinocut
(append below; none recorded yet)

## Lessons learned — GIMP
- 2026-10-31 (Day 0 post kit): `new_canvas(name=...)` does not stick — GIMP reports the image as
  `[Untitled]` via `get_name()`. Identify images in `call_api` by dimensions + `get_file()` (None for
  unsaved), not by name.
- 2026-10-31: in 3.2 PyGObject there is no `Gimp.Image.select_all` / `image.select_all` / `Image.set_name` /
  `Layer.crop`. Use `image.select_rectangle(Gimp.ChannelOps.REPLACE, 0, 0, w, h)`; skip image renames; to trim
  a layer, paint the unwanted strip with the background color via `fill_rectangle(layer_name=...)`.
- 2026-10-31: cross-image composite recipe that worked: select_rectangle on source → `Gimp.edit_copy([layer])` →
  `Gimp.Selection.none(src)` → `floating = Gimp.edit_paste(bottom_layer_of_dst, True)[0]` →
  `Gimp.floating_sel_to_layer(floating)` (returns a **bool**, not the layer) → find the new layer by iterating
  `dst.get_layers()` (paste lands centered, name "Background copy") → `set_offsets(x, y)` → `displays_flush()`.
- 2026-10-31: `add_text` returns `text_width` — use it for right-alignment (`x = 1020 - width`) and inline
  two-color captions; reposition layers with `layer.set_offsets` via `call_api` (MCP has no move-layer tool).
- 2026-10-31: fonts installed to `~/.local/share/fonts` from rsms/inter v4.1 and JetBrains/JetBrainsMono
  **v2.304** (the v2.305 asset URL 404s; check `api.github.com/repos/.../releases/latest` for the real asset
  name). GIMP sees "Inter Bold", "Inter Medium", "JetBrains Mono", "JetBrains Mono Bold" after `fc-cache`.
- 2026-10-31: verify crop boundaries with `get_state_snapshot(region=...)` before cropping; QC with a
  `max_size=300` snapshot for phone readability; `save_xcf` to /tmp/opencode keeps re-editable layers out of
  the repo.
