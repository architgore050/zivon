# theme.md: the rules every Zivon post follows

Status: v0.1 (Day 1). Items marked **[CONFIRM]** are proposals or blanks only the founder can settle. Everything
else is a default. Change a value here and every skill that reads this file follows it.

## 0. How this file is used
- All post, video, and photo skills (x-post-interviewer, linkedin-post-interviewer, video-edit-director,
  photo-edit-director) read this file first.
- Precedence: the founder's instruction for a specific post > this file > a skill's built-in defaults.
- If a skill's advice conflicts with this file, follow this file and say so in one line.
- Never invent facts to satisfy a template. A missing number is a question to the founder, not a blank to fill.

## 1. Identity [CONFIRM all]
- What Zivon is, in one sentence: `[CONFIRM]`
- Who it is for (role, stage): `[CONFIRM]`
- The founder's voice in three words (examples: plain, specific, candid): `[CONFIRM]`
- Words the founder never uses: `[CONFIRM]`
- Handles and links: X `[CONFIRM]`, LinkedIn `[CONFIRM]`, repo `architgore050/zivon`
- AI disclosure policy (posts or visuals made with AI help): `[CONFIRM: always say / say when asked / say on visuals only]`

## 2. Visual system

### 2.1 Palette (proposed; swap the hex values if a brand already exists) [CONFIRM]
Dark theme is the default; every contrast ratio below was calculated against WCAG's formula.

| Role | Hex | Use | Contrast on #0E1116 |
|---|---|---|---|
| Background | `#0E1116` | canvas | n/a |
| Surface | `#171B22` | cards, code boxes, panels | n/a |
| Text | `#F3F4F6` | headlines, body | 17.2:1 |
| Muted | `#9AA4B2` | labels, sources, secondary text | 7.5:1 |
| Accent | `#5EEAD4` | ONE highlight per image: a number, a keyword, an arrow | 12.8:1 |
| Gap (not done / failed) | `#FF8A7A` | honest-gap items only | 8.3:1 |
| Done | `#86EFAC` | completed items on checklists | 13.5:1 |

Light variant (only when the platform or context needs it): background `#F7F7F5`, ink `#111418` (17.2:1), muted
`#5B6472` (5.6:1), accent `#0F766E` (5.1:1), gap `#B42318` (6.1:1).

Colour rules:
- One accent per image. If two things are highlighted, nothing is.
- The gap colour is reserved for honesty (what is not done). Never use it decoratively.
- Text on accent uses background colour `#0E1116` (12.8:1).
- No gradients, drop shadows, glows, or stock backgrounds. Flat and calm reads as real; polished reads as ad.

### 2.2 Fonts (free, no licence trouble) [CONFIRM]
- Primary (headlines, body, captions): **Inter**, weights 500, 600, 700. Fallback: system-ui, Arial.
- Mono (numbers, file names, code, day counter): **JetBrains Mono**, weights 400, 700. Fallback: Menlo, Consolas.
- Never more than 2 families. No script, no display fonts, no emoji as design elements.

### 2.3 Sizes (on a 1080 px wide canvas; scale proportionally for other sizes)
| Element | Size | Weight | Notes |
|---|---|---|---|
| Hook / big number | 96-140 px | 700 | max 7 words; one idea |
| Headline | 64-80 px | 700 | max 12 words |
| Body | 44-52 px | 500 | max 3 short lines on a card |
| Video caption | 56-72 px | 700 | 3-6 words per line, 2 lines max |
| Label / source / day counter | 32-36 px | mono 400/700 | never below 32 px |
- Minimum text size anywhere: 32 px at 1080 px width. If it will not fit, cut words, not size.
- Line height 1.15-1.3. Sentence case, not ALL CAPS (caps only for the day counter and tiny labels).

### 2.4 Layout
- Margins: 60 px sides, 150 px top, 170 px bottom on vertical canvases; the same 60 px on square and 4:5.
- Keep faces, text, and logos in the central safe area; platform UI covers the top and bottom edges (verify in the
  current composer before export).
