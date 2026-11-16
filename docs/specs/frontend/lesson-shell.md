# Lesson shell (F4) — product chrome around a generated lesson page

**Status:** binding for the W2 F4 workstream (2026-11-16). Implements the frozen full-frontend plan's lesson-page requirements (§10.4) on top
of the P1 hooks and the existing generated pages. Companion to [`spec.md`](spec.md), [`shell-injection.md`](shell-injection.md),
[`state-matrix.md`](state-matrix.md), and `docs/frontend/design-doctrine.md` §0.

## 1. What this is (and what it is not)

| The factory emits (content) | The shell injects (chrome) |
|---|---|
| `<link>`/`<script>` to `zivon.css`/`zivon.js` | app bar, chapter drawer, reading progress, bookmarks |
| header, objectives, text, diagrams, sims, checks, examples, glossary, sources | per-block "Ask about this", end-of-lesson next steps |
| `id="b-NN"`, `data-block-type`, `data-concept-id`, `section.zn-section#sec-NN` wrappers | — |
| `manifest.json` (`sections[].block_ids` = the block → section map) | drawer sections, current position, jump links |
| — | previous/next chapter, end CTA (from the published `catalogue.json`) |

**Two rules that decide every visual choice here:**

1. **The lesson body keeps §10.** The shell never rewrites, restyles, or reorders
   `.zn-page` content. Every injected node lives outside the ruled paper
   (`.zn-appbar`, `.zn-drawer`, `.zn-read-progress`) or carries
   `data-ruled-skip` so `LessonKit` ignores it (`.zn-block-tools`,
   `.zn-lesson-next`). No generated block, title, diagram, sim or check changes.
2. **The shell uses the BASE Field Notes identity (§1–§9), not §10.** App bar,
   drawer, progress and CTAs are typed Bricolage/Courier, flat paper, 1 px ink
   rules, ink-fill selected controls, pen-blue for "where you are". No ruled-line
   grid, no handwritten accents, no tape, no language-bar look. A shell element
   that borrows a §10 device is a scope error (doctrine §0).

With JavaScript off none of this exists and the lesson is fully readable
(progressive enhancement, tested).

## 2. Regions and elements

| Region | Element family | `EL-` ids | Code |
|---|---|---|---|
| `SCR-LES-01.R0` app bar | brand/home, Courses/Practice/Progress, Ask, identity, Contents toggle | `EL-LES-01-091`, `092`, `093`, `094`, `095`, `096`, `097`, `109` | `[kit] ZivonLessonShell.buildLessonAppBar` |
| `SCR-LES-01.R13` chapter drawer | panel, section link, save toggle, prev/next chapter, mobile product nav | `EL-LES-01-098`, `099`, `100`, `101`, `102` | `[kit] ZivonLessonShell.buildLessonDrawer` |
| `SCR-LES-01.R14` reading progress | 2 px `role="progressbar"` rule + fill | `EL-LES-01-103` | `[kit] buildLessonProgressBar` |
| `SCR-LES-01.R15` end of lesson | block, practise, explain-back, next chapter, all chapters, back to contents | `EL-LES-01-104`…`110` | `[kit] buildLessonNextSteps` |
| `SCR-LES-01.R3..R7` per block | "Ask about this" chip | `EL-LES-01-013` (P1 slice of F-ADD-VOI-02) | `[kit] injectAskButtons` |

The app bar sits **above** the sticky language bar in the document and scrolls
away with it, so §10.5's bar keeps the top edge while reading. The drawer is the
one navigation surface (the end-of-lesson "Back to contents" opens the same
drawer — no second nav).

## 3. Data sources

- **Sections** — `section.zn-section` wrappers in the DOM (P1 hook) joined with
  `manifest.json` → `sections[]` for the authored titles and `concept_id`. The
  renderer emits section wrappers, not section headings, so the manifest is the
  title source; without a manifest (content-only fixture, `file://`) titles fall
  back to the first heading/paragraph in the section, and the drawer still
  works.
- **Chapters** — the published `catalogue.json` at the site root
  (`../../../catalogue.json` from a topic directory). Neighbours are the
  previous/next entry of the same `course_id`, in catalogue order, linked through
  the entry's `localized_hrefs` (the routes P5 verified exist) with an English
  fallback when the reader's locale is not published for that chapter — never a
  guessed `/<locale>/` path. No catalogue → no chapter links and no
  next-chapter CTA (never an invented destination).
