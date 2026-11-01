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
- **Visible-window rule (founder rule, 1 Nov):** every scripted build must run in an image that has a display
  window — `Gimp.Display.new(image)` immediately after `new_canvas`/`open_image`, kept open for the whole build.
  The founder watches every edit live; never build into an image without a display.

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
  statement; Hindi/Hinglish taglines fit the brand voice. Zivon never positions itself
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
- 2026-10-31 (Day 1 rebuild run): **`Gimp.Drawable.fill` and `Layer.fill` fill the ENTIRE drawable and ignore
  any active selection** in GIMP 3.2 — the root cause of "opaque veil" layers (rules/shadow/tape flooding the
  whole layer). Selection-restricted fills must use **`layer.edit_fill(Gimp.FillType.FOREGROUND)`**. Isolate
  one behavior per test canvas and verify with exported PNG + PIL before building anything on top of it.
- 2026-10-31: **`Layer.delete()` silently fails** (ghost layers survive as `name #1`, `name #2` — three
  stacked "rules" layers faked every later test). Remove layers with **`Image.remove_layer(layer)`**.
  `Image.delete()` does work for whole images.
- 2026-10-31: `Layer.scale(new_width:int, new_height:int, local_origin:bool)` takes **absolute target sizes**,
  not factors — factors return `False` and leave the layer untouched.
- 2026-10-31: `TextLayer.new(image, text, font, size, unit)` — `font` must be a `Gimp.Font` object
  (`Gimp.Font.get_by_name('Courier Prime Bold')`), and `unit` is required; `Gimp.Unit.PIXELS` does not exist —
  borrow the unit from any existing project text layer: `layer.get_font_size()[1]`.
- 2026-10-31: **`TextLayer.set_color` silently fails** — text renders in the context foreground color at
  creation time. Set `Gimp.context_set_foreground(Gegl.Color.new(...))` immediately before each `TextLayer.new`.
- 2026-10-31: no `Gimp.Matrix3D` / `Gegl.Matrix3D` class; `transform_matrix` takes **9 raw coefficients**.
  Rotation by θ around a pivot (cx,cy) bakes the translation in: `c02 = cx - cx*cos + cy*sin`,
  `c12 = cy - cx*sin - cy*cos`. Day 0's approved card device: rotate only card-bg + card-shadow layers;
  keep text and separators straight on top. **SUPERSEDED 2026-11-01 by the group-tilt rule below** — Day 1's
  founder review required every page element to tilt with the page.
- 2026-10-31: `Image.select_polygon(operation, [x1,y1,x2,y2,...])` is the clean way to draw rotated strips
  (tape corners): compute the rotated rectangle's 4 corners, select, `edit_fill` — no transforms needed.
- 2026-10-31: `Gimp.Display.new(image)` opens a visible GUI window for plugin-created images — do it so the
  founder can watch the build live.
- 2026-10-31: no XCF-save proc in this pyGObject build (`Image.export_drawing_xcf` and `GLib.File` don't
  exist) — save layered files with the MCP `save_xcf` tool.
- 2026-10-31: a console script aborts at the first error and **loses all its prints**; split risky calls into
  separate `call_api` items. `get_pixel` returns a `Gegl.Color` (read `.get_rgba()`, not `.red`/indexing) and
  returns `None` outside the layer's bounds. `get_state_snapshot` can return null/stale after scripted edits —
  ground truth is `export_image` + PIL pixel checks.
