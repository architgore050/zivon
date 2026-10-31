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
  unsaved), not by name.- 2026-10-31: in 3.2 PyGObject there is no `Gimp.Image.select_all` / `image.select_all` / `Image.set_name` /
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
  the repo. Correction (31 Oct, founder decision): working XCFs now live in the repo next to their exports
  (`posts/assets/day-0/A{1,2,3}.xcf`); save them there.
- 2026-10-31 (Field Notes rebuild): fonts installed mid-session are invisible to GIMP's cached font list until
  `Gimp.fonts_refresh()` (call_api) is run; then `Gimp.fonts_get_list('Caveat')` returns `Gimp.Font` objects and
  `TextLayer.set_font(font_obj)` works (it needs a `Gimp.Font`, not a string). MCP `add_text` validates against
  the cached list and silently substitutes unknown fonts (a `Sans-serif` fallback shows up in `edit_text`'s
  returned `font`). Always verify the rendered face with a snapshot.
- 2026-10-31: doctrine fonts live in `~/.local/share/fonts/fieldnotes/`: Bricolage Grotesque Medium/Bold/ExtraBold
  (opsz 36 cut) + "Bricolage Grotesque Display" Bold/ExtraBold (opsz 72 cut, for 96-120 px headlines), Courier
  Prime Regular/Bold, Caveat Bold — static instances made from google/fonts variable TTFs with
  `fontTools.varLib.instancer` plus a name-table rewrite (family/style per cut). Keep exactly one family+style
  set active; duplicate installs make fontconfig matching nondeterministic.
- 2026-10-31: `image.select_polygon(ops, pts)` takes a flat float list `[x1,y1,x2,y2,...]`, not Vector2 objects.
  Hand-drawn marks (uneven underline ribbons, curved arrows with barbs, 45-degree tape strips) all work as
  polygon selections + `edit_fill` on a dedicated layer.
- 2026-10-31: `Image.crop()` returned True but left dimensions unchanged in this build — crop via
  select_rectangle → `Gimp.edit_copy` → new canvas → `edit_paste` → `floating_sel_to_layer` → `set_offsets`.
  `Image.scale(w, h)` works in place; set `Gimp.context_set_interpolation(Gimp.InterpolationType.NOHALO)` first.
- 2026-10-31: rotate a layer around an image-space pivot with `lay.transform_matrix(c,-s, cx*(1-c)+cy*s, s,c,
  -cx*s+cy*(1-c), 0,0,1)` (radians). `layer.get_offsets()` returns a named tuple — use `.offset_x/.offset_y`.
  `transform_rotate_simple` takes `(RotationType, auto_center, center_x, center_y)`, not an angle.
- 2026-10-31: `im.delete()` silently no-ops on images held by the plugin; the MCP `close_image` tool closes them
  reliably. `sample_color` gives the exact fill color for solid redaction (Trello header `#00204e`).
- 2026-10-31: pen-blue annotations must sit on paper, not on dark screenshots (contrast fails the doctrine
  table); the underline + Caveat-note pair from `design-doctrine-example.html` is the reusable pattern. One
  rotated element per image (card 1.2 deg or note -2 deg, not both).
- 2026-10-31: `layer.delete()` also silently no-ops when the persistent plugin console holds a reference to the
  layer (same failure mode as `im.delete()`). To retire a layer, `set_visible(False)` instead — hidden layers are
  excluded from flattened exports and only clutter the /tmp XCF. When replacing a text layer, MCP `add_text`
  names the new one `"text #1"` because the old one still exists; grab the new layer by the exact name
  `add_text` returns, never by the bare name.
- 2026-10-31 (founder-approved Field Notes corrections): annotation arrows point at the **word**, not at the
  underline. Natural layout: Caveat note in the margin beside/above the headline (if it crowds the title, move
  it to the page corner, aligned with the Day-counter line); the arrow **starts at the middle of the note text**
  (or ~1/3 from the near end), not at the note's edge. Tip lands at mid-right of the word (near-horizontal
  arrows) or top-right of the word (descending arrows) — never bottom-right. Curve stays clear of the underline.
  Long swoops that start under a note and cross near the underline read as weird squiggles; don't do them.
  Caveat notes render at 40 px. Ruled lines: 2 px at 18% opacity — 1 px at 15% is invisible at 1080 px width.
