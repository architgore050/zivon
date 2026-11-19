# PL3 artifact goldens — `EV-PL-003`

Recorded 2026-11-18 by the W5.5 PL3 agent. Hermetic (no network, no keys, no
student text); the "student" strings below are synthetic.

## Golden good artifact

- `good-concave-mirror.html` — the reference artifact: one inline `<script>`
  and one inline `<style>`, the §4 meta CSP byte-exact, one `<h1>`, labelled
  range control, `role="img"` + `aria-label` canvas, `aria-live` text mirror,
  `prefers-reduced-motion` branch with a visible Play control, harness
  `ready`/`state`/`fps` postMessage only.
  - **Lint:** passes `backend/personalized/artifacts.py::lint_artifact_html`
    with zero hits.
  - **Render gate** (`DET-PL03-RENDER`, Playwright): zero console errors, zero
    network attempts, no navigation, no 360 px overflow, `ready` ≤ 5 s,
    median fps ≈ 60 (floor 24), no long task > 200 ms, reduced-motion context
    renders the static frame.

## Seeded defects (`DET-PL03-LINT`)

Each is minimal and violates exactly one lint class; the expected rule id is
the assertion:

| File | Defect | Expected rule |
|---|---|---|
| `external-fetch.html` | `fetch('https://…')` exfiltration attempt | `LINT_NETWORK_FETCH` |
| `eval.html` | `eval(...)` dynamic code evaluation | `LINT_EVAL` |
| `localstorage.html` | `localStorage.setItem` from the opaque origin | `LINT_STORAGE` |
| `form.html` | a `<form action="https://…">` | `LINT_FORM` |
| `topnav-link.html` | an `<a href="https://…">` anchor | `LINT_ANCHOR` |
| `oversized.html` | 148 KB padded document | `LINT_SIZE` |
| `missing-label.html` | range input without a `<label for>` | `LINT_LABEL_MISSING` |

## Specs (`DET-PL03-SPEC` via the card's spec-validation checker)

| File | Expected outcome |
|---|---|
| `valid-simulation.json` | validates against the available claim set `{c-01…c-08}`; content id stable |
| `valid-diagram.json` | validates; zero controls |
| `too-many-controls.json` | rejected (4 controls > cap 3) |
| `unknown-claim-ids.json` | `c-99`/`c-42` dropped against `{c-01…c-08}`; zero remaining ⇒ `weak_grounding=True`, build proceeds |

The claim universe for the spec checks is the fixed set `c-01…c-08`
(`DET-PL03-SPEC` builds it in the checker; no RAG fixture needed).
