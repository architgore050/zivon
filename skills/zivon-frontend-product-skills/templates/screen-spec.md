# Screen spec: `<screen name>`

Copy this file into the PR or the workstream folder and fill it before writing
markup. A screen spec is the contract between the designer/founder verdict, the
template, the API, and the tests.

## 1. Identity

| Field | Value |
|---|---|
| Screen ID / name | `<SCR-... / name>` |
| Route | `<path>` |
| Surface | `<static / generated lesson / SSR app / auth / admin>` |
| Auth | `<none / guest allowed / student session / staff session>` |
| Indexable | `<yes + canonical / noindex>` |
| Owner workstream | `<F1…F10>` |
| Feature IDs | `<F-... / SWOT-...>` |
| Element IDs | `<EL-... or "assigned by inventory">` |
| Information IDs | `<INF-...>` |
| Backend needs | `<NEED-... / endpoint>` |
| Events | `<EVT-...>` |
| Doctrine section | `<§1–§9 / §10 / new section>` |
| Status | `<example / verdict / implement / review / done>` |

## 2. Purpose

One sentence: what job does the student hire this screen to do?

- Primary user:
- Primary job:
- Success signal (one metric):
- What this screen must **not** become:

## 3. Regions

| Region | Name | Contents | Notes |
|---|---|---|---|
| R1 | `<app bar / header>` | `<...>` | `<sticky? / skip link?>` |
| R2 | `<page header>` | `<...>` | |
| R3 | `<main>` | `<...>` | |
| R4 | `<aside / drawer>` | `<...>` | |
| R5 | `<footer>` | `<...>` | |

Layout order on mobile:

## 4. Components

| Component | Kit or new | File | States | Notes |
|---|---|---|---|---|
| `<zn-...>` | `<kit / new>` | `<zivon.css / template>` | `<...>` | |

Every new component links its completed
[component checklist](component-checklist.md).

## 5. Data

| Displayed item | Source (INF / API) | Format | Empty / null behaviour |
|---|---|---|---|
| `<...>` | `<INF-... / GET ...>` | `<text / number / date / enum>` | `<...>` |

Rules:

- No orphan datum: every displayed value has a source and a fallback.
- No PII beyond what the feature card allows.
- No free text from a child in telemetry.
- Units, symbols, and equations are never translated.

## 6. API and WebSocket

| Call | Method / path | When | Failure UI |
|---|---|---|---|
| `<...>` | `<GET /v1/...>` | `<load / submit>` | `<inline error / retry / offline>` |

Auth: cookie / CSRF / consent gate.
Idempotency: `<key / none>`.
Cache: `<no-store / private / 300 s>`.

## 7. Events

| Event | Trigger | Properties | Privacy class |
|---|---|---|---|
| `<...>` | `<...>` | `<ids, no free text>` | `<none / pseudonymous>` |

No event carries a name, email, transcript, or raw audio.

## 8. States

Fill every cell. `n/a` needs a reason.

| State | What the student sees | Code path | Owner |
|---|---|---|---|
| default | | | |
| loading | | | |
| empty | | | |
| partial | | | |
| error | | | |
| offline | | | |
| permission-denied | | | |
| reduced-motion | | | |
| untranslated | | | |
| quota-exhausted | | | |
| consent-missing | | | |

## 9. Accessibility

- Landmarks / headings:
- Keyboard path:
- Focus order and focus return:
- 44 px targets:
- Screen-reader names/roles/states:
- `aria-live` regions:
- Colour/shape check:
- Reduced-motion behaviour:
- Zoom/reflow check:

## 10. Performance

- Rendering: `<static / SSR / island>`
- JS budget: `<≤ 60 KB lesson / ≤ 120 KB app island>`
- Fonts: `<local, preload faces>`
- Images/SVG: `<local, lazy below fold>`
- Weak-Android check: `<profile + result>`
- No layout thrash:
- No external request:

## 11. SEO and metadata

- Title:
- Description:
- Canonical:
- OG/Twitter:
- JSON-LD:
- Robots: `<index / noindex>`
- Sitemap: `<yes / no>`
- hreflang: `<gated / n/a>`

## 12. i18n

- Locales: `<en / hi / hi-Latn>`
- Copy keys:
- Number/date format:
- Never-translate values:
- Missing-variant behaviour: English + visible marker
- `lang` attributes:

## 13. Privacy and security

- Data classes read:
- Consent gate:
- Deletion/export path:
- No raw audio:
- No third-party host:
- CSP:
- Cookies:

## 14. Visual example

- Example path:
- Port:
- States demonstrated:
- Review note:
- Verdict record: [visual-verdict.md](visual-verdict.md)
- Required changes applied:

## 15. Tests

| Test | File | What it asserts |
|---|---|---|
| `<...>` | `<testing/frontend/...>` | `<...>` |

## 16. Open decisions

| Question | Owner | Blocks |
|---|---|---|
| `<...>` | `<founder / backend / content>` | `<...>` |

## 17. Definition of done

- [ ] The route exists and returns the right status/headers.
- [ ] Every region and state is implemented.
- [ ] The component checklist is complete.
- [ ] Keyboard, screen reader, 44 px, reduced motion pass.
- [ ] Perf budget passes on `weak-android`.
- [ ] SEO/noindex is correct.
- [ ] i18n has no silent English.
- [ ] Tests are deterministic, key-free, offline.
- [ ] The visual verdict is recorded and applied.
- [ ] The docs that describe the screen are updated.
