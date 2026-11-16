# Motion and performance

A landing page that takes three seconds to show its headline has already lost
the reader it was written for. Motion and speed are not polish; they are part of
the argument.

`[E]` marks a published threshold or research finding, `[P]` a practitioner
convention, `[R]` a rule this repo has already decided.

## 1. The motion principle

**Motion must carry information, or it must not exist.**

Information means one of: *this appeared because you did something*, *this
changed*, *this is where to look*, *this is still working*. Anything else —
parallax, fade-in-on-scroll for every block, floating shapes, a logo marquee — is
decoration that costs frame budget, battery, and attention.

The test is the same removal test used everywhere in this bundle: **remove the
motion. Is any information lost?** If not, it was decoration.

## 2. The scroll narrative

Scrolling is the reader's action, not yours. Respect it.

**Allowed:**

- A **single reveal** when a section first enters the viewport, once, with no
  re-trigger on scroll up and down.
- A **sticky proof element** that stays while its explanation scrolls past — one
  per page, and only when the pairing is the point (a diagram with its caption).
- A **progress-independent diagram** that animates on user interaction (a slider
  moving the ray), because the motion *is* the content.
- A **transcript that follows the audio** while it plays, because the highlight
  tells the reader where they are.

**Not allowed:**

- **Scroll-jacking** — intercepting the wheel or hijacking the scroll position to
  drive a "story". It breaks keyboards, trackpads, screen readers, and reader
  trust.
- **Parallax** on the hero or any large element: it is a vestibular trigger `[E]`.
- **Reveal-on-scroll for every section**: it makes the page feel slow even when
  it is fast, and it hides content from readers who scroll quickly.
- **Auto-advancing carousels**, marquees, and rotating headlines: the reader sees
  one item and loses the rest.
- **Cursor followers, custom scrollbars, smooth-scroll hijacking.**

Rules of thumb `[P]`: interface feedback 120–200 ms; a section reveal 400–600 ms,
once; anything longer than 700 ms on a landing page reads as lag.

## 3. Reduced motion

`prefers-reduced-motion: reduce` does not mean "no animation". It means the
reader has asked the system to minimise non-essential movement, and the interface
should honor that `[E]`.

- **Honor the preference by default**, without a site-level toggle the reader has
  to find.
- **Remove**: parallax, large transforms, scale/zoom transitions, autoplaying
  loops, position animations that cross the viewport.
- **Keep**: opacity fades, colour/state changes, progress that conveys real
  state, and the *content* of an animation (show the final frame, do not animate
  to it).
- **Never** use `* { animation: none !important }` as the whole strategy: it
  removes state feedback along with decoration.

Relevant success criteria `[E]`: WCAG 2.2 **2.3.3 Animation from Interactions**
(AAA) — motion triggered by interaction can be disabled unless essential; and
**2.2.2 Pause, Stop, Hide** (AA) — anything that moves, blinks, or scrolls
automatically for more than five seconds needs a mechanism to pause, stop, or
hide it. This repo targets WCAG 2.2 AA, so 2.2.2 binds and 2.3.3 is the
aspiration worth meeting anyway.

Implementation shape:

```css
@media (prefers-reduced-motion: reduce) {
  .reveal { transition: none; }
  .hero-artifact { animation: none; }
  /* keep the state change, drop the travel */
}
```

```js
const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
// re-check on change, not just at load: the OS setting can flip mid-session
```

## 4. Core Web Vitals

The published thresholds, measured at the 75th percentile of page views `[E]`:

| Metric | Good | Poor | What it measures |
|---|---|---|---|
| **LCP** — Largest Contentful Paint | ≤ 2.5 s | > 4.0 s | when the main content appears |
| **INP** — Interaction to Next Paint | ≤ 200 ms | > 500 ms | responsiveness to every interaction |
| **CLS** — Cumulative Layout Shift | ≤ 0.1 | > 0.25 | how much the page moves while loading |

A page passes only if all three are good `[E]`. Two out of three is a fail.

### What breaks each one on this page

| Metric | The usual cause here | The fix |
|---|---|---|
| **LCP** | the hero artifact is a large unoptimised screenshot; a webfont blocks the H1; a client-side render | inline critical CSS, preload the two font files, serve the artifact as a sized AVIF/WebP with `fetchpriority="high"`, render the H1 in HTML |
| **INP** | a JS island (demo, language switch) doing work on the main thread during interaction | keep the island small, defer it, do no work on `scroll`, break long tasks |
| **CLS** | the demo card has no reserved height; fonts swap to a different metric; a banner injects at the top | fixed aspect-ratio boxes, `size-adjust`/fallback metrics, never inject above existing content |

