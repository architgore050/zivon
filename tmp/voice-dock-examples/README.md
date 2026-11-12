# Voice dock — three directions for the expanded sheet

**Status:** throwaway design proposals, 11 Nov 2026. **Not** production code, **not** a doctrine
change. `frontend/assets/zivon.{css,js}` and `docs/frontend/design-doctrine.md` are untouched.

**Doctrine guard check:** §10.12 “Voice dock” **does exist** (DCR-002, adopted 2026-11-10), so the
AGENTS.md guard is satisfied and dock design work may proceed. Everything here proposes an
amendment to that section for founder review; nothing is canon until approved.

These are *directions*, not pixel-final specs: each is a working, self-contained page with the real
tokens, fonts, state machine, typable input and a toggle mic. Review the feel, the element count and
the hierarchy; then pick a direction and we amend §10.12 once.

---

## Files

| File | What it is |
|---|---|
| `a-field-notes-chat.html` | **Direction A — Field Notes chat.** Familiar chat anatomy in notebook clothes. Recommended. |
| `b-ledger.html` | **Direction B — Ledger.** Two-column Q/A log with margin labels, no bubbles. |
| `c-slate.html` | **Direction C — Slate.** Compact “earlier” rail + one large current answer. |
| `screenshots/` | 18 PNGs: each direction × mobile 390×844 / desktop 1280×800 × expanded, listening or offline, collapsed. |
| `shoot.cjs`, `check.cjs` | The Playwright capture and interaction scripts (dev-only; not shipped). |
| `README.md` | This file. |

The older six shape candidates (`01-bottom-bar.html` … `06-status-strip.html`, `_dock.css`,
`_dock.js`, `index.html`) are the **earlier round** that decided the sheet shape. They are kept as
history; ignore them for this review.

Open any file by double-click (`file://`) or serve the repo root:

```bash
python3 -m http.server 8765
# then open http://127.0.0.1:8765/tmp/voice-dock-examples/a-field-notes-chat.html
```

The top-left **MOCK** bar switches state (`idle`, `listening`, `thinking`, `speaking`, `text-only`,
`reconnecting`, `offline`, `mic-denied`) and containment (`Sheet`, `Strip`, `Tab`). URL parameters
work too: `?state=offline&view=collapsed&still=1`.

Regenerate screenshots (requires Playwright; no app dependencies):

```bash
python3 -m http.server 8765 --bind 127.0.0.1 &
NODE_PATH=~/.npm/_npx/*/node_modules node tmp/voice-dock-examples/shoot.cjs
NODE_PATH=~/.npm/_npx/*/node_modules node tmp/voice-dock-examples/check.cjs
```

Verified: all three pages load and run **with no console errors**, and the mic toggle, typed send,
offline queue, collapse/reopen, anchor highlight and language cycle all work (`check.cjs` passes).

---

## 1. Critique of the current expanded dock

Measured against §0.1 (“if this element were removed, would the student lose a capability?”) and
against what people expect from a normal AI chat. The current sheet stacks **nine rows** and carries
about **19 interactive controls plus 8 pieces of status chrome**; the minimum set below is 12 slots.

