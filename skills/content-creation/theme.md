# theme.md: the rules every Zivon post follows

Status: v0.6 (31 Oct). Items marked **[CONFIRM]** are proposals or blanks only the founder can settle. Everything
else is a default. Change a value here and every skill that reads this file follows it.

## 0. How this file is used
- All post, video, and photo skills (x-post-interviewer, linkedin-post-interviewer, video-edit-director,
  photo-edit-director) read this file first.
- For anything visual, also read `docs/frontend/design-doctrine.md` (see section 2): this file no longer defines
  a visual design of its own.
- Precedence: the founder's instruction for a specific post > this file > a skill's built-in defaults.
- If a skill's advice conflicts with this file, follow this file and say so in one line.
- Never invent facts to satisfy a template. A missing number is a question to the founder, not a blank to fill.

## 1. Identity [CONFIRM all]
- What Zivon is, in one sentence: `[CONFIRM]`
- Who it is for (role, stage): `[CONFIRM]`
- The founder's voice in three words (examples: plain, specific, candid): `[CONFIRM]`
- Words the founder never uses: `[CONFIRM]`
- Handles and links: X `[CONFIRM]`, LinkedIn `[CONFIRM]`, repo `https://github.com/architgore050/zivon` (public)
- Every post carries the repo link. Placement follows section 7: X first reply, LinkedIn in the post body.
- AI disclosure policy (posts or visuals made with AI help): `[CONFIRM: always say / say when asked / say on visuals only]`

## 2. Visual system (delegated: the design doctrine)

This file does not define a visual design. All design rules — palette, fonts, sizes, layout, card types, day
counter styling, annotation and colour rules — live in **`docs/frontend/design-doctrine.md`** ("Field Notes",
v1.0, confirmed 31 Oct). Read that file before producing any image, carousel, or video frame.

- Reference implementation: **`docs/frontend/design-doctrine-example.html`** — a working page rendering the whole
  system: the CSS-variable tokens, the single pen-blue underline, pencil-red `not yet` stamps, tick-green done
  tags, the taped rotated card, and the `Day 01` counter. Open it before generating post visuals or cards and
  match its patterns; it is the concrete bar for every future generation.

- One doctrine, one look: post visuals and the product UI follow the same design system, so the post series and
  the product feel like the same notebook.
- Precedence for visuals: the founder's instruction for a specific post > the design doctrine > a skill's
  built-in defaults.
- The doctrine invariants the rest of this file refers back to: paper background with ink text; ONE pen-blue
  annotation per image; pencil-red reserved for honest gaps; the `Day NN` day counter top-left in Courier
  Prime; minimum 32 px text at 1080 px width.

Posting-side rules that stay in this file:
- Formats: 4:5 or 1:1 for images (default 1080x1350), 16:9 for link-style previews, 9:16 for vertical video.
- Keep faces, text, and logos in the central safe area; platform UI covers the top and bottom edges (verify in
  the current composer before export).
- **Scoreboard strip** (optional, bottom): 3-5 tracked numbers, same order every day. Metrics are `[CONFIRM]`.
  Example slots: tests passed, active testers, pieces produced, days to v1. Numbers need a denominator or a
  comparison ("12 of 30"), never a bare brag. Styling follows the design doctrine.
- No logo on every slide. The day counter is the brand.

## 3. Series structure (what makes the days connect)

Every post is one episode of a continuing story. Viewers return for the next episode, not for a single post.

### 3.1 The daily spine
1. **Recap hook (1 line, optional on X, recommended on LinkedIn):** what yesterday ended on, plus the open
   question it left. Pay off the previous day's commitment first ("Yesterday I said I'd X. Here's what happened.").
2. **Today's proof:** the single most concrete result, with a real number or visible output.
3. **The decision:** one real tradeoff made today and what it cost.
4. **The honest gap:** one thing not done and why that was a choice or a failure.
5. **Tomorrow's commitment:** one specific, checkable promise (a thing, not a feeling). Tomorrow's recap must
   report on it, hit or miss.
6. **The ask:** one, and only one (see section 6).
Not every post carries all six; at minimum: proof + gap + commitment.

### 3.2 Open loops and payoffs
- Every post closes the loop it opened and opens exactly one new one.
- Never open a loop you will not close within 3 days. Never tease something that does not exist yet.
- If a commitment is missed, the next post says so first. That is the strongest trust signal in the series.

