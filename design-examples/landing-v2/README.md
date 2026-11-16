# Landing concepts v2 — review bundle

**Status:** design exploration, second visual pass. Not product code, not approved copy, no PR.
**Branch:** `feature/w1-f0b-design-shell`, rebased on `main` @ `70545d8`.
**Review URL:** <http://127.0.0.1:8102/>
**Start here:** <http://127.0.0.1:8102/index.html>

This bundle contains **three genuinely different landing-page concepts**, each for one
entrant and one awareness stage. They are built on **base Field Notes §1–§9** and
`docs/frontend/design-doctrine-example.html`, not on the §10 lesson-page extension.

The one §10 content in the bundle is the framed **real capture** of the live Class 9 lesson
page on concept C. The capture is a product artifact; the landing chrome itself is flat paper,
Bricolage/Courier, square corners, one pen mark, and no ruled page, tape, Caveat, language bar
or voice dock.

## Serve it

```bash
cd /home/archit-gore/projects/zivon/tmp/worktrees/w2-f0b
python3 -m http.server 8102 --bind 127.0.0.1 --directory design-examples/landing-v2
```

The server is already running; PID in `/tmp/landing-v2-server.pid`.

## The three concepts

| # | Page | Entrant | Awareness | Promise | Primary action |
|---|---|---|---|---|---|
| A | [The 8pm Doubt](concept-a.html) | Classmate’s link; one phone, 8pm | Solution-aware | Ask the page. Out loud. In Hinglish. | Open a chapter |
| B | [The Marked Paper](concept-b.html) | Search / class group; exam-stakes | Problem-aware → product-aware | Know what you actually know. | Open a test |
| C | [The Build Log](concept-c.html) | Build-in-public post; curious follower | Product-aware | A Physics page that answers where you are reading. | See a real page |

**A** is a voice-first transcript ad: the artifact is a sample Hinglish doubt turn anchored to
the net-force diagram, followed by the mechanism, source ledger, a live check, coverage,
privacy, founder note and FAQ.

**B** is an exam-results ad: the hero is a marked chapter test (`28/35`, concept breakdown,
palette, next step), followed by “a score is not a map”, the attempt → review → practise →
prove loop, a Q14 review artifact, coverage with the non-affiliation copy, privacy and FAQ.

**C** is a build-log ad: the hero is a real capture of the live lesson page, followed by a
before/after, dated build log, how-a-page-is-made process, the page spread with a sample
transcript, source ledger, current six-page coverage, privacy and founder note.

## What to review

Read the [review index](index.html) first. It states the three entrants, the three arguments and
the exact decisions requested. Then open each concept at 1280 px and 360 px.

The full brief, storyboard, five headline variants, copy deck, claim ledger, measurement plan and
rubric case for each concept are on [the thinking page](thinking.html). It also flags two
skill/doctrine conflicts instead of silently resolving them.

### The decisions

1. **Which reader owns `/`?** Recommendation: A for `/`; B for a board-practice campaign URL;
   C for `/about` or a launch-log page. Agree or reassign.
2. **A: mechanism or tension headline?** Chosen mechanism; the tension variant is a fair test.
3. **B: outcome or objection headline?** Chosen outcome; the objection variant is stronger for
   product-aware traffic.
4. **Coverage posture.** B assumes launch-state Class 9–10 tests/practice; A uses the current
   Class 9 state; C uses the current six-page state. Promise the launch catalogue or ship the
   current one and grow?
5. **Artifacts.** A’s transcript and B’s result are labelled samples. Accept for the direction
   verdict, or wait for a real consented recording and a live test capture before implementation?
6. **CTA destination.** The concepts anchor to their proof sections. In production: catalogue or
   strongest live chapter? Recommendation: strongest live chapter, no account gate.
7. **The “I” voice.** C is in the founder’s voice. If C is not `/about`, is that voice allowed on
   a public hook page?

## Scope and honesty

- **No §10 in the landing chrome.** Flat paper; no ruled 36 px grid, no taped cards, no Caveat
  headings, no language bar, no voice dock. The C screenshot contains §10 as product content.
- **One pen mark per screen.** A and B use one generated pen underline on one word in the H1;
  C’s one mark is the real page’s title underline inside the framed capture.
- **One primary action per page.** The same label is used in the header, hero and final CTA; all CTAs are local anchors in this exploration.
- **No stock imagery, gradients, blur, shadows, 3D renders, or external hosts.**
- **No backend, network, microphone, localStorage or analytics.** The only JS is the generated
  pen underline and the native disclosure behaviour; the argument works with JS off.
- **Samples are labelled.** A’s voice turn and B’s test result are illustrative; the claim ledgers
  mark them for replacement. C uses a real capture of the live Class 9 page and six dated pages.
- **A/B coverage.** B uses launch-state coverage; the claim ledger marks it `[launch]`. If the
  current catalogue is smaller, either use A/C or change B’s coverage copy before publishing.

## Skill conflicts flagged (not rewritten)

1. `skills/zivon-landing-page-skills/references/art-direction.md:178–182` says the doctrine’s §4
   paper texture — “the graphite hairline every 36 px” — belongs to §1–§9 and “keep the paper’s
   rule”. The founder’s brief and `design-doctrine-example.html` say the landing page must not
   use the ruled 36 px grid. These concepts follow the founder/base example and use flat paper.
2. `skills/zivon-landing-page-skills/SKILL.md:90–93` says “§10 never appears here”. Concept C
   frames a real screenshot of the live lesson, which necessarily contains §10 content. The
   art-direction §2.3 allows a real screenshot as a product artifact; these concepts treat it as
   content, not chrome. If the founder wants zero §10 pixels, C’s artifact must become a text-only
   excerpt or be removed.

No skill file was modified in this exploration.

## Files

```
design-examples/landing-v2/
  index.html            review index: three readers, links, decisions
  concept-a.html        The 8pm Doubt
  concept-b.html        The Marked Paper
  concept-c.html        The Build Log
  thinking.html         briefs, storyboards, copy decks, claim ledgers, rubric case
  assets/landing.css    base Field Notes §1–§9 landing layer
  assets/landing.js     one generated pen underline; native disclosures
  assets/lesson-crop.png/webp  real capture of the live Class 9 page title
  assets/check-crop.png/webp   real capture of the live Class 9 check card
  assets/fonts/         local woff2 + FONTS-LICENSE.md
```

No tracked `frontend/`, `docs/`, or `skills/` code was modified. The old `design-examples/f0b-shell/`
is left untouched as the rejected reference.
