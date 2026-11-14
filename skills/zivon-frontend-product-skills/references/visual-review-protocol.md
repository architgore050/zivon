# Visual review protocol

The founder's rule: **build a runnable example first, serve it on your assigned
localhost port, and wait for the verdict before implementing.** The verdict
returns to the **same agent session**; that agent implements it, drafts the
doctrine extension, tests, and opens the PR.

This is not a design review by committee. It is a fast visual check on a real
page, with real type and real states, before product code spreads the mistake.

Source: `tmp/full-frontend/FEATURE-MAP.md` (locked decision 11: visual
exploration first; 12: doctrine after verdict) and `REQUIREMENTS.md` §5.4 and
§16.3. The ports are in the handshake §2.6.

## 1. Before you build the example

- [ ] Read the doctrine, the frozen map, and the screen's requirements section.
- [ ] Check the doctrine guard for the voice dock (§10.12). If it is absent,
      stop; do not build the dock.
- [ ] Claim a port (table below) and note it in the PR/issue.
- [ ] Confirm the surface: static, generated lesson, SSR app, auth, or admin.
- [ ] List the states the verdict must see: default, empty, error, loading,
      offline, 360 px, and the surface-specific one (quota, consent,
      permission, untranslated).
- [ ] Gather mock data that looks real (chapter names, marks, dates), never
      real student data.

## 2. Ports

| Port | Owner |
|---|---|
| 8081 | compose `web` (nginx serving `./frontend`) |
| 8082 | compose `dashboard` |
| 18080 | dev inference router |
| 18085 | core backend (compose) |
| 18090 | llm-manager node (compose) |
| 30080 | cluster NodePort (frontend) |
| **8101** | F1 public + catalogue |
| **8102** | F2 identity + settings |
| **8103** | F3 dashboard + progress |
| **8104** | F4 lesson shell |
| **8105** | F5 practice |
| **8106** | F6 speaking |
| **8107** | F7 tests + series |
| **8108** | F8 SWOT |
| **8109** | F10 admin |
| **8110** | P1 generated-page preview |
| **8111** | P4 gate/evidence preview |
| 8112–8115 | reserved; claim by note |

Do not squat another workstream's port. If a port is busy, find the process and
stop it; do not silently move to a random port the founder cannot find.

## 3. Build the example

Requirements:

- A standalone HTML/CSS/JS page or a small folder. It must run with
  `python3 -m http.server` and no backend, no secrets, no network.
- Real local fonts from `frontend/assets/fonts/`; no Google Fonts, no CDN.
- Mock data that exercises the layout: longest chapter title, largest number,
  missing value, empty list, error copy.
- The important states reachable by a query string, a button, or separate
  files: default, empty, error, loading, offline, 360 px.
- Real keyboard behaviour and focus rings, not a static picture.
- Reduced-motion variant (or a note that the surface has no motion).
- A short review note: what to look at, what is decided, what is still open.

Do not copy a defect from a live generated page just because it is live. Match
the best page, the doctrine, and the tests.

## 4. Serve it

```bash
# from the example directory
python3 -m http.server 8101 --bind 127.0.0.1
```

Return the exact URL, e.g. `http://127.0.0.1:8101/`, plus:

- the states and how to reach them (`?state=empty`, `?state=error`);
- the viewport sizes you checked;
- the 3–5 decisions you want the founder to make (not a general “thoughts?”);
- a screenshot or two if the founder is remote from the machine.

The example is throwaway. Do not commit it unless the workstream explicitly
wants a checked-in reference; the product implementation is the deliverable.

## 5. Wait for the verdict

The founder reviews the URL and returns one of:

| Verdict | Meaning | Next |
|---|---|---|
| **Approve** | Build it as shown | Implement; the doctrine section may be drafted |
| **Approve with changes** | Direction accepted; listed changes required | Apply every change; record it; then implement |
| **Reject / redirect** | Wrong shape; rebuild the example | Do not implement; revise and re-review |
| **Defer** | Not now | Stop; record why; no product code |

Record the verdict in [templates/visual-verdict.md](../templates/visual-verdict.md).
Include date, surface, port, example path, verdict, exact required changes, and
the doctrine decision.

**No product PR before the verdict** unless the founder waives it in writing
(email, chat, or PR comment). A waiver is recorded in the verdict file.

## 6. Return to the same agent session

The verdict is implemented by the **same agent session** that built the
example. That is how the context — what was mocked, what was deliberately
deferred, what the founder pointed at — survives into the code.

If the session cannot continue:

- hand the verdict file, the example folder, the branch, and screenshots to the
  successor;
- state what is decided and what is still open;
- do not let a new agent reinterpret the design from memory.

## 7. Doctrine after the verdict

The implementing agent may draft or update the **product-surfaces** doctrine
section once the verdict finalises the design. Rules:

- Add a new section; do not rewrite §10.12–§10.14 without explicit founder
  authorisation.
- Keep §0's scope split true: name the surfaces the section applies to.
- Record a DCR (date, verdict, what changed).
- Update `docs/frontend/design-doctrine.md` in the same PR as the code.
- If the code and the doctrine disagree, the doctrine wins; fix the code.
- Do not write a doctrine section for an unapproved design.

## 8. Implement, test, PR

After the verdict:

1. Apply the verdict changes.
2. Implement in the owned files only; add the kit component before using it.
3. Fill the screen spec and state matrix.
4. Run tests, a11y, perf, and no-network checks.
5. Update the docs that describe the surface.
6. Open the PR; a review agent merges.

## 9. Failure handling

| Situation | Do this |
|---|---|
| Founder is unavailable | Keep the example; do not guess; the task is blocked, not “close enough” |
| The verdict conflicts with the doctrine | Raise the conflict; the founder decides; record it |
| The verdict requires a new component | Add it to the kit first; re-review if the component is a new pattern |
| The example works only with a backend | Simplify to fixtures; the example must run standalone |
| The port is occupied | Find and stop the other process; do not move silently |
| The design needs a doctrine change | Write the DCR after approval; do not smuggle it into code |

## 10. Review note template

```text
Surface: <screen> (<route>)
Port: <8101–8115>
States: default, empty, error, loading, offline, 360 px, <surface-specific>
Decisions requested:
1. <question>
2. <question>
Known gaps: <what is mocked or deferred>
Doctrine: §<section> or "new section needed"
```
