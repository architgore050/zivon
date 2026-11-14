# Component checklist: `<component>`

One checklist per new or changed component. Copy it into the PR or attach it to
the screen spec.

## 1. Identity

| Field | Value |
|---|---|
| Component | `<zn-...>` |
| Family | `<navigation / input / card / progress / dialog / media / state / exam / voice / table>` |
| Kit or new | `<existing kit / new kit component / SSR partial>` |
| Files | `<zivon.css catalog line; zivon.js function; template partial>` |
| Used by | `<screens>` |
| Visual verdict | `<link / date>` |

## 2. Markup contract

```html
<!-- exact markup the renderer/template emits -->
```

Stable classes, roles, and data attributes:

- `<...>`

## 3. Variants

| Variant | When | Notes |
|---|---|---|
| primary | | |
| secondary | | |
| quiet | | |
| danger | | |
| selected / current | | |
| compact | | |

## 4. States

| State | Designed? | How it looks / reads | Test |
|---|---|---|---|
| default | | | |
| hover | | | |
| focus | | | |
| active | | | |
| disabled | | | |
| loading | | | |
| error | | | |
| empty | | | |
| partial | | | |
| offline | | | |
| permission | | | |
| reduced motion | | | |
| untranslated | | | |
| quota | | | |
| consent | | | |

Mark `n/a (reason)` where a state cannot occur.

## 5. Interaction and accessibility

- Keyboard:
  - Tab:
  - Enter/Space:
  - Arrow keys:
  - Esc:
  - Focus return:
- ARIA:
  - Role:
  - Accessible name:
  - State:
  - Described-by:
  - Live region:
- Touch target: `<≥ 44 px>`
- Focus ring: `<3 px pen-blue, 3 px offset>`
- Screen-reader announcement:
- Colour-independent meaning:
- Reduced-motion behaviour:

## 6. Content and i18n

- Copy keys:
- Pluralization:
- Number/date format:
- Never-translate values:
- `lang` attributes:
- Missing-variant behaviour:
- Error copy:

## 7. Privacy and security

- Data read:
- Data emitted:
- Free text? `<no>`
- PII? `<no>`
- Raw audio? `<no>`
- Consent gate? `<yes / n/a>`
- External request? `<none>`

## 8. Performance

- DOM nodes:
- JS bytes:
- CSS bytes:
- Layout thrash risk:
- Animation properties:
- Lazy media:
- Weak-Android result:

## 9. Tests

- [ ] Markup/static test
- [ ] Behaviour test
- [ ] State or failure test
- [ ] Keyboard/a11y test
- [ ] Perf/no-network test
- [ ] Regression test (if a bug)

## 10. Usage rules

- Use when:
- Do not use when:
- Must never become:
- Related components:

## 11. Review checklist

- [ ] It is a kit component, not a page-local copy.
- [ ] Every applicable state is implemented and tested.
- [ ] Keyboard and screen-reader paths are complete.
- [ ] 44 px target and visible focus.
- [ ] Reduced motion honoured.
- [ ] Copy keyed; units/symbols not translated.
- [ ] No colour-only meaning.
- [ ] No dead control.
- [ ] No external asset.
- [ ] The visual verdict covers it.