| Current element | Purpose today | Verdict | Why |
|---|---|---|---|
| `grabSheet` “— Collapse” text button | collapse the sheet | **merge** | A whole 44 px text row for a move the header already implies. Make it a 44 px chevron in the sheet header, or keep a grab rule for dragging. |
| Anchor chip (`b-13 · worked example`) | show what the tutor is looking at; tap scrolls + rings the block | **keep** | The product’s differentiator and a real capability. It is also the only place the single tape corner belongs. Shorten the copy: block id + short title, nothing else. |
| Identity line “I’m an AI tutor — I see this lesson page, not your room.” | one-time disclosure (P7) | **merge** | The disclosure is required; permanent header chrome is not. Show it once as a small system line at the top of an empty transcript, then never again. It currently occupies prime header space on every visit until storage says otherwise. |
| State row: `MIC OFF` stamp, `TUTOR · TEXT` chip, state label, thinking sweep, 5 level bars, Retry | status | **remove as a row; redistribute** | This is the core of the “too many little status messages” problem. It duplicates the same state in three places (state label, caption, strip caption) and mixes a per-message property (`TUTOR · TEXT`) with a global state. Keep one conditional line inside the conversation, next to where the answer will appear. |
| `TUTOR · TEXT` chip | mark a text-only tutor reply | **remove** | A per-message fact shown as global chrome. If it matters, tag the message itself (`text reply` in its meta line). |
| `MIC OFF` stamp | mic-denied honesty | **keep (conditional)** | Shape + words is a doctrine rule; keep the stamp only in `mic-denied`, inline at the composer. It should not exist in the other states. |
| Retry button in the state row | recover from no-match/timeout | **move** | Retry belongs to the failed/last answer, where the student is looking. A global button next to a status label is hard to associate. |
| Thinking sweep + level bars | show activity | **merge** | One indicator, inline in the thread. Bars for listening, a 2 px sweep for thinking, bars + caret for speaking. Never both a sweep and a row of bars and a text label and a caption for the same moment. |
| Transcript panel (≤34 dvh, `You:`/`Tutor:` prefixes) | read what was said | **keep, redesign** | The surface is right; the anatomy is not. No role hierarchy, no time, no copy, no retry, no streaming into the transcript, and the maximum height leaves the sheet mostly chrome. Give the transcript the sheet’s remaining height. |
| Caption row + “Captions” checkbox | live text + a11y | **remove the toggle; keep the captions** | Captions are the tutor text itself — streamed into the transcript. A captions on/off checkbox is a settings item, not a primary surface control, and the current caption duplicates the state label verbatim. |
| `Stop` button | stop playback | **merge** | Pressing the mic while speaking already interrupts (barge-in). One stop target, not two. Keep a visible stop state on the mic. |
| Composer mic (56 px) + “Speak” word + typed input + Send | voice + text | **keep, simplify** | The word “Speak” is redundant beside a mic. Make the mic the toggle (see §3) and let the input be the text path. |
| Help chips (“Is graph ka slope…”, etc.) | recovery prompts | **merge into empty + error states** | Useful when the student is stuck, noise in normal use. Show them only when there is no conversation or after no-match/denied. |
| “What the tutor remembers” + Clear session memory | privacy / memory view | **remove from dock** | This is a privacy control, not a doubt control. It belongs in settings / the privacy page (`SCR-PRIV-01`), not in a 20-second overlay. A `<details>` here costs a row and invites accidental destructive taps. |
| “Language” button | scrolls to the page language bar | **remove** | It does not change language; it scrolls. A control labelled Language that only scrolls is dishonest. The dock inherits the page language. If a dock-level switch is wanted, it must actually switch. |
| “Hide dock” button | hide to tab | **merge** | Keep the capability, demote the affordance: one quiet text button in the sheet header or footer. The reversible tab already exists. Do not spend a 44 px row on it. |
| 92 px collapsed strip with grab, caption, Type, Hide, mic | glance + resume | **keep, shrink** | Five controls in 92 px. Keep the grab rule, one line of the last answer and the mic; opening the sheet is the “Type” affordance. 60–68 px is enough. |
| 5 s silence-close to collapsed | get out of the way | **remove** | It fires while a student is reading or looking at the page — the sheet vanishes mid-sentence. Collapse on user action; if auto-collapse survives, make it minutes and suppress it while the answer is being read. |
| Stored `expanded` → starts collapsed | never auto-expand | **keep** | Correct and boring. |

### What a normal AI chat has and this dock does not

- **Role hierarchy you can see at a glance.** A text prefix (`Tutor:`) is not hierarchy. Use a role
  label + layout (indent/rule/weight), or margin labels (B).
- **Timestamps / sequence.** Not mandatory, but 11 px typewriter time costs one line and orients a
  student who looks away and comes back. A has them; C keeps them only in the rail.
- **Copy.** Students screenshot or copy a definition into their notes. Keep it on the latest answer
  (all answers if cheap) as a 44 px hit target with 11 px text.
- **Retry / regenerate.** Errors currently end in a global retry; a chat puts it under the answer.
- **Streaming text in the transcript.** Today only the caption streams; the transcript receives the
  final line. That makes the transcript feel like a log, not a conversation.
- **Stick-to-bottom + “latest” affordance.** The current state change rebuilds the transcript
  (`innerHTML` replacement in `renderAgentState`), which can reset scroll and re-announce the whole
  list to a screen reader. Append-only rendering is required in the real implementation.
- **An empty state that teaches.** One line (“Poochho kuch bhi is page se”) + two example questions
  is more useful than a permanent hidden help row.
- **Honest queueing.** Offline currently disables the path or shows copy; a sent typed message
  should appear in the thread marked `queued`, not disappear.
- **A text-only state that is a state, not an error banner.** The ledger line belongs under the
  composer, once.

---

## 2. The three directions

All three share the same shell: fixed bottom sheet, 2 px ink top rule, paper surface, single tape
corner on the anchor chip, local fonts (Bricolage / Courier Prime / Caveat), 44 px minimum targets,
safe-area bottom padding, no gradients, shadows, blur or glow. All three use a **toggle mic**
(tap to start, tap to stop), a single conditional status line, and the same six-turn Hinglish
Physics transcript (impulse vs change in momentum). All differ only in **how the transcript is
organised**.

