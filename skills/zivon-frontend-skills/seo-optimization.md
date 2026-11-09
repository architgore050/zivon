---
name: seo-optimization
description: SEO fundamentals for EX5-FRONT — technical SEO (SSR/SSG, metadata, sitemaps, structured data), Core Web Vitals as ranking inputs, and crawl/index hygiene. Consumed by SP5 and EX5-FRONT.
consumed-by: SP5, EX5-FRONT
sources:
  - https://developers.google.com/search/docs
  - https://web.dev/articles/vitals
---

# SEO Optimization (frontend bundle addition)

## 1. Rendering strategy [V]

- SSR or SSG for indexable routes; client-only rendering delays/degrades
  indexing. If hydration cost matters, use partial hydration / islands for
  interactive widgets only.
- One canonical URL per page; `rel=canonical` on every parameterized route to
  merge duplicate signals.

## 2. Metadata & structured data [V]

- Unique `<title>` and meta description per route; Open Graph + Twitter cards
  for social surfaces.
- Structured data (JSON-LD: Organization, Product, Article, FAQ) where the
  page type warrants it; validate with the Rich Results Test.

## 3. Crawl & index hygiene [V]

- `robots.txt` + XML sitemap (split by section for large sites, ping on
  publish); noindex for thin/internal routes (search, cart, filters).
- Client-side redirects (JS) are unreliable for crawlers — emit real 301/302
  at the edge/server.

## 4. Core Web Vitals as ranking inputs [V]

- LCP ≤ 2.5 s, INP ≤ 200 ms, CLS ≤ 0.1. These are measurable field metrics
  (CrUX), not lab scores — optimize for the p75 mobile experience.
- Largest-contentful-paint element: preload hero image, server-render it, and
  never lazy-load the LCP element.
- INP: break up long tasks; route-level code splitting must not block input.

## 5. Operational checks

- Lighthouse CI on PRs for lab vitals; Search Console for field data and
  coverage errors; log-file or crawler analytics for crawl-budget issues on
  large sites.

## Evidence tags

- [V] verified against Google Search Central docs and web.dev vitals guidance
