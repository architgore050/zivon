# Visual verdict: `<surface>`

The founder decision record for a frontend example. One file per surface or
per verdict round. It is the evidence that the design was explored first and
that the same agent implemented the approved version.

## 1. Context

| Field | Value |
|---|---|
| Surface / screen | `<...>` |
| Route | `<...>` |
| Delivery class | `<static / generated lesson / SSR app / auth / admin>` |
| Workstream | `<F1…F10>` |
| Agent / session | `<session id or name>` |
| Branch / worktree | `<branch>` |
| Date | `<YYYY-MM-DD>` |
| Doctrine section | `<§... / new section>` |

## 2. Example

| Field | Value |
|---|---|
| Example path | `<tmp/... or folder>` |
| Local URL | `http://127.0.0.1:<8101–8115>/` |
| Port owner | `<F1…F10>` |
| Mock data | `<synthetic only>` |
| States demonstrated | `<default, empty, error, loading, offline, 360 px, ...>` |
| Viewports checked | `<360 / 768 / 1280>` |
| Screenshots | `<paths or links>` |
| Known gaps | `<mocked or deferred>` |

## 3. Review note

What the founder is asked to decide (3–5 concrete questions):

1. `<...>`
2. `<...>`
3. `<...>`

## 4. Verdict

- [ ] **Approve** — build it as shown
- [ ] **Approve with changes** — direction accepted; changes required
- [ ] **Reject / redirect** — rebuild the example
- [ ] **Defer** — not now

Founder's words (short quote or summary):

```text
<verdict>
```

Required changes:

1. `<...>`
2. `<...>`
3. `<...>`

## 5. Doctrine decision

- [ ] No doctrine change needed (existing §... covers it)
- [ ] New product-surfaces section approved
- [ ] Existing section updated (DCR: `<id/date>`)
- [ ] Blocked: doctrine section missing; founder must author it

Section / DCR:

## 6. Implementation

- [ ] Verdict returned to the same agent session
- [ ] Changes applied
- [ ] Kit component added before use
- [ ] Screen spec updated
- [ ] State matrix updated
- [ ] Tests added
- [ ] A11y/perf evidence attached
- [ ] Docs updated
- [ ] PR opened

Notes on what changed from the example:

## 7. Waiver (only if a PR precedes the verdict)

A product PR before the verdict requires an explicit founder waiver. Record it
here; do not self-grant it.

- Waiver date:
- Waiver channel:
- Scope:

## 8. Follow-up

| Item | Owner | Status |
|---|---|---|
| `<...>` | `<...>` | `<open / done>` |