### 3.3 Weekly and milestone rhythm
- Day 7 (and every 7th day): a weekly recap in one visual (what shipped, what slipped, one number that moved, the
  next week's single goal). Link or reference the 6 daily posts.
- Milestones (first tester, first real output, v1 ships, domain bought, CI/CD live): their own post, a story, not an
  announcement. Show the before state and the cost.
- Vary the format day to day. Never use the same hook pattern or card type three days in a row.

### 3.4 Storytelling patterns (pick one per post)
- **Scene > tension > decision > result > turn.** Start in a specific moment, not a summary.
- **Receipts:** "N days, N things, here is what actually happened."
- **The reversal:** what I believed, what I saw, what I changed.
- **The fork:** two options, what each costs, which I chose, ask the audience which they would pick.
- **The failure post:** what broke, the first wrong assumption, the fix, what it cost in hours.
- **Show the work:** one screen recording of the thing doing its job once, start to finish.

### 3.5 Day-count convention (decided 31 Oct)
- In post text the day count is always `Day N of 12` and is always tied to the programme name in the same
  sentence: **Gnani AI's Great Indian AI Internship Challenge**. Never a bare "Day N", never "12-day build".
  A reader with zero context must get what the count refers to in the first line.
- Approved shapes:
  - X: `Day N of 12 building Zivon for Gnani AI's Great Indian AI Internship Challenge: <product one-liner>.`
  - LinkedIn: `Day N of 12 in the Great Indian AI Internship Challenge, <hook claim>.`
- The visual day counter follows the design doctrine (`Day NN`, Courier Prime, top-left; see section 2); the
  challenge name lives in the post text, not in the counter.

## 4. Voice and writing
- First person singular. Plain words. Contractions. Short sentences; break any sentence over 20 words.
- Specific over adjectival: numbers, file names, dates, named tools, real quotes.
- State opinions as facts when they are earned by something you did; say "I'm not sure" when you are not.
- No em dashes. X: every post ends with the two mandatory programme tags `#GreatIndianAIInternshipChallenge`
  and `#GnaniAI` (founder decision 31 Oct; the writer adds them automatically, the founder never has to
  remember). No other tags unless the founder asks. They count inside the hard 280-character cap: the tags plus
  their line breaks cost 44 characters, so the body must fit in 236. LinkedIn: 0-3 specific hashtags, at the end.
- Banned words: leverage, unlock, delve, harness, streamline, game-changer, revolutionize, supercharge, seamless,
  cutting-edge, "in today's fast-paced world", "excited to announce", "thrilled", "journey" (unless literal).
- Emojis: none by default. `[CONFIRM]` if the founder's own voice uses them.
- Vary list lengths; avoid mechanical rule-of-three rhythms and "not X, but Y" templates repeated post after post.

## 5. Psychology rules (the subtle part)

### 5.1 Avoid bloat
- One idea per post. If there are two, save one for tomorrow.
- Cut the first sentence and see if the post still works; usually it does. Then cut 20% of what remains.
- Every sentence must add a fact, a feeling, or a turn. Throat-clearing, restatements, and summaries get cut.
- If a post needs more than about 1,300 characters on LinkedIn or one 280-character post on X (mandatory tags
  included), it needs either a thread/carousel or a smaller idea.

### 5.2 Avoid the "this is an ad" feeling
Readers detect promotion in under a second. The tells, and what to do instead:
| Ad tell | Do this instead |
|---|---|
| Opens with the product name or "Introducing" | Open with a result, a number, or a scene |
| Feature lists, benefit lists | One concrete moment where the thing did something |
| Superlatives (best, fastest, revolutionary) | A measured fact with its limit |
| CTA in the first line; "link in bio" energy | Keep links out of the hook line; place them after the story (LinkedIn body, X first reply) |
| Polished stock imagery, glossy mockups | Real screenshots, real desk, real mess |
| Logo-heavy visuals | Day counter only |
| Testimonials without names or specifics | Nothing, or a real quote with permission |
| Constant selling | 80% give (a lesson, a number, a decision) / 20% ask |
| Fake urgency, scarcity | Real dates only |
| "We" corporate voice | "I" until there is actually a team |
Test: if the post still reads fine with the product name replaced by `[Product]`, it is probably an ad.

### 5.3 Avoid generic
- **Swap test:** could another founder post this by changing the product name? If yes, rewrite.
- **Specificity ladder:** claim > number > named thing > real quote or screenshot. Climb at least two rungs.
- **Screenshot test:** would someone screenshot this and send it to a friend?
- No lessons you did not learn today. No motivational wrap-ups. No "here's what I learned" unless it is a
  specific, surprising, checkable lesson.

### 5.4 Keep it interesting (ethically)
- Curiosity gaps are allowed only if the post pays them off inside itself. No bait-and-switch, no "you won't
  believe".
- Lead with the most interesting true thing, not the chronological first thing.
- Mix emotions across the week: curiosity, tension, relief, honest embarrassment, pride earned. One per post.
- Concreteness creates tension: "40 minutes of a build failing because of one character" beats "debugging is hard".
- Show the cost of every win and the reason for every delay. People trust accounts that count costs.

### 5.5 Credibility
- Say what is not done. Say what you do not know. Give denominators and time frames.
- Never inflate a metric; never use a number you cannot show. Rounded numbers are fine if labelled "about".
- Do not call something a "launch" if it is a test. Do not call a single tester "users".
- Correct mistakes publicly and quickly, in a reply or the next post.

### 5.6 Self-presentation
- Confident about the process, humble about the outcome. No humble-bragging, no self-deprecation as a tic.
- No hustle-culture language (grind, 10x, crush it, 4am routines).
- Credit people and tools by name when they helped; ask permission before naming a person.

## 6. Interaction rules

### 6.1 One ask per post, matched to the post
| Ask type | When | Template |
|---|---|---|
| Decision question | there is a real fork | "I'm choosing between A and B because X. Which would you pick, and why?" |
| Experience question | the post touches a shared pain | "When did you last X? What did you do instead?" |
| Network ask | you need specific people | "Looking for 3 people who do X to test Y. Reply with Z and I'll DM you." |
| Feedback ask | something is testable | "Here is the output. What is the first thing that looks wrong?" |
| Resource ask | you are stuck | "Has anyone solved X with Y? I tried A and B." |
- The question must be one the writer would genuinely want answered. Never "Thoughts?", "Agree?", "Like if...".
- Make asks small and answerable in one line. Name the exact person you are asking (role, not name).
- Never ask for a share, a like, or a follow in the post. If a follow ask is ever used, make it a promise ("I'll
  post the result tomorrow; follow if you want it").
- Do not tag people to inflate reach.

### 6.2 After posting
- Reply to every substantive reply in the first hour with new information, not "thanks".
- Answer critics with facts and a concession where they are right. Never argue; never delete honest criticism.
- Turn good replies into next-day content ("You asked about X. Here's the answer") and credit them.
- Ask a follow-up question that goes one level deeper than the first answer.
- Comment on 3-5 relevant people's posts BEFORE posting each day, with a specific insight, never "great post".

## 7. Platform differences
| | X | LinkedIn |
|---|---|---|
| Length | 280 chars hard cap including the mandatory tags (this account has no long-post access); threads for more | about 900-1,300 characters |
| Hook | strongest line first, passes the first-three-words test | first ~140 characters carry the post |
| Links | in the first reply | in the post body, after the story |
| Tone | compressed, wry, direct | warmer, story-led, one idea explained |
| Media | proof screenshot or short clip in the hook tweet | one image, short captioned video, or carousel |
| Ask | a reply question | a comment question or a specific network ask |
| Hashtags | exactly the 2 mandatory tags, at the end | 0-3, specific, at the end |
Same story, two different posts: never paste the same text on both.

### 7.1 Exact post text (required output format)
Every draft ends with paste-ready plain-text blocks, one per thing the founder will copy into a composer:
- "EXACT POST TEXT" (one per platform), plus "EXACT FIRST COMMENT" (LinkedIn) or "EXACT FIRST REPLY" (X).
- Inside a block: only the literal characters to paste, line breaks as they should appear in the post. No
  Markdown syntax (`#`, `**`, `>`, backticks, `~~`), no commentary, no placeholders, no character-count notes.
  Platform composers do not render Markdown; the block is what gets pasted.
- Outside the blocks: hooks, hashtag rationale, variants, audit notes, plans. The founder approves the block,
  not the prose around it.
- The X EXACT POST TEXT block includes the two mandatory tags and totals 280 characters or fewer; count it
  before presenting and state the count outside the block. Never drop or swap the tags to fit; compress the
  body instead.
- In post files under `posts/`, the blocks sit near the top of the file and are the source of truth for what is
  or will be published. Once posted, mark the block "POSTED <date>" and keep the text exactly as published.

## 8. Cadence [CONFIRM]
- Post time: `[CONFIRM: audience time zone and slot]`; keep it consistent.
- One main post per day during the build. If nothing real happened, post a short honest note, not filler.
- Weekly recap on day 7. A pre-launch teaser only when there is something real to show.

## 9. Safety and integrity (never overridden)
- No secrets, tokens, `.env` content, private URLs, personal data, or unreleased client information on any frame.
- Minors: no faces, full names, or identifying details without explicit documented guardian consent. Default to
  showing the product, the numbers, or hands only. This includes the Day 1 test participant if they are a minor.
- No fake results, staged outputs, or edited numbers. Mockups are labelled as mockups.
- Third-party content, music, and images: only what is licensed or original; credit sources.
- Reach and view statistics quoted in skills (retention thresholds, algorithm weights) are heuristics from
  third-party sources, not guarantees. Never promise virality.

## 10. Pre-post checklist (all must be true)
- [ ] One idea; the first line works alone
- [ ] A real number, name, or visible output (specificity ladder: two rungs up)
- [ ] The gap is stated honestly; the commitment for tomorrow is specific
- [ ] Yesterday's commitment is reported on (hit or miss)
- [ ] Not an ad: passes the product-name swap test; no banned words; no superlatives
- [ ] Passes the swap test and the screenshot test
- [ ] Exactly one ask, genuine and specific
- [ ] Visuals follow `docs/frontend/design-doctrine.md`: one pen annotation, day counter present, minimum
      32 px text, readable at 300 px wide
- [ ] Secrets sweep done on the exported files; minors and consent checked
- [ ] Repo link present in every post (X: first reply; LinkedIn: post body); X posts carry exactly the two
      mandatory tags and fit 280 characters including them (count stated)
- [ ] Each platform's post and its first comment/reply exist as EXACT POST TEXT blocks: plain text,
      paste-ready, no Markdown syntax (section 7.1)
- [ ] A reply plan exists for the first hour

## 11. Open decisions (answer once; then delete this section)
1. One-line description of Zivon and its target reader.
2. Design doctrine: answered 31 Oct (founder decision, final). `docs/frontend/design-doctrine.md` (Field
   Notes, now v1.0) is the single source of truth for all post visuals and the product UI.
3. The 3-5 scoreboard metrics to track daily.
4. The founder's voice samples (3 real posts or messages) and words to never use.
5. AI disclosure policy.
6. Posting time zone and slot. (Answered 31 Oct: X has no long-post access; 280-char hard cap including the
   mandatory tags.)
7. Who is the Day 1 test participant, and do they appear in any asset (consent status)?

## 12. Changelog
- v0.1 (Day 1): first version; palette and fonts are proposals.
- v0.2 (Day 2): repo link made a required element of every post (section 1); day-count convention added
  (section 3.5), both from the Day 0 post work.
- v0.3 (Day 3): section 2 no longer defines its own visual system; visual design defers to
  `docs/frontend/design-doctrine.md` (Field Notes). Day counter, checklist, and open-decisions wording aligned
  with it. Reference implementation `docs/frontend/design-doctrine-example.html` named as the concrete bar for
  post visuals.
- v0.4 (Day 3): section 7.1 added (exact post text blocks). Cause: the Day 0 post had to be assembled from
  Markdown fragments because no skill required a paste-ready plain-text block; both interviewer skills and the
  pre-post checklist now enforce 7.1.
- v0.5 (Day 3): founder decisions from the Day 0 X post. (1) The two programme hashtags are mandatory on every
  X post, inside a hard 280-char cap (sections 4, 5.1, 7, 7.1, 10); the writer adds them automatically after
  the first Day 0 X attempt missed them and the post had to be redone. (2) LinkedIn links move from the first
  comment to the post body (sections 1, 5.2, 7, 10); X links stay in the first reply.
- v0.6 (31 Oct): design doctrine confirmed as final (founder decision): Field Notes v1.0 is the single visual
  source of truth for post visuals and the product UI (section 2, open-decisions item 2). Day-lag convention
  from the Day 1 post work: when a post covers an earlier build day, the lag is disclosed in the first
  comment/reply, not in the post text (see posts/2026-10-30-day-1.md).