- **Consent** — `localStorage["zivon.consent"]`. Declined: no Ask entry and no
  per-block chips (voice is off on this device, so the affordance would be
  dead). Missing: the chip/Ask entry focus the §10.14 gate instead of pretending
  to listen.

## 4. Reading progress and completion

- **Current section** = the section wrapper that contains the band at 45 % of the
  viewport height (nearest section when above/below the stream). Drives
  `aria-current="location"` + the pen-blue marker in the drawer.
- **A section is "read"** after it has been the current section for a measured
  dwell; leaving it emits `EVT-section_viewed` (`frontend.section_view`,
  `EVT-F02`) with `section_id`, `concept_id` and a **measured** dwell bucket
  (`<5s` / `5-30s` / `>30s`). No fabricated buckets.
- **The bar** shows `max(scroll percentage ever reached, sections read / total)`
  so it never goes backwards. `aria-valuenow` is updated; nothing is announced
  per scroll tick.
- **Lesson complete** = every section read **and** ≥ 90 % of the document
  scrolled; emits `EVT-lesson_complete` once and stores `completed: true`.
- **Device-local store** `localStorage["zivon.progress"]`:

```json
{"v":1,"chapters":{
  "<course_id>/<topic_slug>": {
    "sections": {"sec-01": {"first_seen": 0, "dwell_s": 12, "dwell_bucket": "5-30s"}},
    "max_scroll_pct": 84, "last_section": "sec-05",
    "completed": false, "updated_at": 0
  }}}
```

The store is bounded (50 most recently touched chapters), never leaves the
device, and contains no free text and no identity.

**Handoff to F3:** `window.ZivonLessonShell.getProgress()` returns the current
chapter record; `window.ZivonLessonShell.setProgressSink(fn)` is called on every
write so F3 can mirror to `/v1/progress/events` when that API lands
(`NEED-019`). Do not add a second local store.

## 5. Bookmarks

- One toggle per section in the drawer (`aria-pressed`, label "Save"/"Saved"),
  stored device-local in `localStorage["zivon.bookmarks"]`:

```json
{"v":1,"items":[{"course":"class-9-physics","topic":"class-9-physics/describing-motion-around-us",
  "section_id":"sec-03","block_id":"b-07","title":"…","ts":0}]}
```

- Newest first, capped at 100; un-saving removes the entry. The record carries
  the section's first block id as the jump target so F3's `/app/bookmarks` can
  resolve a deep link. Emits `EVT-bookmark` (`frontend.bookmark`, `EVT-F13`)
  with `section_id` and `bookmarked` bool.

## 6. "Ask about this" (anchor to a block)

- One quiet graphite chip per block (every `[data-block-type][id]`), 40 px
  minimum, labelled with the block's human title for screen readers.
- Pressing it sets the **explicit anchor**: the next context snapshot reports
  that block (`block_id`, `block_type`, `block_title`, `block_text`) instead of
  the block nearest the viewport centre, opens the dock expanded, and rings the
  block with the pen-blue highlight. The anchor stays until another block is
  chosen or `ZivonLessonShell.clearAnchor()` runs — the dock's anchor chip keeps
  the student oriented.
- Emits `EVT-ask_about_this` (`frontend.ask_about_this`, `EVT-F14`) with
  `block_id`, `block_type`, `opened`. Consent-missing/declined never reports
  `opened: true`.

## 7. Voice context snapshot fix (regression contract)

`buildContextSnapshot()` must only ever anchor to real blocks:

- Blocks are `[data-block-type][id]` (legacy pages: ids matching `b-NN`).
  Section wrappers (`section.zn-section#sec-NN`) are **never** blocks.
- `visible_blocks` = the 12 blocks **nearest the viewport**, in document order
  (previously the first 12 on the page, which also left deep blocks typed as
  `text`).
- Type/title/text are collected for every block, so an explicit anchor deep in
  the lesson carries its real type and excerpt.

Regression tests: `testing/frontend/test_lesson_shell.py`
(`test_context_snapshot_excludes_section_wrappers`,
`test_ask_about_this_anchors_the_next_turn_to_the_block`).

## 8. States (11-state matrix, lesson shell rows)

