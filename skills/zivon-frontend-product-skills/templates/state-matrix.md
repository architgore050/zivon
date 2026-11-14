# State matrix: `<screen>`

Copy this template into the screen spec or the PR. Rows are screens, regions,
or element families; columns are the eleven states. Every cell names **what the
student perceives** and, where useful, the code path (`[static]`, `[ssr]`,
`[island]`, `[kit]`). A blank cell is a defect; `n/a (reason)` is valid.

## Legend

- `[static]` — plain HTML from nginx or the publish flow.
- `[ssr]` — server-rendered template from the Python service.
- `[island]` — a small vanilla-JS enhancement on top of rendered HTML.
- `[kit]` — `frontend/assets/zivon.js` / `zivon.css` behaviour.
- `[page]` — generated `page.js` in a factory lesson.
- `[shell]` — the hand-maintained shell (`index.html`, `404.html`, etc.).

## Matrix

| Row | default | loading | empty | partial | error | offline | permission-denied | reduced-motion | untranslated | quota-exhausted | consent-missing |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `<screen / region>` | | | | | | | | | | | |
| `<region R1>` | | | | | | | | | | | |
| `<region R2>` | | | | | | | | | | | |
| `<component family>` | | | | | | | | | | | |

## Cross-cutting rows

| Concern | default | loading | empty | partial | error | offline | permission-denied | reduced-motion | untranslated | quota-exhausted | consent-missing |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Fonts | | | | | | | | | | | |
| JS failure | | | | | | | | | | | |
| Auth/session | | | | | | | | | | | |
| Deletion | | | | | | | | | | | |

## Completeness check

- [ ] Every screen in scope has a row.
- [ ] Every region of the screen has a row or is covered by a parent row.
- [ ] All 11 columns are present.
- [ ] Every `n/a` has a reason.
- [ ] Every cell names a visible outcome, not “handled”.
- [ ] The failure states (error, offline, permission, quota, consent) were
      designed before the happy path.
- [ ] Each state names the code path that renders it.
- [ ] The matrix is linked from the screen spec and the PR body.

## Worked cell examples

| Cell | Good | Bad |
|---|---|---|
| empty | “No doubts yet — ask one from a lesson” + link | “No data” |
| error | “Could not load your SWOT — retry” + button | “Error 500” |
| offline | “Offline — reading works; the tutor needs a connection” | A spinner forever |
| permission | “Mic is off — type your doubt instead” + focused input | A red toast |
| quota | “Voice is resting (daily limit) — type your doubt” | Hiding the tutor entirely |
| consent | Consent sheet; decline leaves reading intact | A mic button that opens the permission prompt |
| reduced motion | Sim draws once; caption instant | A looping animation |
| untranslated | English + “not available in this language yet” | A silent English block |
