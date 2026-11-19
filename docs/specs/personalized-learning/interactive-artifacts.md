# Interactive artifacts — generation, sandbox, review, cache

Status: **PL3 implemented (2026-11-18); PL2 wires the decide call.** Owner
workstream: PL3 ([`workstreams.md`](workstreams.md)). Product view:
[`spec.md`](spec.md) §4. The turn that requests an artifact is specified in
[`agent-and-rag.md`](agent-and-rag.md) §4.4. The implementation notes in §12
map every section of this document to the code that landed.

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

One artifact per teaching slice, but no more than **one per 4 teaching turns**, at most
**4 per session** and **12 per user per day** (`D-PL-03`). The agent may ask; the server
may refuse (budget, quota, "text is enough") and the turn continues.

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
     `url(http…)`); **one deliberate relaxation:** the artifact document may carry
     one inline `<script>` block (it is self-contained; `lint_html`'s no-inline rule
     is for lesson pages), while inline `on*=` handlers are rejected (use
     `addEventListener`). Do **not** apply `lint_page_css_scope` — that contract is
     for a lesson's `page.css`, not an artifact document;
   - artifact-specific: no `<form>`, no `localStorage`/`sessionStorage`/
     `indexedDB`/`document.cookie`, no `window.top`/`window.parent` navigation,
     **no self-navigation** (`location`, `location.href`/`assign`/`replace`,
     `window.open`, `history` push beyond the initial entry,
     `<meta http-equiv="refresh">`, `<base href>`), no `<iframe>`/`<object>`/`<embed>`,
     no `data:` URL except `img`/font, no `javascript:` URL, no clipboard APIs, no
     `Notification`, no fullscreen.
     The **only** allowed `postMessage` is the harness channel:
     `window.parent.postMessage(msg, '*')` — the parent is cross-origin and cannot
     be named; any other `postMessage` call is rejected.
4. **Headless render gate** (build-time, Playwright, key-free):
   - load the artifact document with **all network requests aborted**; any
     attempted request is a failure;
   - capture console errors/warnings and unhandled rejections — any error fails;
   - assert the document never navigates: the committed URL after 3 s equals the
     requested URL and no additional document load occurred (sandbox permits a frame to
     navigate *itself*; CSP does not stop that, so this is the check that does);
   - assert `scrollWidth <= clientWidth + 2` at 360 px;
   - run 3 s, collect a frame-time sample via the harness (`postMessage`), fail
     if median < 24 fps or any long task > 200 ms, measured under the 4× CPU
     throttle the §4 performance budget names;
   - assert the artifact posts `ready` within 5 s;
   - assert a `prefers-reduced-motion: reduce` context renders a static frame.
5. **Store** — content-addressed (`artifact_id =
   sha256(canonical_json(spec minus why) + prompt_version + doctrine_hash +
   schema_version + lint_version)[:32]`), status `ready`.
   The spec's `why` is a short misconception label (never the student's words)
   and is **excluded from the hash**: two students with the same visual need share
   one build; the label is not rendered into the document.
6. **Failure** — status `failed` + a machine reason (`lint`, `render`,
   `timeout`, `budget`); the turn shows the fallback; one retry is allowed only
   for a transient route error, never for a lint failure.

The build is **asynchronous** relative to the teaching stream: the turn emits
`turn.artifact {status: pending}` immediately and the client polls the status
endpoint `GET /v1/personalized/artifacts/{id}/status` (API-PL-14; a `ready`
response carries the server-issued `src`), or receives `turn.artifact.ready`
on the same SSE if it finishes within the stream window.

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
| `Cache-Control` | `private, max-age=86400, immutable` (same-origin) / `private, max-age=600` (signed-URL mode, matching the token TTL) |
| `X-Robots-Tag` | `noindex, nofollow` |
| `Cross-Origin-Resource-Policy` | `same-origin` |

The CSP is enforced twice: the response header and the in-document `<meta>`
(defense in depth). `sandbox` in the CSP header also protects a top-level
navigation to the URL (if a student pastes it): the document is sandboxed even
outside the iframe.

Two per-environment notes:

- **`Cross-Origin-Resource-Policy` is `same-origin` only in same-origin mode.** In
  dedicated-origin mode the app origin is the embedder, so the artifact response sends
  `cross-origin` (or omits the header) and `frame-ancestors` stays the embedding control.
  Copying `same-origin` into dedicated-origin mode would block the frame in browsers that
  apply CORP to framed navigations.