### Lab versus field

Lab numbers (Lighthouse, throttled) tell you whether the page *can* be fast.
Field numbers (real users) tell you whether it *is*. Core Web Vitals are defined
on field data at p75 `[E]`; at small traffic volumes there is no field data yet,
so use lab numbers plus a real-device test and say which one you are quoting.

## 5. The repo's low-end-Android budget

The hard budget blocks a release `[R]`:

- interactive within about **3 seconds** on the `weak-android` profile;
- **no long task over 200 ms** on the interaction path;
- animations target **60 fps**, with a **24 fps floor** under 4× CPU throttle;
- no jank or layout thrash while scrolling;
- the tab stays inside the measured memory envelope (pinned after the first
  measurement).

The soft budget is monitored, not blocking `[R]`: first-party shell/app JS
≤ **150 KB gzip** per page, CSS ≤ **50 KB gzip**, with per-topic `i18n` and
`page.js` reported separately.

The old "60 KB" figure was a downloaded/parsed **JavaScript byte budget, not a
RAM budget**. Do not reintroduce it as a memory claim, and do not block a
feature on bytes alone.

## 6. Media rules

| Rule | Why |
|---|---|
| **No autoplay, ever** — audio or video | a page that makes noise in a classroom or beside a sleeping sibling is closed, not read |
| **Every audio has a transcript**, visible without JS | WCAG 2.2 SC 1.2.1 requires a text alternative for prerecorded audio-only content `[E]` |
| **Every video has captions** and a transcript | SC 1.2.2 `[E]` |
| **`preload="none"`** on demo media | the reader may never press play; do not spend their data |
| **A poster frame that is a real frame** | a fake poster is a promise the media breaks |
| **A visible stop control** while playing | SC 2.2.2 `[E]` |
| **The transcript is the fallback, not the substitute** | the demo is proof; the transcript is what makes it accessible |

Audio is the product's proof, so its failure modes matter more here than
anywhere else on the site. A blocked autoplay, a missing file, or a silent
failure must each render a readable state — see the state table in
[copywriting-and-microcopy.md](copywriting-and-microcopy.md) §8.

## 7. Fonts

- **Two families, bundled locally**, per the kit: Bricolage Grotesque and Courier
  Prime. Landing pages make no external font calls `[R]`.
- **Preload the two faces that paint above the fold**; the rest load on demand.
- **Match fallback metrics** so the swap does not shift layout (CLS). A serif
  fallback for a grotesque is a visible reflow, not a detail.
- **Subset if Devanagari is used above the fold**; a full Devanagari face is
  large, and the hero is the one place it is on the critical path.

## 8. The demo island

The voice demo is the only place the landing page needs JavaScript. Treat it as
an island with a contract:

- **No framework.** Vanilla JS, one file, deferred.
- **The page argues without it.** Every claim, price, source and objection is in
  the HTML; the island only adds playback.
- **It owns its layout before it loads**: reserved dimensions, poster, transcript
  in the DOM.
- **It does nothing on scroll.** No `scroll` listeners on the interaction path.
- **It fails visibly.** An error state with a sentence, never a silent no-op.
- **It is measured**: bundle size in the perf report, INP contribution, and one
  real-device run.

## 9. Test protocol

Record all of this in the PR; a claim of "fast" without numbers is an opinion.

1. **Lab run** on the built page, mobile, simulated Slow 4G + 4× CPU: LCP, INP
   (interact with the demo and the language switch), CLS. Report all three.
2. **Real device**: one low-end Android (the `weak-android` profile if available),
   on a real network, cold cache. Time to interactive hero and time to first
   demo frame.
3. **Reduced motion**: repeat the run with the OS setting on. Confirm nothing
   essential disappears and nothing large moves.
4. **JS off**: the page must still make the argument. Screenshot it.
5. **360 px, 390 px, 1280 px**: no horizontal overflow, CTA visible without
   scrolling on the small sizes.
6. **Throttled scroll**: scroll the full page at 4× CPU throttle and watch for
   long tasks and dropped frames.

A page that passes 1 but fails 2 is a page for reviewers, not for students.
