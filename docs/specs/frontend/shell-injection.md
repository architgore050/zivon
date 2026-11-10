# Shell injection contract — product chrome on content-only pages

**Status:** binding for the EX5B-FRONT wave (2026-11-10). Companion to
[`spec.md`](spec.md), [`component-inventory.csv`](component-inventory.csv), and
`docs/frontend/design-doctrine.md` §10.12–§10.14.

## 1. The problem this solves

The content factory emits **content-only** lesson HTML: header, text/diagram/simulation/check
blocks, sources footer. It does **not** emit consent sheets, the voice dock, read-aloud
controls, report forms, or credit notices. Those are product chrome owned by the shell. If the
factory had to emit them, every generated page would drift and every doctrine change would
require a pipeline re-run.

**Rule: the factory emits content + hooks; the shell kit injects chrome at runtime.**
One implementation (`frontend/assets/zivon.js`) runs on every lesson page, including pages the
factory will generate after this wave.

## 2. What the factory must guarantee (and nothing more)

`factory/render.py` already guarantees (1)–(3); (4)–(5) are optional data hooks:

1. `<link rel="stylesheet" href="…/assets/zivon.css">` and
   `<script src="…/assets/zivon.js"></script>` on every lesson page.
2. Stable block ids: `id="b-NN"` on **every** block element (guaranteed by a
   factory unit test; the non-i18n text path used to omit it, which silently
   cost those blocks their read-aloud control and their context anchor).
3. `data-block-type`, `data-element-id` where the component inventory requires them.
4. `manifest.json` in the topic directory. Narration availability is the
   `narration.blocks{block_id: {available, path, duration_ms}}` map written by
   `factory/narration/publish.py`; translated strings are the `i18n.js`
   `window.ZIVON_I18N` bundle (`factory/render.py` already emits it when a locale exists).
5. The lesson `<meta>` CSP keeps `connect-src 'self'` (already true) so the kit can fetch
   `manifest.json` and open `wss://<origin>/voice/ws`.

The factory must **not** emit dock markup, consent markup, read-aloud buttons, or report
forms. No per-page copies of chrome.

## 3. Injection sequence (one mount, idempotent)

`zivon.js` runs `ZivonShell.mount()` from the existing `DOMContentLoaded` handler, after
`LessonKit.init()`:

| # | Surface | Depends on | If data is absent |
|---|---|---|---|
| 1 | Global notices: offline, voice-limited, typed-only | `session.ready.credit_state`, `agent.state`, `navigator.onLine` | show offline only when actually offline |
| 2 | Read-aloud controls (§10.13) | `manifest.json` → `narration.blocks` | render **no** buttons |
| 3 | Report-a-problem button/panel | block ids; `POST /v1/reports` | button hidden if the endpoint is unreachable; reading unaffected |
| 4 | Consent gate (§10.14) | `localStorage[zivon.consent]` | if absent, gate before the dock; reading unaffected |
| 5 | Voice dock (§10.12) | `ZivonVoiceDock.lazyMount()`; `doctrineReady` | if doctrine text is missing, stay hidden (existing gate) |
| 6 | Privacy link + locale controls | footer; `window.ZIVON_I18N` | link always present; disabled chips if no bundle |

Rules:

- **Idempotent:** guard with `data-zn-mounted` on each injected root; a second call is a no-op.
- **Content-first:** every surface is additive. With JS off, or if any step throws, the lesson
  remains fully readable and the simulation/check kit keeps working. No surface may be required
  to read the page.
- **Ordering matters for consent:** the dock is not created until consent is accepted; the
  read-aloud control is allowed before consent (it sends no audio, only fetches static assets).
- **One conversation:** the dock and the page share `buildContextSnapshot()` / `highlightBlocks()`;
  the anchor chip and the pen-blue block ring are the same state.
- **Same-origin only:** `fetch("./manifest.json")`, `POST /v1/reports`,
  `POST /api/v1/events`, `wss://<origin>/voice/ws`. No external hosts; CSP unchanged.
- **Storage:** only `zivon.dock`, `zivon.consent`, `zivon_locale`, `zivon.captions`,
  `zivon.device_pseudo_id` (ADR-0007). No behavioural profile, no progress store.

## 4. Why this keeps working for future factory runs

The contract is keyed to stable, already-emitted hooks (block ids, assets, manifest), so a
page generated a month from now gets the chrome without a pipeline change. The only factory
obligation is to keep the hooks stable; `factory/render.py` has a test that a content-only
fixture still includes the kit assets and block ids.

If a future factory run adds a new block type, the shell needs a renderer only if the block
gets a chrome affordance; the default is no chrome.

## 5. Tests (owned by `testing/frontend/`)

1. **Content-only fixture:** a minimal lesson page with only block markup + assets + a
   narration manifest → all five surfaces mount once; no double-mount on re-entry.
2. **No manifest:** no read-aloud buttons; everything else still mounts.
3. **Consent declined:** dock never mounts; read-aloud/report remain; no re-nag after reload.
4. **JS error injection:** a thrown injection step leaves the lesson readable (progressive
   enhancement assertion).
5. **CSP:** no `connect-src` violation; no external URLs in generated DOM.
6. **Doctrine gate:** if `doctrineReady` is false, dock stays hidden and no dock DOM is built.

## 6. File boundaries

- Shell: `frontend/assets/zivon.js`, `frontend/assets/zivon.css`, `frontend/index.html`.
- Tests: `testing/frontend/`.
- Factory: only if a hook is missing (`factory/render.py` + its unit test).
- Doctrine: `docs/frontend/design-doctrine.md` (§10.12–§10.14) — **not** written by build agents.
