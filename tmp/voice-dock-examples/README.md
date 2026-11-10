# Voice dock - six throwaway shape candidates

**Status:** throwaway mockups, 10 Nov 2026, L0 of the deadline plan. **Not** design-doctrine §10.12,
**not** a design decision, **not** wired into the product. Delete the folder after the founder picks.

**Why this folder exists:** `docs/frontend/design-doctrine.md` has no §10.12 "Voice dock" yet
(founder-gated, DCR-002). `frontend/assets/zivon.js` therefore ships
`ZivonVoiceDock.doctrineReady = false` and `lazyMount()` returns
`{ mounted: false, reason: "founder-gated: …" }`. Nobody may improvise the dock's look. These six
files exist so the founder can pick a **shape** first; the doctrine gets written afterwards, once,
against the winner.

## What is in here

| File | What it is |
|---|---|
| `01-bottom-bar.html` … `06-status-strip.html` | Six self-contained visual mockups, one dock shape each |
| `index.html` | Gallery: all six side by side in scaled frames, links to full size |
| `_dock.css` | Shared chrome + tokens + the state styling every variant inherits |
| `_dock.js` | Mockup script: the fixed six-turn conversation, the state machine, the dev switcher |
| `README.md` | This file |

Open `index.html` (or any variant) by double-click - `file://`, no server, no build step.

**Everything here is inert and fake.** No WebSocket, no `fetch`, no `getUserMedia`, no
`AudioContext`, no storage, no CDN, no Google Fonts (fonts come from `frontend/assets/fonts/` by
relative path). The latency numbers, level bars, timings and credit counts are hard-coded. The
backdrop is the **real** generated page, embedded unmodified in an iframe:
`frontend/courses/class-11-physics/laws-of-motion/index.html#b-13`, with a pen-blue
`EL-LES-01-056`-style ring over block **b-13** (the batsman/impulse worked example) in the parent
document.

## The one fixed conversation (identical in all six)

Anchor `class-11-physics/laws-of-motion` · block `b-13`.

| Turn | Who | Line |
|---|---|---|
| 1 | student | "Sir, impulse aur change in momentum same kyun hote hain? Formula nahi samajh raha." |
| 2 | tutor | "Achha sawaal. Pehle yeh socho - bat aur ball ka contact kitni der tak chalta hai?" |
| 3 | student | "Bahut kam sir, 0.15 second jaisa." |
| 4 | tutor | "Haan, chhota time, aur bada force. Ab force × time karo — yahi impulse hai. Newton ka doosra law F = Δp/Δt hai, ise palat do to F·Δt = Δp, matlab left side impulse aur right side **change in mo**" ← **cut mid-word by the barge-in** |
| 5 | student | "रुक रुक sir — matlab left side impulse, right side change in momentum? Same cheez hai na?" |
| 6 | tutor | "Bilkul same hai. Formula ek hi quantity ko do naam deta hai — force × time jo momentum badle, wahi impulse hai. इसलिए दोनों बराबर लिखते हैं।" |

Turn 4 is the barge-in: the caption grows phrase by phrase, then **stops mid-word** and freezes in
`interrupted` while the student's next line takes the floor. Tutor turns are 1-2 sentences, one
idea each, Socratic on turn 2, code-mixed Hinglish (Latin + Devanagari).

## States

Every variant reaches all 18 client state names from `frontend/assets/zivon.js` through the
**`MOCK · state`** switcher (top-left, bottom-left in variant 06): `idle`,
`requesting-permission`, `connecting`, `ready`, `listening`, `endpointing`, `thinking`, `speaking`,
`speaking_text`, `interrupted`, `offline`, `error:mic-denied`, `error:mic-in-use`, `error:no-match`,
`error:auth.invalid`, `error:version.mismatch`, `error:system-error`, `text_only`. The eight the
brief requires are all there and visually distinct:

- **`listening`** - mic filled, animated level bars, "Listening — keep holding".
- **`endpointing`** - mic released (outline), bars flattened to 15 %, a dashed hairline that
  breathes: "silence mila, aapki baat khatam hone ka wait". Never a spinner, never the same
  shape as listening.
- **`thinking`** - a 2 px indeterminate sweep, **no timer and no percentage** (it cannot lie about
  time because it never claims any).
- **`speaking`** - voiced: growing caption + blink caret + level bars.
- **`speaking_text`** - newly speechless: same text, **no bars, no caret**, chip reads
  "TUTOR · TEXT" (test with the `text mode` button mid-answer).
- **`interrupted`** - the frozen half-word, transcript row marked `▍cut off`.
- **`error:mic-denied`** - no red toast: a `MIC OFF` stamp, one sentence saying the lesson works
  fine, and the text field already open and focused.