### A — Field Notes chat (recommended)

Familiar chat anatomy, notebook materials. Tutor answers are typed full-width on the paper; the
student’s line is indented behind a 3 px ink rule; role labels are handwritten (`Caveat`), times are
11 px typewriter. One line per state, inside the thread, only while it is true. Copy/Retry sit under
the newest answer. The composer is one row: mic toggle, input, Send. Header: anchor chip, language
chip, collapse chevron.

- **Pros:** immediately legible as a chat; best mobile measure (full width for the tutor); scales to
  6+ turns; lowest implementation risk (closest to the current DOM); every element is a familiar
  chat affordance.
- **Cons:** the least “notebook” of the three — the paper does most of the brand work; the student
  line is a conventional indent; on a narrow phone the last 6 turns still require a scroll.
- **Screenshots:** `screenshots/a-field-notes-chat-*.png`.

### B — Ledger

A two-column log: a 68 px margin column carries `You`/`Tutor` + time in handwriting; the answer runs
in the body column. Student lines get a paper-light inset with a 3 px ink rule. A handwritten
“Doubts” heading with a pen underline opens the page.

- **Pros:** the most “notebook page” of the three; the margin labels make roles unmistakable without
  bubbles; the tightest visual rhythm; reads like a worked log, which matches a tutor.
- **Cons:** the margin costs ~25 % of the text column on a 390 px phone (≈32 characters per line,
  tall paragraphs); it scans as a record, not a live chat; the heading scrolls away immediately in a
  long session. Best on a tablet/desktop, weaker on the actual demo phone.
- **Screenshots:** `screenshots/b-ledger-*.png`.

### C — Slate

A compact “Earlier” rail (one line per prior turn, 11 px, all six turns accounted for) above one
large current exchange: the question at 13 px, the answer at 16 px. Voice-first hierarchy: the
current answer is the hero, history is scannable, not readable.

- **Pros:** the best answer to “I asked one doubt, show me the answer”; the current answer gets the
  whole width and a comfortable measure; the transcript stays visible without competing; fewest
  elements.
- **Cons:** least like a normal chat; history is truncated by design, so a student cannot re-read an
  earlier explanation in full; when a new question starts, the previous answer moves into the rail
  and becomes a one-liner, which can feel lossy; requires a different rendering model (current
  exchange vs rail), not just styling.
- **Screenshots:** `screenshots/c-slate-*.png`.

### Recommendation: **A**

The founder’s brief is “closer to a normal AI chat, still a paper notebook sheet”. A is the only
direction that satisfies both without a trade-off the demo cannot afford: it is conventional where
convention helps (roles, times, copy, retry, a composer), and the notebook lives in the materials,
the handwritten role labels, the tape and the anchor. B is more distinctive but spends 25 % of the
phone’s text width on its margin and reads as a log; C is the strongest for a single doubt but hides
the conversation the founder asked to make scannable. If time allows after the demo, borrow C’s
“earlier” rail for a collapsed/peek mode, and B’s margin labels for a desktop-only variant — but
ship A.

---

## 3. What to decide

**Removal candidates (delete from §10.12 and the implementation):**

1. The separate state row (`EL-LES-01-044`) with sweep + bars + label + stamp + retry.
2. The `TUTOR · TEXT` chip (`EL-LES-01-045`).
3. The captions checkbox (`EL-LES-01-049`) and the separate caption line (`EL-LES-01-048`);
   captions are the streamed transcript.
4. The global Retry button — move to the newest answer.
5. “What the tutor remembers” + clear memory (`EL-LES-01-054`) — move to settings/privacy.
6. The “Language” button (`EL-LES-01-055`) — it scrolls, it does not switch.
7. The “Hide dock” buttons in the strip and meta row — keep one quiet entry in the sheet header.
8. The “Type” button in the collapsed strip — opening the sheet reveals the input.
9. The 5 s silence-close (or raise it to minutes and never while an answer is on screen).
10. The `Stop` button — the mic is the stop target.

**Mic: toggle, not hold.** Hold-to-talk is the single biggest flake source on real phones: the
pointer leaves the button while scrolling, the permission prompt interrupts the hold, iOS raises a
context menu on long-press, and the current code deliberately drops the turn if the student releases
while the permission dialog is open (`viaPointer && !pointerHeld`). Toggle removes every timing
dependency and gives a clear stop target. Mitigate the obvious risk (mic left on) with: a filled mic
+ bars + “tap to stop” while listening; server endpointing auto-stop; a hard maximum duration; stop
on `visibilitychange`; and no mic start without a gesture. This requires amending §10.12 interaction
rule 4 and the ADR-0018 wording (“hold-to-talk is the default” → “tap-to-start/tap-to-stop is the
default”). **Founder decision needed.**