- **`immutable` is honest for content-addressed ids and an obstacle for an emergency
  purge.** A purged artifact can survive in a student's browser cache for up to 24 h.
  Incident response therefore pairs an operator purge with a `lint_version`/`schema_version`
  bump (new `artifact_id`, new URL) and, for the 60-minute window, a
  `Cache-Control: no-store` override on the affected route (`security-privacy.md` §8,
  incident row).

### 5.3 Origin strategy

| Environment | Artifact origin | Why |
|---|---|---|
| Local / compose | same origin, `/v1/personalized/artifacts/{id}` | simplest; the iframe sandbox still gives an opaque origin |
| Production (recommended) | dedicated origin `artifacts.<domain>` (same backend, separate hostname; `frame-ancestors` restricted to the app origin) | a same-origin compromise (a future XSS in the shell) cannot read artifact storage or vice versa; the host-only session cookie is not sent to the artifact host |

The dedicated origin is a deployment decision (D-PL-09). Until it lands, the
same-origin route + opaque-origin sandbox is the accepted posture; it is
recorded, not silent.

Embedding consequence: `/app`'s CSP has no `frame-src`, so `default-src 'self'` decides.
Same-origin mode is allowed unchanged; dedicated-origin mode needs exactly one
`frame-src https://artifacts.<domain>` allow-list entry on `/app` (an addition, not a
relaxation of `script-src`/`connect-src`).

**Auth on a dedicated origin.** A host-only session cookie is not sent to
`artifacts.<domain>`, so the artifact route must not depend on it there. The
session/detail serializer (or `turn.artifact.ready`) returns `src` as either the
same-origin route (cookie mode) or a **signed URL**
`/v1/personalized/artifacts/{id}?token=<HMAC-SHA256(artifact_id|user_id|exp)>&exp=<unix>`
with a 10-minute TTL, issued only after the caller's session reference check and
verified in constant time. The token grants read of exactly one artifact and is
not a session credential; it is never logged (the route logs the artifact id
only, never the query string) and is not placed in a `Referer` (the iframe is
`no-referrer`).

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
- **Self-navigation is contained, not assumed away.** A sandboxed frame may still navigate
  itself (`location.href = …`, `meta refresh`); the new document keeps the opaque origin, so
  cookies/storage stay out of reach, but attacker content could replace the artifact inside
  the trusted card (phishing copy). Three controls: the lint rejects every self-navigation
  API and `meta refresh`; the render gate asserts the document never navigates; the host
  treats a second `load` event, or a second `ready` from the same frame, as a
  crash — it unloads the iframe and shows the fallback. A message whose
  `event.source` is not the frame's own window is ignored, never acted on (a
  multi-viewer page cannot let one card's message crash another).

---

## 6. Review pipeline (build-time) and runtime monitoring

| Gate | When | Blocks | Evidence |
|---|---|---|---|
| Spec validation | before build | malformed/oversized/ungrounded spec | `personalized_usage` row `outcome=rejected` |
| Lint | in the build retry + final | any hit | `lint_hits` count + rule ids (no HTML) |
| Headless render | after lint | console error, network attempt, overflow, fps floor, no `ready` | render report (counts, timings) |
| Deterministic eval | CI (`EV-PL-003`) | seeded unsafe artifacts and a golden good artifact | `runs/evals/<date>/…/EV-PL-003.json` |
| Student report | runtime | does not block; feeds the inbox | `problem_report` row (`category='broken_sim'`, the existing CHECK value — no migration) |
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

- **Key:** `artifact_id = sha256(canonical_json(spec minus why) + "|" +
  prompt_version + "|" + doctrine_hash + "|" + schema_version + "|" +
  lint_version)[:32]`.
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
  `lint_version`, `model`, `created_at` are stored per row; the viewer shows a
  provenance line, not a version number.
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
| `DET-PL03-RENDER` | headless: zero console errors, zero network requests, no 360 px overflow, no navigation (committed URL unchanged), `ready` ≤ 5 s, fps floor under 4× throttle |
| `DET-PL03-SANDBOX` | a red-team artifact cannot read parent DOM/cookies/localStorage, cannot navigate top, cannot open a popup, cannot submit a form, **cannot navigate itself to a foreign document** (Playwright) |
| `DET-PL03-CACHE` | same spec → same id, second build zero model calls; doctrine hash change → new id |
| `DET-PL03-NO-STUDENT` | the builder prompt, the stored spec, and the document contain none of the session's free text (a canary string in the weakness/instructions never appears) — the cache is shared across students, so this is the cross-student-leak test |
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

---

## 12. Implementation notes (PL3, 2026-11-18)

This section records what landed, file by file, and the two deliberate
interpretations taken where this document left a choice open. The spec text
above stays the contract; nothing below relaxes it.