- **`text_only`** - credit-guard closed mic: disabled mic + the honest ledger line
  ("30 credits / day · voice resets at 00:00. Reading, sims and typing are free and unlimited").
- **`offline`** - says nothing typed is lost, keeps the text path open.

## The six, and what each one costs

Cost column: DOM nodes = the dock subtree in the empty (idle) shell - each conversation turn adds
about 4 more, so ~55 nodes at a full six-turn history, plus the ~46 nodes of the shared mockup
script's ring and dev switcher. "New region?" asks whether the shape can live inside the single
`aside.zn-voice-dock-region` that `frontend/assets/zivon.js` already emits inside `.zn-page`.

| # | Variant | Layout | The question it answers | Build cost | What breaks at 360 px | The one thing the founder must decide |
|---|---|---|---|---|---|---|
| 01 | `01-bottom-bar.html` | Full-width bar pinned to the bottom edge, one-line caption, transcript grows **upward** above the mic row; collapses to a 72 px strip | "Can the dock be the boring, obvious thing every school app has?" | 30 nodes · no new region (fixed-position from the existing `aside`) · 2 media tiers (900 px gutter alignment, 380 px tool stacking) | The bar + transcript eat 240-330 px of a 740 px viewport; the lesson is reduced to a scrolling peephole. The caption at 3 lines pushes the mic row below the fold if you also open the text field | **Is permanently giving up ~30 % of a cheap Android viewport acceptable?** If yes, buy speed and stop looking |
| 02 | `02-floating-pill.html` | 72 px capsule bottom-right (mic + one live line) expanding into a 360 px taped paper card (one tape strip, -3°) | "Can the tutor be present without being furniture?" | 35 nodes · no new region · 1 media tier (420 px: card becomes edge-to-edge) | The card covers the b-13 answer and the b-14 card; the capsule's 36 px radius is a **§6 departure** (corners are square or 4 px) | **Capsule or square?** A pill reads "chat widget", the doctrine reads "notebook" - you cannot have both |
| 03 | `03-margin-rail.html` | 168-236 px "margin note" column in the page's outer right margin, top edge on a ruled row, graphite margin rule at its left, pen-blue Caveat label | "Can the tutor live outside the text entirely?" | 31 nodes · no new region, **but it only exists above 1120 px** (the outer margin must be ≥ 180 px) · 1 media tier, and it is the wrong one: below 1120 px it degrades to a bottom bar | Nothing *breaks* - the rail simply ceases to be a rail and becomes a bottom bar, i.e. variant 01 with extra code. At 1280 px it is the only variant that covers **zero** words of the lesson | **Is a dock that changes species at 1120 px one dock or two?** (Desktop/marketing judgement: this is the screenshot-perfect one) |
| 04 | `04-inline-under-block.html` | Dock hangs off the bottom edge of the b-13 ring, inside the page column, with a 2 px pen-blue leader stroke | "Is the tutor talking about *this* paragraph, visibly?" | 30 nodes · **in-flow placement needs a second region per block** (or a JS-computed `top`, which is what the mockup fakes) · 1 media tier: < 860 px wide **or** < 700 px tall → bottom bar | Needs ~260 px below b-13; at 360 px b-13 alone is 1081 px tall, so it degrades to the bottom bar and the "it lives under your paragraph" promise evaporates | **Are you willing to accept a second mount point (per-block) for the only variant that makes the anchor legible?** |
| 05 | `05-sheet.html` | Bottom sheet up to 60 % of the viewport: grab rule, transcript history, mic on the thumb shelf at the bottom; collapses to a 92 px strip | "Does a doubt need history, or just the last line?" | 31 nodes · no new region · no breakpoint tier (dvh + flex only); the 900 px tier is cosmetic (centred width) | The sheet takes 306 of 740 px and the transcript is the only thing that grows; the grab strip plus mic shelf leave ~2 transcript lines visible | **Do students need to re-read the conversation, or is one live line enough?** History is the only reason to pay 40 % of the screen |
| 06 | `06-status-strip.html` | 46 px strip pinned **above** the page, above the lesson's own sticky language bar: mic + state + one-line live caption; expands to 55 % | "Should the tutor be a status, like battery or network?" | 30 nodes · no new region · 1 media tier (460 px: state chip drops out of the closed strip) | Two paper-light bars stack (strip + language bar, 46 + 105 px) before a single line of Physics appears; the page's own chrome becomes indistinguishable from the tutor's | **Is the primary affordance allowed to sit above the page's language bar?** If the strip and the lang bar merge into one, that is a shell change, not a dock |

## The code seams a winner must map onto

Nothing in this folder touches the product. When the doctrine lands, the winning shape must be
built on exactly these seams - all already exist in `frontend/assets/zivon.js`:

