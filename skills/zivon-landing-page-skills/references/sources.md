# Sources

Every external claim in this bundle, with its URL, publication date, access date,
and an evidence tag. **All URLs were fetched on 2026-11-16.** Re-verify before
citing; several of these are perishable.

Tags:

- `[E]` — research, a published standard, a regulator, or vendor data with a
  stated methodology. The claim is checkable at the source.
- `[P]` — practitioner model or convention. Useful and widely used, but not a
  controlled finding. Treated as a hypothesis with a track record.

## Research and standards

| ID | Source | Date | URL | Tag | Used for |
|---|---|---|---|---|---|
| S1 | Nielsen Norman Group, *The Fold Manifesto: Why the Page Fold Still Matters* | 2015-02-01 | https://www.nngroup.com/articles/page-fold-manifesto/ | `[E]` | the fold is a real attention boundary; ~84% average difference in treatment above vs below |
| S2 | Nielsen Norman Group, *Scrolling and Attention* | 2018-04-15 | https://www.nngroup.com/articles/scrolling-and-attention/ | `[E]` | ~57% of viewing time above the fold; ~74% in the first two screenfuls; 130,000+ fixations, 120 participants, 1920×1080 |
| S3 | Nielsen Norman Group, *How Long Do Users Stay on Web Pages?* | 2011-09-12 | https://www.nngroup.com/articles/how-long-do-users-stay-on-web-pages/ | `[E]` | visitors often leave in 10–20 s; a clear value proposition within 10 s is what buys minutes; negative-Weibull dwell times from 205,873 pages |
| S4 | Nielsen Norman Group, *Homepage Design: 5 Fundamental Principles* | 2024-03-15 | https://www.nngroup.com/articles/homepage-design-principles/ | `[E]` | state the unique value in the hero; reveal content through examples; the fold gates scrolling |
| S5 | Nielsen Norman Group, *Visual Hierarchy in UX: Definition* | 2021-01-17 | https://www.nngroup.com/articles/visual-hierarchy-ux-definition/ | `[E]` | hierarchy via contrast, scale, and grouping; define the content hierarchy before styling |
| S6 | Nielsen Norman Group, reading-pattern series: *F-Shaped Pattern* (2006, revisited 2017), *Text Scanning Patterns* (2019-08-25), *The Layer-Cake Pattern* (2019-08-04) | 2006–2019 | https://www.nngroup.com/articles/f-shaped-pattern-reading-web-content/ · https://www.nngroup.com/articles/text-scanning-patterns-eyetracking/ · https://www.nngroup.com/articles/layer-cake-pattern-scanning/ | `[E]` | readers scan; front-load lines; descriptive headings enable efficient scanning |
| S7 | Lindgaard, Fernandes, Dudek & Brown, *Attention web designers: You have 50 milliseconds to make a good first impression!*, Behaviour & Information Technology 25(2):115–126 | 2006-03 | https://doi.org/10.1080/01449290500330448 | `[E]` | visual-appeal judgements form within 50 ms and are stable across exposures (about appeal, **not** conversion) |
| S8 | web.dev, *Web Vitals* and *How the Core Web Vitals metrics thresholds were defined* | rolling; fetched 2026-11-16 | https://web.dev/articles/vitals · https://web.dev/articles/defining-core-web-vitals-thresholds | `[E]` | LCP ≤ 2.5 s / > 4 s poor; INP ≤ 200 ms / > 500 ms poor; CLS ≤ 0.1 / > 0.25 poor; evaluated at p75 |
| S9 | W3C, *Web Content Accessibility Guidelines (WCAG) 2.2*, W3C Recommendation | 2024-12-12 (first Recommendation 2023-10-05) | https://www.w3.org/TR/WCAG22/ · https://www.w3.org/WAI/standards-guidelines/wcag/new-in-22/ | `[E]` | SC 2.5.8 Target Size (Minimum) AA = 24×24 CSS px; 2.3.3 Animation from Interactions AAA; 2.2.2 Pause, Stop, Hide AA; 1.2.1/1.2.2 audio and captions |
| S10 | web.dev, *prefers-reduced-motion: Sometimes less movement is more* and *Animation and motion* | rolling; fetched 2026-11-16 | https://web.dev/articles/prefers-reduced-motion · https://web.dev/learn/accessibility/motion | `[E]` | reduced motion means minimise non-essential movement, not remove all; parallax is a vestibular trigger; pause/stop/hide for >5 s |
| S11 | Baymard Institute, *Homepage & Category Navigation UX* research overview | rolling; fetched 2026-11-16 | https://baymard.com/research/homepage-and-category-usability | `[E]` (vendor) | 40+ homepage guidelines from large-scale usability testing; 76% of benchmarked top sites rated mediocre or worse on this theme |
| S12 | Unbounce, *2024 Conversion Benchmark Report* and its methodology page | 2024 (data 2023-07-23 → 2024-07-23) | https://unbounce.com/conversion-benchmark-report/ · https://unbounce.com/conversion-benchmark-report/methodology/ | `[E]` (vendor) | 57M conversions across 41K+ landing pages; median 6.6%; education 8.4%; SaaS 3.8%; lower reading difficulty correlates with higher median conversion (grade 5–7: 11.1% vs college: 5.3%) |

## Regulators and public-service style

