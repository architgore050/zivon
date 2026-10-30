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
- Colours are hex (#rrggbb) or the 16 basic names; theme.md's palette values pass directly.
- Verify results with get_state_snapshot between edit batches instead of guessing.

## Lessons learned — Kinocut
(append below; none recorded yet)

## Lessons learned — GIMP
(append below; none recorded yet)