- Left-aligned text, 1 column, generous empty space. One focal point per image.
- Formats: 4:5 or 1:1 for images (default 1080x1350), 16:9 for link-style previews, 9:16 for vertical video.

### 2.5 Recurring visual elements
- **Day counter** in the top-left of every image and video: `DAY 01` in mono, accent colour. Same position every day.
- **Scoreboard strip** (optional, bottom): 3-5 tracked numbers in mono, same order every day. Metrics are `[CONFIRM]`.
  Example slots: tests passed, active testers, pieces produced, days to v1. Numbers need a denominator or a
  comparison ("12 of 30"), never a bare brag.
- **Card types** (each is one idea, one focal point):
  1. Number card: one big number, one line of context.
  2. Decision card: `Decision / Tradeoff / Why` in three lines.
  3. Proof card: a cropped screenshot with at most one annotation.
  4. Gap card: what is not done, in the gap colour, with the reason.
  5. Recap card: yesterday in one line, today in one line, tomorrow in one line.
  6. Ask card: the one question or request, nothing else.
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

## 4. Voice and writing
- First person singular. Plain words. Contractions. Short sentences; break any sentence over 20 words.
- Specific over adjectival: numbers, file names, dates, named tools, real quotes.
- State opinions as facts when they are earned by something you did; say "I'm not sure" when you are not.
- No em dashes. No hashtags on X; 0-3 specific hashtags on LinkedIn, at the end.
- Banned words: leverage, unlock, delve, harness, streamline, game-changer, revolutionize, supercharge, seamless,
  cutting-edge, "in today's fast-paced world", "excited to announce", "thrilled", "journey" (unless literal).
- Emojis: none by default. `[CONFIRM]` if the founder's own voice uses them.
- Vary list lengths; avoid mechanical rule-of-three rhythms and "not X, but Y" templates repeated post after post.

## 5. Psychology rules (the subtle part)

### 5.1 Avoid bloat
- One idea per post. If there are two, save one for tomorrow.
- Cut the first sentence and see if the post still works; usually it does. Then cut 20% of what remains.
- Every sentence must add a fact, a feeling, or a turn. Throat-clearing, restatements, and summaries get cut.
- If a post needs more than about 1,300 characters on LinkedIn or one 280-character post on X, it needs either a
  thread/carousel or a smaller idea.

### 5.2 Avoid the "this is an ad" feeling
Readers detect promotion in under a second. The tells, and what to do instead:
| Ad tell | Do this instead |
|---|---|
| Opens with the product name or "Introducing" | Open with a result, a number, or a scene |
| Feature lists, benefit lists | One concrete moment where the thing did something |
| Superlatives (best, fastest, revolutionary) | A measured fact with its limit |
| CTA in the first line; "link in bio" energy | Put any link in a reply or first comment |
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
| Length | 280 chars per post unless the account allows longer; threads for more | about 900-1,300 characters |
| Hook | strongest line first, passes the first-three-words test | first ~140 characters carry the post |
| Links | in a reply | in the first comment |
| Tone | compressed, wry, direct | warmer, story-led, one idea explained |
| Media | proof screenshot or short clip in the hook tweet | one image, short captioned video, or carousel |
| Ask | a reply question | a comment question or a specific network ask |
| Hashtags | none | 0-3, specific, at the end |
Same story, two different posts: never paste the same text on both.

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
- [ ] Visuals: one focal point, one accent, minimum 32 px text, day counter present, readable at 300 px wide
- [ ] Secrets sweep done on the exported files; minors and consent checked
- [ ] Link placement correct for the platform; no hashtags on X
- [ ] A reply plan exists for the first hour

## 11. Open decisions (answer once; then delete this section)
1. One-line description of Zivon and its target reader.
2. Existing brand colours or fonts? (If none, keep section 2 as written.)
3. The 3-5 scoreboard metrics to track daily.
4. The founder's voice samples (3 real posts or messages) and words to never use.
5. AI disclosure policy.
6. Posting time zone, slot, and whether X supports longer posts on the account.
7. Who is the Day 1 test participant, and do they appear in any asset (consent status)?

## 12. Changelog
- v0.1 (Day 1): first version; palette and fonts are proposals.