- **Mount target** - `aside.zn-voice-dock-region` inside `.zn-page`, with
  `data-region="SCR-LES-01.R9"`, `data-element-id="EL-LES-01-090"`, `aria-label="Voice tutor dock"`,
  currently `hidden` and emitted by `ensureVoiceDockRegion()`. It is a **single region at the end of
  the page**, so variants 01/02/03/05/06 mount from it directly with `position: fixed`.
  Variant 04's true inline placement does **not** fit that one region: it needs an insertion point
  per block (or a JS-computed offset that survives resize and reflow). That is a layout change, not
  a dock variant - call it out in the doctrine if you pick it.
- **Mount seam** - `window.ZivonVoiceDock.lazyMount()`; it returns
  `{ mounted: false, reason: "founder-gated: design-doctrine.md §10.12 absent (DCR-002)" }` today.
  Set `doctrineReady` only when §10.12 exists. These mockups deliberately do **not** touch it.
- **Client** - `window.ZivonVoiceClient.create()`; its state names are the ones in this folder's
  switcher (verbatim), so the visual states need no renaming.
- **Context** - `buildContextSnapshot()` (≤ 4 KB, `block_id`, `visible_blocks`, `sim_states`,
  `scroll_pct`, `lang_pref`). The dock's "b-13" line is exactly that snapshot's `block_id`.
- **Highlight** - `highlightBlocks([blockId])` adds `.zn-tutor-highlight` (`EL-LES-01-056`,
  pen-blue 3 px ring, kit-owned CSS). The mockups fake that ring in the parent because a
  `file://` iframe is cross-origin; served over `http://` `_dock.js` measures the real rect.
- **CSP** - a lesson page ships `default-src 'none'`, and its `connect-src` was `'none'`: no
  WebSocket could open from a lesson page until `connect-src 'self'` was granted. That scoped
  relaxation is separate, founder-authorised work (ws-client-contract.md §8) and was in flight in
  the tree while these mockups were written - check the page's meta tag before wiring anything.
  **These mockups never try to open a socket** in either state: they are inert by construction.

## Interaction each variant demonstrates

1. **Entry** - hold-to-talk (`pointerdown` = listening, release = endpointing, ADR-0018), with a
   real pressed state (mic fills ink; pen-blue in the capsule). Keyboard: hold <kbd>Space</kbd>.
2. **Collapse/expand** - every collapsed state keeps a live mic button; the toggle is a chevron
   with a text label, never a bare hide icon. Collapsed still shows the caption.
3. **Barge-in** - turn 4 is cut mid-word; `interrupted` freezes the half-word and marks the
   transcript row.
4. **Text fallback from every state** - the `Type` control is always present; errors, `offline`
   and `text_only` open it automatically and focus it. Submitting text from any state streams a
   tutor answer back, so no state is a dead end.
5. **Anchor visible** - the b-13 ring (on from `listening` through `interrupted`) and the real
   page behind it.
6. **Silence-close** - after 4.2 s of `listening` with no speech the dock returns to `idle` with an
   opacity transition and an idle caption; it never blinks out.
7. **Stop** - <kbd>Esc</kbd> cuts the tutor to `interrupted`, same as a barge-in.

## Accessibility and low-end-Android notes (mockup level)

- 44 px minimum targets (mic 52-56 px, buttons ≥ 44 px); 3 px pen-blue focus ring, 3 px offset.
- `aria-live="polite"` on the live caption and `role="log"` + `aria-live="polite"` on the
  transcript; `aria-pressed` on the mic; `aria-busy` while thinking; `aria-expanded` on the text
  toggle and the collapse control.
- Animation is **transform + opacity only** - no filters, no backdrop blur, no animated shadow, no
  scroll-linked JS. `prefers-reduced-motion` kills the level bars, the caret blink, the sweep and
  the breathing hairline; the text still grows word by word (the growth *is* the content, not
  choreography).
- Honest caveat, worth fixing in the real build: **two live regions** (caption and transcript) will
  double-announce to a screen reader. The real dock should keep exactly one - the caption - and
  give the transcript `aria-live="off"` with a "read conversation" control.

## Other honest caveats (things a reviewer would find)

- The **ring geometry on `file://` is a measured fallback**, not live: a `file://` iframe is
  cross-origin, so the parent cannot read b-13's rect. `_dock.css` carries the measured heights
  (57 px language bar, 517-1200 px block, per breakpoint). Served over `http://`, `measureAnchor()`
  measures the real block. The top of b-13 (its "Worked example" heading) is under the page's own
  sticky language bar, exactly as a real `#b-13` deep link behaves.
- The conversation, timings, latency, level bars and credit numbers are **fabricated** for judging
  shape and streaming feel. None of it is a claim about Gnani latency or the credit guard.
- Nothing here is a doctrine statement. If the founder picks a variant, §10.12 must be written by
  the founder, in the doctrine, first - then the dock is built on the seams above.
