# SEO & discoverability plan — static multilingual site

Agent: SP5-FRONT · Status: SPEC. Consumes
`skills/zivon-frontend-skills/seo-optimization.md` (the [V]-tagged SEO rules
written for this task), the deployment truth (`docs/deployment/`,
`scripts/publish-frontend.sh`), the doctrine (§0/§10 scopes), and the brief's
child-privacy guardrail. The site is already SSG-by-construction (static files
served by nginx) — everything here either SHIPS metadata in that static output
or GENERATES more static files at publish time. No runtime SEO machinery, no
third-party anything.

Ownership note (boundaries matter): this plan ASSIGNS work items to owners.
Items touching `scripts/publish-frontend.sh`, factory stages, or CI workflows
are outside this spec agent's file boundary and are flagged for the merge
agent / respective owners — listed in §8's assignment table.

---

## 1. Constraints that shape the plan

| Constraint | Consequence |
|---|---|
| CSP `connect-src 'none'`; no third-party hosts (G2/G7) | no Search Console script, no analytics, no external SEO tooling — verification and monitoring use DNS/static-file methods only (§7) |
| Child privacy (DPDP flags, method reference 06) | no behavioural tracking of any kind; OG/share images must never depict child testers (consented footage is for the demo video, not page assets); metadata claims must match reviewed content (no clickbait on a children's product) |
| Static, no-JS-redirects [V: seo skill §3] | every variant is a real file at a real URL; language selection is content-level (§10.5 bar), never a JS redirect |
| Hosting/domain still open (TIMELINE ⬜) | all absolute URLs derive from ONE env value, `ZIVON_PUBLIC_BASE_URL` (config via env, no secrets); nothing hard-codes a domain |

## 2. Per-page metadata (ships in the static HTML)

| Page | `<title>` | meta description | canonical | OG/Twitter |
|---|---|---|---|---|
| Landing (`SCR-HOME-01`) | `Zivon — Physics you can talk to` (copy key `home.seo.title`) | one sentence: NCERT-based interactive Physics pages + Hinglish voice tutor (copy key `home.seo.desc`) | `ZIVON_PUBLIC_BASE_URL + /` | `og:type=website`, `og:title`, `og:description`, `og:image=$BASE_URL/assets/og-card.png` |
| Lesson (`SCR-LES-01`) | `<Lesson title> — Zivon` (renderer already emits this shape) | derived from the lesson's first text block / objectives (renderer rule, not hand-written per page) | `…/courses/<course_id>/<topic_slug>/` | `og:type=article`, plus `og:updated_time` from `manifest.generated_at` |
| 404 | `Page not found — Zivon` | n/a | n/a | n/a |

Mechanics: the LANDING page is shell-owned (EX5-FRONT adds the tags — static
edit); LESSON pages are factory-rendered (the renderer's `<head>` block gains
description/canonical/OG — a factory change, assignment table §8). OG image:
ONE shell-owned static asset (`assets/og-card.png`, Field-Notes look per the
doctrine — founder reviews it; no child imagery). Twitter cards ride the same
tags (`twitter:card=summary_large_image`) — no Twitter-specific files.

## 3. hreflang + localized routes (GATED — do not build until ADR-0009/SP2 land)

- When localized route trees exist (`/{locale}/…`, spec.md §3.2), every page in
  a locale set emits a full hreflang cluster [V: seo skill §2's canonical
  discipline]: `link rel="alternate" hreflang="en"`, `hreflang="hi"`,
  `hreflang="hi-Latn"`, `hreflang="x-default"` → the English canonical — plus
  `rel=canonical` self-reference on each variant. Locale codes MUST match SP2's
  locale model (ABSENT — flag Q4); the values above are the doctrine §10.5 v1
  list as placeholders.
- sitemap gains per-locale entries (`xhtml:link alternates`) in the same
  change — one generator handles both (§5).
- **Until then: zero hreflang tags** (a half-built cluster is worse than none
  [V: search-docs guidance]); the landing page carries only its canonical.

## 4. JSON-LD structured data (per lesson page)

Type: `schema.org/LearningResource` (with `Course`-compatible fields — the
brief asks for Course/LearningResource; LearningResource is the honest type for
a single-topic page, `hasCourseInstance` covers the Course angle [V:
schema.org] — final type call rides the type's validation in §6's Rich
Results check).

Emitted by the FACTORY RENDERER from fields that already exist in
`manifest.json` (no new data required):

```json
{
  "@context": "https://schema.org",
  "@type": "LearningResource",
  "name": "<manifest.title>",
  "inLanguage": "en",
  "educationalLevel": "Class <manifest.class>",
  "about": {"@type": "Thing", "name": "Physics"},
  "learningResourceType": "interactive lesson",
  "isBasedOn": [{"@type": "Book", "name": "<sources[].title>",
                 "license": "<sources[].license>"}],
  "dateModified": "<manifest.generated_at>",
  "provider": {"@type": "Organization", "name": "Zivon"},
  "url": "<ZIVON_PUBLIC_BASE_URL>/courses/<course_id>/<topic_slug>/"
}
```

Rules: rendered server-side into the page head (crawlers see it without JS
[V: seo skill §1]); NO tracking pixels inside it; `isBasedOn` carries the
source-pack honesty rule into the metadata (licenses surface to crawlers too).
**Factory-boundary item — assignment table §8.**

## 5. sitemap.xml + robots.txt (generated at publish time)

- **Generator**: a small stdlib-only script, `scripts/gen-seo-files.py`
  (EX5-FRONT work item), reading `frontend/courses.js` + each
  `frontend/courses/*/manifest.json` + `ZIVON_PUBLIC_BASE_URL` from the
  environment; writes `frontend/sitemap.xml` + `frontend/robots.txt`. It is
  IDEMPOTENT and offline (no fetches) — same discipline as the publish flow.
- **Hook**: invoked by `scripts/publish-frontend.sh` after the courses copy
  succeeds (a 2-line addition to that script — **shared-file line edit,
  assignment table §8**), and documented in the script's header comment.
  Committed together with the published snapshot so sitemap, robots and
  courses.js never disagree (the snapshot IS the deployable truth).
- **sitemap.xml**: landing URL + one `<url>` per catalogue entry
  (`<loc>`, `<lastmod>` = `manifest.generated_at`). Per-locale alternates
  added only with §3. Split-by-section is unnecessary at this scale (< 50k
  URLs for the foreseeable future) [V: sitemap limits are 50k/URL set].
- **robots.txt**: allow all; `Disallow: /healthz` (probe endpoint, not
  content); sitemap pointer `Sitemap: <base>/sitemap.xml`. Nothing else —
  no AI-crawler politics in a file children's product ships; blocked paths
  start as the minimum honest set.

## 6. Core Web Vitals (ride the existing budget — no second regime)

| Metric | Threshold [V: seo skill §4] | Where enforced |
|---|---|---|
| LCP ≤ 2.5 s (p75 mobile) | the LCP element is the `h1.zn-title` — text, no hero image, never lazy-loaded (it already is the first paint) | Era-2 FCP/load budgets + `perf-budget-tests.md` §3 (lab) |
| INP ≤ 200 ms | `test_no_long_tasks_blocking_input` (long-task proxy) | perf spec |
| CLS ≤ 0.1 | `test_cls_under_threshold`; the font swap is THE cls risk → C4 (woff2 + preload) is also the CLS fix, not just the load fix | perf spec |

Lab vs field honesty: CI gives LAB numbers; field data needs Search Console —
which is gated on §7's privacy review. The plan accepts lab-only until the
founder says otherwise (recorded as Q8).

## 7. Child-privacy guardrails (the non-negotiables of this plan)

1. No third-party trackers, SEO tools, or analytics scripts — the CSP forbids
   them and this plan never relaxes it for SEO's sake.
2. Search Console / Bing Webmaster verification: DNS TXT record or a static
   `google<hash>.html` file committed to the shell — NO JS snippet.
3. OG/share images: Field-Notes artwork only; never frames from kid-testing
   footage (consent scope was demo-video recording, not share assets).
4. Metadata honesty: titles/descriptions describe reviewed content; `dateModified`
   comes from the pipeline, not hand-edits; the source-pack licenses surface via
   JSON-LD `isBasedOn`.
5. No hreflang/sitemap entry for anything that is not a published, reviewed
   page (the courses.js snapshot is the allowlist by construction).

## 8. Assignment table (who does what — boundaries respected)

| # | Item | Owner | Boundary note |
|---|---|---|---|
| S1 | Landing meta/canonical/OG tags + `assets/og-card.png` | EX5-FRONT | shell files |
| S2 | Renderer head block for lesson pages (description/canonical/OG/JSON-LD) | factory owner (EX5/factory agent) | factory boundary; fields all exist in manifest.json — flagged in `integration_notes` |
| S3 | `scripts/gen-seo-files.py` | EX5-FRONT | new script |
| S4 | 2-line hook in `scripts/publish-frontend.sh` calling S3 | merge agent / founder | shared script, outside this agent's boundary |
| S5 | hreflang cluster + per-locale sitemap | EX5-FRONT — GATED on ADR-0009/SP2 locale model | do not build early |
| S6 | Lighthouse CI job (lab vitals on PRs, seo skill §5) | CI/CD agent | `ci.yml` outside this agent's boundary |
| S7 | Search Console setup (DNS verification) | founder | needs the domain decision (TIMELINE ⬜) |