- 2026-10-31: reusing the annotation kit: **crop** `pen-underline.png` to the needed length (native stroke
  quality preserved) instead of compressing it — horizontal compression tightens the pen wave and looks wrong.
  Paste kit shapes with NOHALO interpolation at native size; scale only when unavoidable, with CUBIC.
  **SUPERSEDED 2026-11-01: kit pasting is banned** (founder: pasted marks showed white backgrounds — "don't
  go for cheap tricks, learn to draw this stuff"). Draw pen marks natively; the kit is look reference only.
- 2026-11-01: **Native pen strokes** (the reusable renderer): **canonical parameters live in
  `docs/frontend/design-doctrine.md` §4.1** (all in em of the underlined font: span ink + 0.09em left +
  0.18em right, control spacing 0.45em, sine amp 0.02em / period 4em / phase 0.7, jitter ±0.007em seeded
  from the underlined string, width taper 0.067em→0.033em, centerline baseline + 0.3em (revised 1 Nov from 0.5em — 0.5em read as detached from its own text); strikethrough
  variant: +0.09em each side, 0.056em→0.033em, centerline baseline − 0.26em). The seed must match the web
  implementation bit-for-bit: FNV-1a string hash → mulberry32 (`t = imul(a^a>>>15, a|1); t = (t +
  imul(t^t>>>7, t|61)) ^ t; return (t^t>>>14)/2^32`). Build the stroke as a parametric outline —
  sample the path into control points (every ~40px; sine wave amp ~1.5-1.8px + seeded jitter ±0.6), compute
  per-point normals from averaged adjacent tangents, offset left/right by half the local width (linear taper
  w0→w1, e.g. 6→3), emit one closed polygon (left side forward + right side reversed), then
  `select_polygon(REPLACE, poly)` + `layer.edit_fill(FOREGROUND)`. For anti-aliased edges: draw at 2x on a
  temporary image, `layer.scale(W, H, False)` down to 1x, copy-paste onto the target. Arrow = cubic-bezier
  shaft (~13 points) + two barbs from the tip opening **backwards** (reverse tip tangent, rotate ±30°, ~15px).
- 2026-11-01: **polygon point limit**: a ~178-point `select_polygon` splits into chunks and renders a
  duplicated shifted stroke. Keep polygons under ~50 points (coarse control-point sampling is plenty for a
  gentle wave); verify every stroke with an export + PIL stray-pixel scan.
- 2026-11-01: `Image.select_rectangle(operation, x, y, width, height)` takes **width/height, not x2/y2** —
  passing corner coords fills a giant block (this wrecked a card build; check the docstring when a fill
  covers the wrong area).
- 2026-11-01: `layer.scale(w, h, local_origin)` — `True` anchors at the **image center** (layer offset jumps
  and content compresses toward the center); use `False` for origin-anchored downscaling.
- 2026-11-01: `edit_paste(parent, True)` pastes at the **parent's** origin and clips to the parent's bounds —
  pasting full-canvas pen strokes onto a small text layer yields an empty layer. Paste onto `base` with
  `False`, then move the converted layer up the stack.
- 2026-11-01: `floating_sel_to_layer` returns a **bool**, not the layer; grab it as
  `get_layers()[index(parent) - 1]`. `insert_layer` cannot move an existing layer — `layer.copy()`,
  `remove_layer(original)`, `insert_layer(copy, None, 0)` (position 0 = top; `get_layers()` lists top→bottom).
- 2026-11-01: `Gimp.TransformResize` values are ADJUST / CLIP / CROP / CROP_WITH_ASPECT — **ADJUST** grows the
  layer to fit the transformed result (set via `context_set_transform_resize` before `transform_matrix`).
- 2026-11-01 (founder rule, supersedes the 2026-10-31 "rotate only card-bg + card-shadow" device): **group
  tilt** — every element of a tilted page (bg, shadow, separators, all text, stamp, pen marks) rotates by the
  same matrix around the same pivot. Page shadow = card silhouette offset +10/+10, graphite at 22% opacity —
  attached to the edge, corner included, ~10px thick (Day 0 A2 ground truth).
- 2026-11-01: **stamps carry a single judgment word** (DELAYED / POSTPONED / BLOCKED / PENDING) in uppercase
  Courier Prime Bold inside a 2px pencil-red border. The "not yet:" phrase is purged from the doctrine and
  skills — never revive it; the reason belongs beside the stamp in ink.
- 2026-11-01: **text on ruled lines**: pick the rule pitch to match the text line pitch (36px rules for 26px
  Courier log lines), then place every baseline exactly on a rule. Measure baseline-from-offset empirically
  per font/size (export + PIL ink-bottom of a descender-free probe): Courier Prime 26 → +20, Bricolage
  Grotesque ExtraBold 88 → +82, Caveat Bold 96 → +92. No dashed separators between log entries — the hash
  column is the index.
- 2026-11-01 (founder): ruled lines at 1px / 18% opacity were "hard to notice". Standard is now **2px
  graphite at 40% opacity** (doctrine §4): verify with export + PIL — rule luminance should sit ~40 below
  the paper (e.g. paper 239 → rule 197).
- 2026-11-01 (Day 2 asset run): in this pyGObject build `Gimp.GetImages()`, `Gimp.image_list()`,
  `Image.new_layer()`, `Image.get_displays()` and `Display.get_list()` do **not** exist. Enumerate images with
  **`Gimp.get_images()`** (lowercase) filtered by `get_id()`; create/fill layers with the MCP tools
  `create_layer` / `fill_layer` (position 0 = topmost). `new_canvas` opens its own display (`display_opened:
  true`), so the visible-window rule is satisfied from creation.
- 2026-11-01: `layer.get_offsets()` returns a named tuple whose **index access is broken** (`[0]` returns
  `True`) — always read `.offset_x` / `.offset_y`.
- 2026-11-01: **2x supersampling without a temp image or paste**: create the 2x-sized layer directly in the
  target image (`create_layer`, set offset 0,0 first), draw the polygon selections in 2x image coordinates,
  `edit_fill`, then `layer.scale(w/2, h/2, False)` + `set_offsets(x, y)`. Arrow built this way (26-point
  shaft + 2 barb triangles): PIL scan 800 pen-blue px, 0 pure-white px in the bbox.
- 2026-11-01 (straight underline — **REVOKED 2026-11-01 by founder**): the Day 2 asset was briefly built with a
  plain 5 px `select_rectangle` underline as the "Day 2 doctrine state". That exception is dead: §4.1's pen
  algorithm applies to **every** underline, Day 2 assets included. Never draw a straight underline.
- 2026-11-01: `call_api` `args[1]` must be a **list of code strings**, never a bare string. The plugin runs
  `for c in a[1]` (gimp-mcp-plugin.py), so a bare string execs **each character** as its own statement; the
  persistent context makes this sneakily confusing — characters that happen to name leaked variables (`i`, `m`
  from earlier loops) execute fine and the NameError lands on the first undefined one (e.g. `name 'p' is not
  defined` for code starting `import...`). Always wrap: `args: ["pyGObject-console", [code]]`.
- 2026-11-01 (founder, Day 2, revised four times): an arrow aimed at a **block of text** must target the block's
  **title/label/hook word**, not a line inside the block — a tip landing mid-block reads as ambiguous ("pointing
  at the wrong thing"). The first fix (note on the title line, arrow skimming beside the headline) was itself
  rejected as "weird": annotations must sit in **whitespace with comfortable empty space around them** (see
  photo-edit-director SKILL.md Phase 2). Working layout: Caveat note in a corner whitespace area
  (top-right, on a rule), arrow running through open space from the note to the hook word, tip at the word's
  **right edge**. Third + fourth revisions converge on the founder's ASCII sketch: note on top, a **steep
  diagonal** leaving the note down toward the target's line, curving into a **short horizontal run** whose head
  points left into the title (`title <──╱` under `note`) — the angle lives in the descent; the shaft must not
  run near-parallel to text across its length. Working params at 1080x1350: cubic P0 (902,146) C1 (790,180)
  C2 (640,196) P3 (547,196) — start tangent ~17° downward, tip tangent exactly horizontal, descent concentrated
  in the right two-thirds, ~90px horizontal run into the word (tip mid-right). Barbs ±32°/20px. Verify every
  clearance (mark-to-text, mark-to-mark) with a PIL scan on the export before showing the founder.
- 2026-11-01: arrowhead barbs must be **visible on both sides of the shaft**. With a steep tip tangent,
  ±30°/15px barbs fuse with the shaft and the head reads as a thorn (founder: "pointing the wrong way").
  Fix that worked (for a steep down-pointing arrow): tip tangent within ~12° of vertical, barbs ±32°, length
  20px, width 6px. For the current swooping-descent shape (horizontal tip tangent), ±32°/20px barbs open
  symmetrically above and below the shaft. Verify with a zoomed crop of the EXPORT (PIL crop + NEAREST resize),
  not just the full frame.
- 2026-11-01 (Day 2 git-log fit, final): 17 commits / 30 wrapped lines fit at **Courier Prime 25 px, 31 px rule
  pitch, 56-char wrap** (Day 1: 26 px / 36 px / 54). Rule phase `y = 103 + 31k` (k=0..38) so counter (103), note
  (134, top-right), hook (227), header (320), log baselines (351+31k) and caption (1281) all sit on rules. Pitch
  dropped from 32 to 31 px to make room for the underline + header stack under the hook.
- 2026-11-01 (text baselines): baseline = layer offset_y + font ascent; measured ascents: Courier Prime Bold 25
  → +19, 28 → +21, 32 → +25, 38 → +29; Bricolage Grotesque ExtraBold 90 → +84; Caveat Bold 40 → +38. Compute
  positions from baselines, not offsets.
- 2026-11-01 (failed calls leave side effects): a Code Mode `execute` block that throws at runtime may already
  have run earlier tool calls — a duplicate `Day 02` counter layer survived from a batch that died on a later
  line. MCP `add_text` dedupes names with a `#1` suffix, so **a `#N` layer name is the clue that an earlier call
  with the same text already succeeded**. After any failed build call, dump layer names/offsets before
  continuing.
- 2026-11-01 (PIL QC thresholds): graphite `#5A5748` has max channel 90 — an `ink()` test of `max(c) < 90`
  silently misses every graphite element (header, hashes, rules). Use `max(c) < 130 and blue-red < 40` for
  graphite-or-ink scans; keep `max(c) < 90` only for ink-only checks. A "missing text" QC result is usually the
  threshold, not the asset.
