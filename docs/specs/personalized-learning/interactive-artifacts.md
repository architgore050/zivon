# Interactive artifacts — generation, sandbox, review, cache

Status: **spec, not implemented (2026-11-17).** Owner workstream: PL3
([`workstreams.md`](workstreams.md)). Product view:
[`spec.md`](spec.md) §4. The turn that requests an artifact is specified in
[`agent-and-rag.md`](agent-and-rag.md) §4.4.

An artifact is **untrusted generated code**. Every control below assumes the
model will eventually produce something unsafe; the design must survive a lint
miss, not hope for one.

---

## 1. What an artifact is

| Kind | Shape | When the agent should ask for one |
|---|---|---|
| `simulation` | one self-contained HTML document with inline CSS/JS, a canvas (`480×320` backing store) and 1–3 native range controls | a relationship changes with a parameter (ray angle, object distance, force, slope) and manipulating it teaches faster than prose |
| `diagram` | one self-contained HTML document with inline SVG (or a canvas that draws a static figure) | a labelled schematic (ray diagram, free-body arrows, apparatus) where the static SVG would be hand-computed |

Not artifacts: a generated page (that is the factory's job), a video, audio, a
PDF, a chart that could be a static SVG in the turn text, or anything that
needs data from another student, the network, or the account.

One artifact per teaching slice, at most **4 per session** and **12 per user
per day**. The agent may ask; the server may refuse (budget, quota, "text is
enough") and the turn continues.

---

## 2. Artifact request contract

The decide call returns:

```json
{
  "kind": "simulation",
  "title": "Concave mirror: move the object",
  "learning_goal": "See how the image moves as the object crosses the focus",
  "controls": [
    {"id": "u", "label": "Object distance (cm)", "min": 5, "max": 60, "step": 1, "initial": 30}
  ],
  "cited_claim_ids": ["c-03", "c-07"],
  "why": "the student's wrong answer treats the image as always real"
}
```

Validation (server, before any build call):

- `kind` ∈ {simulation, diagram}; `title` ≤ 120 chars; `learning_goal` ≤ 200.
- `controls` ≤ 3 for a simulation; 0 for a diagram; `min < max`, `step > 0`,
  `initial` inside the range; ids `[a-z][a-z0-9_]{0,15}`.
- `cited_claim_ids` ⊆ the claims of the retrieved excerpts for this turn (the
  prompt supplies them as `c-01…`). Unknown ids → dropped; zero remaining →
  the build proceeds but the artifact is marked `weak_grounding` and the turn
  keeps its citations.
- The artifact spec must contain **no student free text** (the builder prompt
  gets the concept, claims, and a generic confusion label — never the weakness
  text, never the personal instructions).

---

## 3. Generation pipeline

```
request ─▶ validate spec ─▶ build call (model) ─▶ lint (hard) ─▶ headless render gate
                │                    │                  │                 │
                │                    │                  └─ retry ≤ 2 ──────┤
                └─ reject ───────────┴───────────────────────────────────▶ failed ─▶ fallback
                                                                           │
                                                                  store content-addressed
```

1. **Build call** — one model call (`reasoning_effort=medium`, deadline 120 s)
   reusing the factory's discipline:
   - the live design doctrine + palette (`factory/design.py`),
   - the Visual Builder contract (`factory/interactive.py`'s skeleton + laws:
     compute geometry from the cited equations, never hand-draw it; axes are
     data; no external assets),
   - the cited claims and equations,
   - the artifact output contract (§4).
2. **Lint-in-retry** — the model sees its own violations and gets up to 2
   rebuilds, exactly like `05-interactive`; lint runs inside the loop.
3. **Hard lint** — any hit is a failure, never a warning:
   - reuse `factory/lint.py` rules (no `eval`, `new Function`, `document.write`,
     `fetch`, `XMLHttpRequest`, `WebSocket`, `EventSource`, `sendBeacon`,
     dynamic `import()`, `require`, `importScripts`, string-literal `http(s)://`,
     inline `<script>` creation, external `src`/`href`, `@import`,
     `url(http…)`);
   - artifact-specific: no `<form>`, no `localStorage`/`sessionStorage`/
     `indexedDB`/`document.cookie`, no `window.top`/`window.parent` navigation,
     no `postMessage` to `*` except the one documented harness channel, no
     `<iframe>`/`<object>`/`<embed>`, no `data:` URL except `img`/font, no
     `javascript:` URL, no clipboard APIs, no `Notification`, no fullscreen.
4. **Headless render gate** (build-time, Playwright, key-free):
   - load the artifact document with **all network requests aborted**; any
     attempted request is a failure;
   - capture console errors/warnings and unhandled rejections — any error fails;
   - assert `scrollWidth <= clientWidth + 2` at 360 px;
   - run 3 s, collect a frame-time sample via the harness (`postMessage`), fail
     if median < 24 fps or any long task > 200 ms;
   - assert the artifact posts `ready` within 5 s;
   - assert a `prefers-reduced-motion: reduce` context renders a static frame.
5. **Store** — content-addressed (`artifact_id = sha256(canonical spec +
   prompt_version + doctrine_hash + schema_version)[:32]`), status `ready`.
6. **Failure** — status `failed` + a machine reason (`lint`, `render`,
   `timeout`, `budget`); the turn shows the fallback; one retry is allowed only
   for a transient route error, never for a lint failure.

The build is **asynchronous** relative to the teaching stream: the turn emits
`turn.artifact {status: pending}` immediately and the client polls
`GET /v1/personalized/artifacts/{id}` (or receives `turn.artifact.ready` on the
same SSE if it finishes within the stream window).

---

## 4. Generated HTML contract

The artifact document is one file. The builder emits:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; frame-src 'none'; child-src 'none'; worker-src 'none'; media-src 'none'; form-action 'none'; base-uri 'none'">
  <style>/* artifact-local only; doctrine palette values; no @import */</style>
</head>
<body>
  <main class="zn-art" aria-labelledby="art-title">
    <h1 id="art-title">…</h1>
    <label for="u">Object distance (cm)</label>
    <input id="u" type="range" min="5" max="60" step="1" value="30">
    <canvas width="480" height="320" role="img"
            aria-label="Ray diagram: … state summary …"></canvas>
    <p class="zn-art-read" aria-live="polite">…text mirror of the canvas state…</p>
  </main>
  <script>/* artifact-local only; no network/storage/parent access */</script>
</body>
</html>
```

Rules:

- **Doctrine** (`docs/frontend/design-doctrine.md` §10.6/§10.7): paper-light
  card surface, ink structure, graphite guides, pen-blue live quantity, clean
  geometry (no hand-wobble), no gradients/shadows/blur/grain, labels in the
  page language, SI units untranslated. An artifact is a lesson-page device, so
  §10 applies here even though the session chrome uses §1–§9.
- **Responsive**: 100% width, fixed-aspect box, no horizontal overflow at
  360 px; the canvas backing store stays `480×320` and is scaled by CSS; touch
  targets ≥ 40 px.
- **Accessibility**: one `<h1>`; every control has a `label for`; the canvas has
  `role="img"` + an `aria-label` that names the current state; an
  `aria-live="polite"` text mirror (`.zn-art-read`) reflects the live values
  without writing on every animation frame (throttle ≥ 250 ms); correct/incorrect
  is never colour-only; keyboard operable; `prefers-reduced-motion` renders a
  static first frame and a visible Play control.
- **Performance**: `requestAnimationFrame` only; no timers < 16 ms; no layout
  reads in the frame loop; stop the loop when paused/off-screen; no long task
  > 200 ms; target 60 fps, floor 24 fps at 4× CPU throttle.
- **Size**: ≤ 120 KB of HTML (CSS/JS inline), ≤ 1,500 DOM nodes, ≤ 3 controls.
- **No external assets**: fonts fall back to the system stack; images only
  `data:` (preferably none — SVG/canvas only).
- **Harness channel** (the only allowed `postMessage`): the document posts
  `{source:"zivon-artifact", v:1, type:"ready"|"state"|"fps"|"error", ...}` to
  `window.parent`; it never listens for privileged commands except
  `{source:"zivon-host", type:"pause"|"resume"|"reload"}`. The host validates
  `event.source === iframe.contentWindow` and the schema; nothing from the
  message is rendered as HTML.

---

## 5. Sandbox

### 5.1 Iframe attributes

```html
<iframe
  src="/v1/personalized/artifacts/{artifact_id}"
  title="{artifact title}"
  sandbox="allow-scripts"
  referrerpolicy="no-referrer"
  allow=""
  loading="lazy"
  style="width:100%;aspect-ratio:3/2;border:0">
</iframe>
```

- `allow-scripts` **only**. No `allow-same-origin` (the document gets an opaque
  origin: no cookies, no localStorage, no parent DOM), no `allow-forms`, no
  `allow-popups`, no `allow-top-navigation*`, no `allow-modals`, no
  `allow-downloads`, no `allow-pointer-lock`, no `allow-presentation`.
- `allow=""` disables every permissions-policy feature (camera, mic,
  geolocation, clipboard, payment, USB…).
- The iframe is `loading="lazy"`; it is paused when off-screen
  (`IntersectionObserver` → `postMessage` pause).

### 5.2 Document and response headers

Served by the backend at `/v1/personalized/artifacts/{id}` (owner session
required, `GET`, no CSRF needed):

| Header | Value |
|---|---|
| `Content-Type` | `text/html; charset=utf-8` |
| `Content-Security-Policy` | `sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; frame-src 'none'; child-src 'none'; worker-src 'none'; media-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self' <APP_ORIGIN>` |
| `X-Content-Type-Options` | `nosniff` |
| `Referrer-Policy` | `no-referrer` |
| `Cache-Control` | `private, max-age=86400, immutable` (content-addressed) |
| `X-Robots-Tag` | `noindex, nofollow` |
| `Cross-Origin-Resource-Policy` | `same-origin` |

The CSP is enforced twice: the response header and the in-document `<meta>`
(defense in depth). `sandbox` in the CSP header also protects a top-level
navigation to the URL (if a student pastes it): the document is sandboxed even
outside the iframe.

### 5.3 Origin strategy

| Environment | Artifact origin | Why |
|---|---|---|
| Local / compose | same origin, `/v1/personalized/artifacts/{id}` | simplest; the iframe sandbox still gives an opaque origin |
| Production (recommended) | dedicated origin `artifacts.<domain>` (same backend, separate hostname; `frame-ancestors` restricted to the app origin) | a same-origin compromise (a future XSS in the shell) cannot read artifact storage or vice versa; the host-only session cookie is not sent to the artifact host |

The dedicated origin is a deployment decision (D-PL-09). Until it lands, the
same-origin route + opaque-origin sandbox is the accepted posture; it is
recorded, not silent.

### 5.4 What the sandbox guarantees

- No network: CSP `connect-src 'none'` + `default-src 'none'`; no forms; no
  navigation (sandbox); no popups.
- No storage/cookies: opaque origin; APIs throw; lint also rejects them.
- No parent access: `allow-same-origin` absent; `window.parent` is cross-origin;
  the only channel is the validated `postMessage`.
- No top navigation: sandbox without `allow-top-navigation`; links are not
  rendered by the builder (lint rejects `<a href>` except `#`).
- No downloads/modals/fullscreen: not allowed by the sandbox.
- Crash containment: a runaway loop only freezes its own frame; the host
  watchdog unloads the iframe after 10 s without `ready` or after 60 s of
  runtime, then shows the fallback.

---

## 6. Review pipeline (build-time) and runtime monitoring

| Gate | When | Blocks | Evidence |
|---|---|---|---|
| Spec validation | before build | malformed/oversized/ungrounded spec | `personalized_usage` row `outcome=rejected` |
| Lint | in the build retry + final | any hit | `lint_hits` count + rule ids (no HTML) |
| Headless render | after lint | console error, network attempt, overflow, fps floor, no `ready` | render report (counts, timings) |
| Deterministic eval | CI (`EV-PL-003`) | seeded unsafe artifacts and a golden good artifact | `runs/evals/<date>/…/EV-PL-003.json` |
| Student report | runtime | does not block; feeds the inbox | `problem_report` row (`category=artifact`) |
| Operator purge | manual | removes a cached artifact by hash | audit log |

The render gate runs **outside** the student request path (the turn has already
delivered text). It executes in a sandboxed Playwright context with network
aborted; the report stores timings and counts only, never the artifact HTML in
logs.

A human/agent design review is **not** in the per-artifact loop (cost); the
doctrine + lint + render gate is the gate. The content-quality review lens
(`skills/code-review/review-content-quality/`) applies to the artifact
**builder prompt** and its eval goldens when they change, not to each artifact.

---

## 7. Cache, versioning, deletion

- **Key:** `artifact_id = sha256(canonical_json(spec) + "|" + prompt_version +
  "|" + doctrine_hash + "|" + schema_version)[:32]`.
  `doctrine_hash` is the SHA-256 of `docs/frontend/design-doctrine.md`; any
  doctrine edit invalidates the cache.
- **Shared cache:** artifacts contain no student data, so identical specs reuse
  one row across students/sessions. The response is still owner-authenticated
  and only served when referenced by one of the caller's sessions (or when the
  caller is the owner of a session that references it). This avoids an open
  content proxy while keeping the cache global.
- **Reference counting:** messages store `artifact_id`; a nightly job deletes
  `ready` artifacts with no referencing message for 30 days. `failed` rows are
  purged after 7 days. Deleting a session drops its references; the artifact
  row survives until the cache window.
- **Versioning:** `schema_version`, `prompt_version`, `doctrine_hash`,
  `model`, `created_at` are stored per row; the viewer shows a provenance line,
  not a version number.
- **Purge:** operator `DELETE /admin/personalized/artifacts/{id}` (admin auth,
  audit row) for a bad artifact; a purge also marks every referencing message
  `artifact_missing` so the fallback renders honestly.
- **No cold copy:** artifacts are derivative content; they are rebuilt on
  demand. Nothing in the `storage-tiering` cold path references them.

---

## 8. Fallback

| Failure | What the student sees |
|---|---|
| Spec rejected | no card; the teaching text stands; no note (nothing was promised) |
| Build timeout/lint/render fail | card with "The visual didn't build. Here's the diagram instead." + a static SVG diagram from the decide payload, or the teaching text if none |
| Viewer crash/timeout | "The visual didn't load." + Reload + the same fallback |
| Embedder/index down | no new artifact requests (the decide call is told the budget is 0); text only |
| Reduced motion | static first frame + Play; no automatic animation |
| Quota/artifact budget | "Visuals are paused for today." + text; the turn is not blocked |

The fallback is part of the turn payload, not a client-side invention: the
server stores `fallback: {kind: "diagram"|"text", svg?: …}` when it requests an
artifact, so a failed build always has something honest to show.

---

## 9. Abuse controls

- Only the server creates artifacts; there is no upload path, no user HTML, no
  user-supplied URL.
- The build prompt never contains student free text or preferences (so an
  artifact cannot quote a student).
- Per-user/per-day build caps, per-session cap, global cap, concurrency
  semaphore; cache hits cost zero.
- Artifact size/DOM/time caps; lint rejects resource exhaustion patterns
  (`while(true)` cannot be proven safe — the runtime watchdog covers it).
- The artifact route requires a session and a reference; it is `noindex`,
  `no-store`-free but `private`, and never listed in the sitemap.
- Report path on every artifact card; repeated reports on the same hash move it
  to the admin queue and can trigger an operator purge.
- No `eval`/`Function` even in the builder's retry loop: a model that needs
  them gets the lint error as feedback (that is the point).

---

## 10. Tests (mapped to `EV-PL-003`)

| Test id | What it asserts |
|---|---|
| `DET-PL03-LINT` | each seeded defect (external fetch, `eval`, `localStorage`, form, top-nav link, oversized, missing label) fails the lint with its expected rule |
| `DET-PL03-DOC` | a golden good artifact passes lint, has the meta CSP, `role="img"`, label pairs, reduced-motion branch |
| `DET-PL03-RENDER` | headless: zero console errors, zero network requests, no 360 px overflow, `ready` ≤ 5 s, fps floor under 4× throttle |
| `DET-PL03-SANDBOX` | a red-team artifact cannot read parent DOM/cookies/localStorage, cannot navigate top, cannot open a popup, cannot submit a form (Playwright) |
| `DET-PL03-CACHE` | same spec → same id, second build zero model calls; doctrine hash change → new id |
| `DET-PL03-FALLBACK` | forced build failure → the turn payload has a fallback and the UI renders it |

Full card, goldens, and log paths: [`evals.md`](evals.md) §4.

---

## 11. Open items

- Dedicated artifact origin (`D-PL-09`) — deployment decision.
- Artifact per-turn cap and daily numbers (`D-PL-03`).
- Whether a diagram-only artifact (static SVG) should be a cheaper path that
  skips the headless render gate (recommended: no — it still runs lint, and the
  render gate is cheap for a static SVG).
- Whether the artifact builder should reuse the **factory model** (same
  DeepSeek route) or a cheaper image/JS-specialised model (no: one route, one
  secret, recorded in `D-PL-06`).
