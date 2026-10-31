# Field Notes annotation kit

Reusable hand-drawn annotation shapes for every Zivon post asset. Extracted from Day 0's **approved** marks
layers (`posts/assets/day-0/A3.xcf`, `A1.xcf`), so every asset from Day 1 on uses the exact same pen strokes
the founder already signed off on. Do not redraw these shapes by hand; paste these files.

## Files

| File | Size | Use |
|---|---|---|
| `pen-underline.png` | 797x16 | Pen-blue underline under hooks (5-6px stroke, gentle wave, taper at right end) |
| `arrow-steep.png` | 58x80 | Steep connector arrow pointing down-left (Day 0 A3 look) |
| `arrow-shallow.png` | 178x26 | Shallow connector arrow pointing left (Day 0 A1 look) |

All shapes are pen-blue `#1F3A9E` on transparent (alpha was unblended from the white source background).
`*-zoom.png` previews are 3x nearest-neighbor views for review only — never paste them.

## How to reuse (GIMP 3.2)

1. `open_image` the kit file, `select_rectangle` the needed span, `edit_copy`.
2. Paste onto the layer you want the shape above; convert the floating selection and grab the new layer at
   `get_layers()[index(parent) - 1]`.
3. **Underlines: crop to length, don't compress.** Select the left N px of `pen-underline.png` (native stroke
   quality preserved); horizontal compression tightens the wave and looks wrong. Extend a few px past both
   ends of the text it underlines.
4. Arrows: paste at native size with NOHALO interpolation. Scale only when unavoidable, then CUBIC.
5. Strikethroughs reuse `pen-underline.png` cropped to the struck word's width + ~12px, positioned through
   the x-height middle of the word.

## Rules (from photo-edit-director)

- At most one annotation on a proof image; annotations decode the proof, never restate the hook.
- Callout text under 7 words, Caveat Bold, pen-blue.
- Kit shapes guarantee the approved look — see `skills/content-creation/photo-edit-director/` and
  `docs/frontend/design-doctrine-example.html`.