- 2026-10-31: a handwritten note must add value to the viewer (explain, invite, or reframe) — "the receipts" got
  cut for adding nothing; "the why, in writing" replaced it on the repo-tree asset. If there is nothing useful
  to say, drop the note entirely rather than decorating.
- 2026-10-31 (founder copy review, applies to all card/note assets): card text is product reasoning, not
  decoration — settle the logic before designing anything. On the decision card: Tradeoff = why the bigger
  audience was chosen ("reach over niche"), Why = the reasoning stated explicitly, never as a slogan. The
  stamp slot became a handwritten closing tagline in pen-blue Caveat ("dil khol ke padhega india") — plain
  statement, no "not yet:" prefix; Hindi/Hinglish taglines fit the brand voice. Zivon never positions itself
  as exam-focused, even where exam relevance explains demand.
- 2026-10-31: arrowhead barbs must open **backwards** from the tip: reverse vector = -(tip - control_point),
  rotate ±30°, length ~15 px. A sign slip on the reverse vector puts the barbs past the tip and the arrow reads
  as a pitchfork. Verify arrowheads with a zoomed `get_state_snapshot(region=...)`, not just the full frame.
- 2026-10-31: layer stacking fixes — GIMP 3.2 pyGObject has no `Layer.set_below`/`set_above`, no
  `Image.reorder_layer`, and no `gimp_item_set_below` PDB proc. Use the MCP `reorder_layer` tool
  (`new_position` 0 = topmost). Ruled-paper lines belong **below** taped/tilted card layers so the card reads as
  clean paper on a ruled page.
- 2026-10-31: a text-glyph arrow ("→") inside a headline dies when the headline wraps — it ends pointing into
  empty margin. For a pivot headline the strongest Field Notes treatment is a **text correction**: keep the
  original line in the title font, hand-draw a pen-blue strike through the old word (extend slightly past its
  ends), and squeeze the handwritten replacement (Caveat, lowercase) centered above it. Skip the insertion
  caret: it floats awkwardly between the line and whatever sits below. Rebuilding a flattened composite
  (card): hide the old flattened layer (stays as XCF backup), build new bg/shadow/text/marks layers unrotated,
  then rotate every new layer by the same angle around the same pivot with `transform_matrix`; nudge rotated
  content afterwards with `set_offsets`.
- 2026-10-31 (Day 1 asset run): `call_api` protocol is `api_path="exec"`, `args=["pyGObject-console", [code]]`
  (one multi-line block per array item). `Gimp` is pre-imported in the console; import `math` and
  `from gi.repository import Gegl` yourself. Colors: `Gegl.Color.new('#rrggbb')`.
- 2026-10-31: `Image.set_active_item` does not exist in this build — don't hunt for it. `edit_paste`,
  `edit_fill`, and `fill` all take explicit drawables, so active-layer juggling is unnecessary.
  `floating_sel_to_layer` inserts the new layer **directly above the parent drawable**: paste onto the layer
  you want the capture above (paste onto `rules` → capture lands above the ruled lines), and find the new
  layer at `get_layers()[index(parent) - 1]`, never at index 0.
- 2026-10-31: `Gimp.edit_clear` does not exist. Clear a selection on a layer with
  `Gimp.Drawable.fill(layer, Gimp.FillType.TRANSPARENT)`.
- 2026-10-31: MCP `add_text` accepts the doctrine font names directly ("Bricolage Grotesque Display
  ExtraBold", "Courier Prime Bold", "Courier Prime Regular", "Caveat Bold") and returns `text_width` /
  `text_height` — measure text first, then compute underline spans, right-alignment (`x = 1020 - width`), and
  arrow tip targets from the returned geometry.
- 2026-10-31: when several unsaved same-size canvases are open (multiple 1080x1350 "Untitled"), identify the
  target by `im.get_id()` — a dimensions+name lookup silently grabbed the wrong canvas and nearly corrupted a
  finished asset. Track IDs from `new_canvas` responses.
- 2026-10-31: verify a screenshot crop's bottom edge with a zoomed `get_state_snapshot(region=...)` before
  finalizing: rendered line boxes extend past glyph bottoms (the theme.md crop needed y 936, not 965, to
  exclude the next bullet — here, a line that must not appear in Day 1 visuals).
- 2026-10-31: MCP `reorder_layer(new_position, layer_name, image_index)` works for stack fixes (0 = topmost);
  use it after pastes land in the wrong slot.
