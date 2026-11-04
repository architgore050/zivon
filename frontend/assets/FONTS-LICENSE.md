# Bundled fonts

All fonts in this folder are bundled locally so generated pages make **zero
external calls** (repo rule: no external calls from generated pages; pages must
work offline). All four files are licensed under the SIL Open Font License 1.1
(OFL), which permits bundling and redistribution with attribution.

| File | Family | Source | License |
|---|---|---|---|
| `BricolageGrotesque-Variable.ttf` | Bricolage Grotesque (variable: opsz, wdth, wght) | github.com/google/fonts (ofl/bricolagegrotesque), downloaded 2026-11-01 | SIL OFL 1.1 |
| `CourierPrime-Regular.ttf` | Courier Prime Regular | github.com/google/fonts (ofl/courierprime), downloaded 2026-11-01 | SIL OFL 1.1 |
| `CourierPrime-Bold.ttf` | Courier Prime Bold | github.com/google/fonts (ofl/courierprime), downloaded 2026-11-01 | SIL OFL 1.1 |
| `Caveat-Variable.ttf` | Caveat (variable: wght) | github.com/google/fonts (ofl/caveat), downloaded 2026-11-01 | SIL OFL 1.1 |

Usage rules come from `docs/frontend/design-doctrine.md` (Field Notes v1.0):
Bricolage Grotesque for display/body, Courier Prime for typed notes and data,
Caveat ONLY for short handwritten annotations pointing at typed content.
The variable fonts are declared with `font-weight: 100 900` ranges in
`frontend/assets/zivon.css`; if a font file is ever missing, the CSS font
fallbacks (Arial / Courier New / cursive) render instead - that is a rendering
degradation, not a pipeline behaviour.
