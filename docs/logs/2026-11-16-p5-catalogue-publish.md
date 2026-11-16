# 2026-11-16 — P5 catalogue v2, publish integrity and SEO

Branch: `feature/w2-p5-catalogue-publish` (worktree `tmp/worktrees/w2-p5`), based on
`main` @ `03fd190`.

## Done

- `factory/catalogue.py` (new): catalogue v2 build/validation.
  - writes `catalogue.json` v2 (manifest-v2 core + `href` + `chapter_number` +
    `localized_hrefs` + narration coverage + `pipeline_version`) and derives
    `courses.js` from it (status/languages/counts/concepts/exam_weight).
  - version guard: `integrity.status` is `ok` / `mixed` / `incomplete`;
    `mixed_versions` and `missing_versions` are named per topic.
  - locale hrefs are route-aware (`<topic>/<locale>/` and `<locale>/<topic>/`),
    and a promised locale with no route is listed, never silently English.
  - publish smoke: catalogue version, hrefs, locale routes + i18n + locale
    manifest, P1 hooks (`factory.hooks.hook_issues`), `lesson_title`,
    usable `chapter.title`, sitemap URLs, robots pointer, narration gaps,
    placeholder base URL.
  - CLI: `python3 -m factory.catalogue build|check` (`--strict`, `--skip-seo`,
    `--allow-placeholder`, `--json`).
- `factory/link.py`: publishes through `catalogue.build`; prunes a superseded
  duplicate that shares the chapter **or the run id**; preserves the previous
  narration manifest/flag and per-locale manifests across a re-render when the
  block set still matches; writes the locale `manifest.json` the shell reads for
  localized read-aloud (honest `available: false` when nothing matches).
- `scripts/publish-frontend.sh`: copies `catalogue.json`; `--dry-run` +
  `--source-dir`; strict catalogue gate before replacing the snapshot; SEO
  regeneration after locale hubs; final strict smoke; `--allow-placeholder`
  only as an explicit local-snapshot escape hatch.
- `scripts/gen-seo-files.py`: hreflang alternates come from the catalogue's
  `localized_hrefs` first (verified on disk), with the old disk walk as fallback.
- Republished the live tree from existing runs at `PIPELINE_VERSION` 9:
  six topics, one version, zero `Grade`, `lesson_title` on every manifest,
  class-9 chapter 4 (`Describing Motion Around Us`) and chapter 6
  (`How Forces Affect Motion`, number 6) corrected, the stale `/motion`
  duplicate pruned, and narration + per-locale manifests carried forward.
  Every topic reports `available: true`; two of the six still have **one
  un-narrated speakable block** each (`units-and-measurement` `b-26`,
  `laws-of-motion` `b-28`), named in `catalogue.json` `narration.missing_blocks`
  and in the publish check's warnings - not claimed as covered.
- The republish also removed two runtime hand-patches that had been edited
  directly into generated `page.js` files (they were not reproducible and are
  not published by any stage):
  - `units-and-measurement`: a `MutationObserver` that re-styled every SVG on
    every DOM mutation (a weak-Android perf hazard) and rewrote one check
    question in place. Removing it restores the artifact's own NCERT wording
    ("meaningful **without** specifying a standard for comparison"), which is
    the correct question for that answer/explanation pair.
  - `units-and-measurement` sim readout machinery: redundant, `zivon.js`
    already drives `.zn-sim-read`.
  The underlying a11y gap the patch masked is real and pre-existing: diagram
  `<svg>` elements on 4 of the 6 topics carry no `role="img"`/`aria-label`
  (only `laws-of-motion` and `how-forces-affect-motion` do). Root-cause fix is
  the renderer's (`factory/render.py`, P1) plus an `EV-VIS-002` rule (P4);
  recorded in `TIMELINE.md` as debt, not fixed here.
- Tests: `testing/content_factory/unit/test_catalogue_publish.py` (25 tests:
  version guard, v2 shape/order, locale hrefs incl. prefixed routes, hooks,
  sitemap/robots, narration honesty, link preservation/pruning, publish-script
  dry-run, SEO generator contract). `testing/frontend/test_shell.py` now checks
  the current `i18n/<locale>.json` localized contract instead of the retired
  locale-manifest shape.
- Docs: `docs/content-factory/{architecture,blocks-schema,runbook}.md`,
  `docs/deployment/kubernetes.md`, this log.

## Not done / open

- Production sitemap is still the dev placeholder: `ZIVON_PUBLIC_BASE_URL` has
  no decided origin (open-questions Q10). The strict publish gate refuses the
  placeholder; the committed snapshot was regenerated with
  `--allow-placeholder` and is explicitly not production-publishable.
- The class-11 chapter titles in manifests stay as the NCERT display caps
  (`LAWS OF MOTION`); the page/catalogue `title` is display-cased. That is P1's
  manifest contract, not changed here.

## Next

- Founder/infra: set the public origin, run a real `publish-frontend.sh`, and
  commit the clean sitemap/robots.
- F1: consume `catalogue.json`/`courses.js` `localized_hrefs` +
  `missing_locales` for the hub cards.
