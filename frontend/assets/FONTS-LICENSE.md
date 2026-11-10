# Bundled fonts

All fonts in this folder are bundled locally so generated pages make **zero
external calls** (repo rule: no external calls from generated pages; pages must
work offline). All four families are licensed under the SIL Open Font License
1.1 (OFL), which permits bundling, subsetting, format conversion (WOFF2), and
redistribution with attribution (provided the Reserved Font Names are not used
to advertise unrelated derivative fonts and the license notice is retained).

| File | Family | Source | License |
|---|---|---|---|
| `BricolageGrotesque-Variable.woff2` / `.ttf` | Bricolage Grotesque (variable: opsz, wdth, wght) | github.com/google/fonts (ofl/bricolagegrotesque), downloaded 2026-11-01 | SIL OFL 1.1 |
| `CourierPrime-Regular.woff2` / `.ttf` | Courier Prime Regular | github.com/google/fonts (ofl/courierprime), downloaded 2026-11-01 | SIL OFL 1.1 |
| `CourierPrime-Bold.woff2` / `.ttf` | Courier Prime Bold | github.com/google/fonts (ofl/courierprime), downloaded 2026-11-01 | SIL OFL 1.1 |
| `Caveat-Variable.woff2` / `.ttf` | Caveat (variable: wght) | github.com/google/fonts (ofl/caveat), downloaded 2026-11-01 | SIL OFL 1.1 |

Spec C4 (2026-11-09): Each bundled TTF was subsetted (Latin + Greek + math/arrow
symbols + check/cross dingbats) and compressed to `.woff2` (`fontTools` +
`brotli`), reducing active font payload from ~940 KB to ~237 KB (< 300 KB Era-2
target) while retaining the `.ttf` files as fallbacks.

Usage rules come from `docs/frontend/design-doctrine.md` (Field Notes v1.6):
Bricolage Grotesque for display/body and controls, Courier Prime for typed
notes, lesson body, and data, Caveat ONLY for lesson titles, section headings,
and short handwritten annotations pointing at typed content.