**Status lines: keep at most one, only when it changes what the student can do.** Keep:
listening (mic hot + how to stop), thinking (answer coming), reconnecting/offline (what still works),
text-only (why voice is off + what is free), mic-denied (MIC OFF + typed path). Remove: idle/ready
duplicate copy (“Mic dabao aur poochho” repeated in three places), endpointing (sub-200 ms, should be
invisible), and the permanent connection line (a 1 px dotted rule is enough). Never show a status
and a caption and a strip caption for the same moment.

**Type scale (sheet only, not the lesson page):**

| Role | Size / line | Font |
|---|---|---|
| Tutor answer | 14 px / 1.45 mobile, 15 px / 1.5 ≥600 px | Courier Prime 400 |
| Student line | 13 px / 1.45 | Courier Prime 400 |
| Role label | 16 px / 1 | Caveat 700 |
| Time, meta, status, tools | 11–12 px | Courier Prime |
| Anchor / language chip | 13 px | Courier Prime 700 |
| “Earlier” rail (C only) | 11 px / 1.7 | Courier Prime / Caveat labels |

4/8 px rhythm inside messages; the 36 px ruled rhythm belongs to the lesson page, not the overlay.
The current dock is airy because every row is a 36–44 px status block — that is where “too large /
loose” comes from, not from the transcript’s font size alone.

**Minimum element set (the removal-test survivor list):**

1. Sheet edge + optional 4 px grab rule (2 px ink top border stays).
2. Anchor chip (block id · short title; tape corner; tap = scroll + ring).
3. Language chip (inherits page language; cycles only if it actually switches strings).
4. Collapse control (44 px chevron) + one quiet “Hide”.
5. Transcript: role label, text, time, streaming caret/last-answer state.
6. Copy + Retry on the newest tutor answer (44 px targets, 11 px text).
7. One conditional in-thread status line.
8. Mic toggle (48–56 px) with a visible pressed/stop state.
9. Typed input + Send (always in expanded, never removed by errors).
10. One ledger line, only in `text-only`.
11. Hidden 44 px tab (“Ask” + mic).
12. Collapsed strip: grab rule + one-line last answer + mic (no Type, no Hide).

Everything else in the current sheet is chrome.

---

## 4. Implementation notes for the real change (not done here)

- **Files to change after approval:** `frontend/assets/zivon.css` (dock block, ~300 lines),
  `frontend/assets/zivon.js` (`ZivonVoiceDock.lazyMount`, `renderAgentState`, mic wiring), plus
  `docs/frontend/design-doctrine.md` §10.12 and the F-ADD-VOI-01 surface/element list in
  `docs/product/features.md`.
- **State machine:** the mock implements the six required states plus `mic-denied`. The real client
  has 18 states; the new sheet must map the rest to the same one-line pattern (`error:*` → sentence +
  Retry on the last answer + typed path).
- **Rendering:** append messages, do not rebuild the transcript on every state tick. The current
  `renderAgentState` replaces every child, which resets scroll and re-announces the list. Use
  `role="log"` + `aria-live="polite"` and announce only the appended line (throttled for streaming).
- **Perf:** no filters, blur or shadows; transform/opacity only for the bars/sweep/caret; the DOM
  budget stays under the current ≤90 idle / ≤140 at six turns.
- **A11y:** 44 px minimum; focus ring 3 px pen-blue / 3 px offset (visible in the offline screenshot);
  `aria-pressed` on the mic; focus returns to the mic after a turn; Esc = stop then collapse; Enter
  sends; reduced motion = static bars, instant text.
- **Honesty:** offline sends append a `queued` line to the thread; the mic is disabled while
  offline/reconnecting/text-only; text-only is a state with a ledger line, not a banner.
- **Copy:** Hinglish strings in the mock are draft; native review is still owed (doctrine §10.11).

---

## 5. Screenshot index

| Direction | Mobile 390×844 | Desktop 1280×800 |
|---|---|---|
| A | expanded, listening, collapsed | expanded, offline, collapsed |
| B | expanded, listening, collapsed | expanded, offline, collapsed |
| C | expanded, listening, collapsed | expanded, offline, collapsed |

Files: `screenshots/<direction>-<viewport>-<state>.png`. All captured at deviceScaleFactor 2 with
animations frozen (`?still=1`) and fonts fully loaded; every page reported zero console errors.