| State | What the student sees |
|---|---|
| default | app bar, drawer closed, 2 px progress rule, per-block chips, end CTA |
| loading | static HTML first; drawer renders before the manifest and re-renders when titles arrive |
| empty | n/a (a published lesson always has sections; a page without `.zn-section`/blocks gets no shell) |
| partial | manifest missing → DOM-derived drawer titles, no chapter links; catalogue missing → no prev/next |
| error | any injected step throws → that step is skipped, the lesson stays readable (`ZivonShell.mount` isolates every step) |
| offline | shell is local-only: drawer, progress, bookmarks and chapter links are cached pages; no network needed |
| permission-denied | consent declined → Ask entry + per-block chips absent, `body[data-zn-voice="off"]`; reading unaffected |
| reduced-motion | section jumps are instant (`behavior: auto`), no smooth scroll |
| untranslated | shell strings carry `data-i18n="ui.shell.*"`; the reviewed English fallback shows until the translation bundle ships the keys |
| quota-exhausted | n/a in the shell (voice quota is the dock's state; reading/nav never metered) |
| consent-missing | Ask/chips focus the §10.14 gate, never open the mic |

## 9. Accessibility and performance

- Keyboard: Contents is a `button` with `aria-expanded`/`aria-controls`; the
  drawer is a `nav` (not a dialog) so the page stays scrollable; Esc closes and
  returns focus to the toggle; a section jump moves focus to the section
  (`tabindex="-1"`, `scroll-margin-top` clears the sticky bar).
- Targets: 44 px app-bar controls and section links, 40 px save/chip controls;
  focus ring is the shared 3 px pen-blue ring.
- Semantics: one `aria-current="location"` at a time; progress is a
  `role="progressbar"` with `aria-valuenow` and no live region; the coming-soon
  rows are `aria-disabled` statuses, not disabled buttons.
- Perf: one passive `scroll` listener coalesced through `requestAnimationFrame`;
  rect reads only for the section list (≤ 8 wrappers on the shipped pages) and
  for block anchoring in the existing snapshot path; the progress fill is a
  compositor-only `transform`. No new network on load beyond the existing
  `manifest.json` fetch and one `catalogue.json` read on published lesson
  routes.

## 10. Handoffs

| To | What | Notes |
|---|---|---|
| **F2 identity** | `ZivonLessonShell.setIdentity({name, href})` shows the signed-in student in the app bar; `body[data-zn-identity]` flips `guest`→`user` | guest-first default renders no identity chrome; no `/login` link until F2 ships |
| **F3 progress** | `getProgress()` + `setProgressSink(fn)`; mirror to `/v1/progress/events` (`NEED-019`) | keeps `zivon.progress` as the guest source of truth until sign-in merge exists |
| **F3 bookmarks** | `zivon.bookmarks` items carry `course`, `topic`, `section_id`, `block_id` for `/app/bookmarks` (`NEED-019`) | local-only today, no fake server sync |
| **F5 practice** | `EL-LES-01-105` "Practise this chapter" links to `/app/practice?chapter=…` once the hub exists | currently an honest "coming soon" status |
| **F6 speaking** | `EL-LES-01-106` "Explain it back" links to `/app/speaking?chapter=…` once it exists | currently an honest "coming soon" status |
| **Translation pipeline** | new `ui.shell.*` keys (`contents`, `chapter_contents`, `close`, `save`, `saved`, `sections_read`, `what_next`, `practise`, `explain_back`, `next_chapter`, `prev_chapter`, `all_chapters`, `ask`, `ask_about_this`, `soon`, notes) | attributes already ship; the bundle swap lands with no code change |
| **F1 nav** | Practice/Progress entries are `aria-disabled` statuses until those routes exist | flipping them to links is a `ready` flag in `shellNavLink` |

Element ids for nav destinations are duplicated between the desktop app bar and
the drawer's phone mirror (`EL-LES-01-093`…`095`), following the dock's
precedent for responsive duplicates.

## 11. Storage keys (additions to `shell-injection.md` §3)

| Key | Contents | Notes |
|---|---|---|
| `zivon.progress` | per-chapter sections read, max scroll %, completion | device-local, bounded, no identity |
| `zivon.bookmarks` | saved sections with their first block id | device-local, bounded, newest first |

Both are on the privacy page's device-wipe key list, so "Clear my data" removes
them with the consent record and the device pseudonym (`ZivonPrivacy`).

## 12. Tests

`testing/frontend/test_lesson_shell.py` (key-free, offline, headless Chromium):
shell mount and untouched body, drawer sections/current position, keyboard
(Esc, focus restore, jump), previous/next chapter resolution, device-local
progress + `EVT-section_viewed`, bookmark persistence across reload, explicit
anchor + dock expansion, context-snapshot filter regression, honest end CTA,
360 px frame, JS-off integrity, and a content-only fixture without manifest or
catalogue.