| Section | Landed as |
|---|---|
| §2 request contract | `backend/personalized/artifacts.py::validate_artifact_spec` — allow-listed fields only (an unexpected field is a rejection, which is what makes "no student text" structural, T-PL-17), caps enforced as rejections (over-length `title`/`learning_goal`/`why` are errors, never truncations), unknown claim ids dropped → `weak_grounding`. |
| §2 no-student-text | `ensure_no_student_text` hard-rejects a spec quoting the session's weakness/instructions (the canary test `DET-PL03-NO-STUDENT` runs it through prompt, spec, and document). |
| §3 generation pipeline | `ensure_artifact` in `artifacts.py` (validate → hash → cache → quota → build → lint → store) + `artifact_prompt.py::LLMManagerArtifactBuilder` (one D-PL-07 route call at `reasoning_effort=medium`, 120 s deadline per the D-PL-06 recommendation, lint-in-retry via `llm_manager.run_validation_rounds`, ≤ 2 rebuilds). The engine re-lints the final document as a backstop (the 05-interactive pattern) — whatever produced the HTML, the row never marks `ready` past a failing lint. |
| §3 hard lint | `lint_artifact_html` in `artifacts.py`: `factory/lint.py` rules reused as the base, artifact-specific rules added as a thin wrapper with stable rule ids (`LINT_*`); the one deliberate relaxation (one inline `<script>` block) and the a11y rules (label/for, canvas `role="img"` + `aria-label`, exactly one `<h1>`) are both enforced here. |
| §3 step 4 render gate | `backend/personalized/artifact_sandbox.py::run_render_gate` — route-fulfilled load with all other requests aborted, console/network/navigation/overflow/`ready`/fps/long-task/reduced-motion assertions, timings-and-counts-only report. Dev/test dependency: without Chromium the gate raises `RenderGateUnavailable` and the build ships on lint alone (`render_ms = NULL`, recorded — not silent). |
| §5 sandbox | API-PL-13 in `backend/personalized/artifact_router.py` serves the §5.2 header set byte-exact (CSP `sandbox allow-scripts` + `frame-ancestors 'self'`, `nosniff`, `no-referrer`, `private, max-age=86400, immutable`, `noindex`, CORP `same-origin`). Host side: `frontend/assets/personalized-artifact.js` creates the iframe (`sandbox="allow-scripts"`, `allow=""`, `no-referrer`, lazy), validates the harness channel by `event.source` + schema, and unloads on watchdog/second-load. Template: `web/templates/app/partials/artifact_viewer.html`. |
| §6 review pipeline | Lint + render gate as above; `EV-PL-003` (`evals/cards/EV-PL-003.yaml` + `evals/checkers/personalized_checks.py`) pins lint, doc contract, spec validation, cache identity, no-student-text, fallback, render gate, and the sandbox red-team test (`evals/goldens/personalized/artifacts/` — 1 golden, 7 seeded defects, 4 specs, red-team probe). |
| §7 cache/versioning | `compute_artifact_id` (the §7 key formula, `why` excluded); `ArtifactStore` (pending/ready/failed transitions, `touch_last_used`, the reference check, `purge` that marks referencing messages `artifact_missing`); the nightly refcount/failed TTL jobs were PL1's (`backend/personalized/retention.py`) and are unchanged. |
| §8 fallback | `normalize_fallback` stores the decide payload's diagram only when the SVG is provably safe — the factory's diagram-svg rule (`factory/checks.py::rule_diagram_svg`) plus the wrapper's script-scheme check (`javascript:`/`vbscript:`/`data:text/html`, because the fallback is injected raw into the app-origin page) — and downgrades to text otherwise; every rejection path (`ArtifactSpecError`/`ArtifactQuotaError`/`ArtifactBuildError`) carries the fallback in `extra` so the turn continues. |

Interpretations recorded (not spec changes):

1. **A `failed` row is rebuilt only for `failure_reason = 'route'`.** §3 step 6
   allows one retry for a transient route error and none for lint/render; a new
   request for an identical spec after a lint/render failure returns the failed
   handle directly (the failure is deterministic and rebuilding would burn
   quota). The row's own TTL (7 days) is the recovery path.
2. **The render gate is not on the student request path and not wired into the
   backend image.** It runs wherever Chromium exists (CI, the eval suite, a
   build job) via the injectable `render_gate` argument; a build without it
   ships on lint alone with `render_ms = NULL` (workstreams.md §4 risk note).
3. **Quota accounting:** the reservation is committed when the build pipeline
   attempted a model call (lint/render/timeout failures consume it) and
   released on a transient route error so the allowed retry re-reserves.
   Spec/quota/budget rejections write no artifact row (usage rows record
   `rejected`/`quota_blocked` per §2.5).