| ID | Source | Date | URL | Tag | Used for |
|---|---|---|---|---|---|
| S13 | US Federal Trade Commission, *Guides Concerning the Use of Endorsements and Testimonials in Advertising*, 16 CFR Part 255 | revised 2023 (Federal Register 2023-07-26) | https://www.ecfr.gov/current/title-16/chapter-I/subchapter-B/part-255 | `[E]` | endorsements must reflect honest experience; material connections disclosed; consumer endorsements are not substantiation |
| S14 | US Federal Trade Commission, *Rule on the Use of Consumer Reviews and Testimonials*, 16 CFR Part 465 | effective 2024-10-21 | https://www.ecfr.gov/current/title-16/chapter-I/subchapter-D/part-465 | `[E]` | fake or false reviews/testimonials prohibited; insider testimonials need disclosure |
| S15 | US Federal Trade Commission, *Bringing Dark Patterns to Light* (staff report) | 2022-09 | https://www.ftc.gov/reports/bringing-dark-patterns-light | `[E]` | false urgency, fake scarcity, and deceptive social proof are named deceptive practices; dark patterns compound |
| S16 | GOV.UK content and publishing guidance, *Use clear language*, *Create a clear structure*, *A to Z style guide* | rolling; fetched 2026-11-16 | https://guidance.publishing.service.gov.uk/writing-to-gov-uk-standards/writing-guidelines/clear-language/ | `[E]` | plain English is preferred even by specialists; active voice; paragraphs of no more than five sentences; split sentences over 25 words; a published words-to-avoid list; readers read ~20–28% of a page |

## Practitioner frameworks

| ID | Source | Date | URL | Tag | Used for |
|---|---|---|---|---|---|
| S17 | StoryBrand (Donald Miller), *The StoryBrand 7-Part Framework* workbook and *Your Brand is Not the Hero* | rolling; fetched 2026-11-16 | https://storybrand.com/downloads/StoryBrand-Online-Marketing-Course-Workbook.pdf | `[P]` | character → problem → guide → plan → call to action → avoid failure → reach success; the customer is the hero, the brand is the guide |
| S18 | Eugene Schwartz, *Breakthrough Advertising* (1966), five stages of awareness | 1966; summarised from secondary sources (book is out of print) | https://personalmba.com/levels-of-awareness/ · https://growthmarketer.co/stages-of-awareness/ | `[P]` | unaware → problem-aware → solution-aware → product-aware → most-aware; the message must match the stage |

AIDA, PAS, BAB, FAB and 4U are conventional direct-marketing models with no
single canonical source; they are used here as lenses and labelled `[P]`
wherever they appear.

## Teardown pages (linked, not reproduced)

Observed 2026-11-16. Structural observations only; these pages change.

| Page | URL | HTTP status at fetch |
|---|---|---|
| Stripe | https://stripe.com | 200 |
| Linear | https://linear.app | 200 |
| GOV.UK | https://www.gov.uk | 200 |
| Basecamp | https://basecamp.com | 200 |
| Wikimedia donation | https://donate.wikimedia.org | 200 |
| The Pudding | https://pudding.cool | 200 |
| Craigslist | https://www.craigslist.org | 200 |
| Berkshire Hathaway | https://www.berkshirehathaway.com | 200 |
| Brilliant | https://www.brilliant.org | 200 |

Land-book (`https://land-book.com`) and Lapa Ninja (`https://www.lapa.ninja`)
returned HTTP 403 to automated fetch and were not used. Design-inspiration
libraries such as Refero (`https://refero.design`), Mobbin
(`https://mobbin.com`), Page Flows (`https://pageflows.com`) and Landingfolio
(`https://www.landingfolio.com`) were reachable but are galleries of *visual*
references; they are useful for seeing a pattern and useless as evidence. Do not
cite a gallery as proof that something works.

## Limits of this research

Recorded so the next reader does not over-trust the bundle.

- **The dwell-time and fold studies are old and mostly desktop.** S2 (2018) used
  1920×1080; S3 (2011) used 1024×768. The *direction* of the findings has held
  across replications; the exact percentages have not. Treat them as "the fold
  matters a lot", not as "57%".
- **Lindgaard measures visual appeal, not conversion.** The 50 ms result says a
  first impression forms fast; it does not say a good first impression converts.
- **Unbounce is vendor data about lead-generation landing pages.** The median is
  useful for order of magnitude and for the reading-difficulty correlation, not
  as a target for an education product whose action is "open a chapter".
- **Baymard's full guidelines are paid.** Only the public research overview was
  read; no individual guideline is quoted here.
- **Schwartz is summarised second-hand.** The book is out of print and scarce;
  the five stages are consistent across multiple secondary summaries, which is
  why the model is used, and it is labelled `[P]` for that reason.
- **The FTC material is US law.** Zivon's users are in India; the Indian
  equivalent (Consumer Protection Act 2019 and the CCPA's dark-pattern
  guidelines) is not researched here. The FTC rules are used as a *floor* for
  honest behaviour, not as the applicable law. Route legal questions to
  `docs/compliance/` and counsel.
- **Core Web Vitals thresholds can change.** They are reviewed periodically;
  check S8 before quoting them in a decision.

## Re-verification checklist

Before citing any number from this bundle:

1. Open the source. Does it still say what the table says?
2. Check the date. If it is older than two years, look for a newer version.
3. Check the method. Vendor data, lab study, field study, or opinion?
4. Check the population. Whose users, which devices, which country?
5. Update this file, the citing reference, and `metadata.evidence_date` in
   `SKILL.md` — in the same PR.
