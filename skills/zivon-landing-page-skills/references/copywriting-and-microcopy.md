# Copywriting and microcopy

Words are the product on a landing page. The layout decides whether they are
read; the words decide whether they are believed.

`[E]` marks a claim backed by research or a published standard, `[P]` a
practitioner rule with a good track record but no controlled test.

## 1. One promise

A landing page has **one promise**, and every section is a consequence of it.

Find it with the "so what" ladder. Write the honest sentence, then ask "so what"
three times, and stop when the answer is about the reader's life rather than the
product's features:

```
We generate interactive Physics lessons.
  so what?  They have simulations you can move.
  so what?  You can see what a static diagram cannot show.
  so what?  You can finally see why the ray bends, instead of memorising that it does.
```

The promise is the last rung. The first rung is the product description and
belongs in the footer, not the H1.

**The substitution test:** replace your product's name with a competitor's. If
the promise still holds, it is a category statement, not a promise.

## 2. Specificity

Specificity is the cheapest credibility available, and it is the first thing
drafting removes. The ladder, weakest to strongest:

| Level | Example | Problem |
|---|---|---|
| Adjective | "powerful, personalised learning" | true of every product, therefore meaningless |
| Category noun | "an AI tutor for Physics" | describes the shelf, not the thing |
| Named mechanism | "a voice tutor that reads the page you are on" | a competitor cannot say it without building it |
| Number + unit | "20-second voice turns, on a 2 GB phone" | checkable |
| Artifact | a screenshot of the actual anchored answer | undeniable |

Move every claim at least one rung up. A claim that cannot move is a claim you
cannot make.

## 3. Verbs

- **The reader does the verb.** "See the ray bend", not "the system renders the
  refraction". The product is the guide, not the hero `[P]`.
- **One verb per sentence.** Two verbs usually means two sentences were
  compressed and the second one is doing the real work.
- **Active voice.** "You need a chapter", not "a chapter is required" — active
  voice is shorter and clearer, and plain-language guidance puts it first for
  exactly that reason `[E]`.
- **No nominalisations.** "decide" not "make a decision"; "explain" not "provide
  an explanation". Words ending in *-ion* and *-ment* lengthen sentences without
  adding information `[E]`.

## 4. Rhythm

Landing-page copy is read in glances, so it has to survive being half-read.

- **Vary sentence length deliberately.** Three medium sentences in a row read as
  a wall; one short sentence after two long ones reads as a conclusion.
- **Front-load.** The first two words of a line carry most of the attention in
  scanning `[E]`. Put the information-carrying word first, not the throat-
  clearing one ("Because the diagram cannot move, …" not "One of the things
  that we noticed is that…").
- **One idea per sentence.** If a sentence needs a semicolon, it is two
  sentences.
- **Working limits** (not research findings, but they catch most drafts):
  headline ≤ 9 words, subhead ≤ 25 words, CTA ≤ 4 words, a paragraph ≤ 3
  sentences, an FAQ answer ≤ 2 sentences.
- **The read-aloud test.** Read the hero out loud. If you run out of breath, or
  if you would never say it to a person, rewrite it. This test also catches the
  copy that reads well silently and dies when spoken — which matters for a
  voice-first product.

## 5. Headline formulas

Six strategies, not six wordings. A hero test compares strategies; a test
between synonyms teaches nothing.

| # | Strategy | Shape | It wins when | Its risk |
|---|---|---|---|---|
| 1 | **Outcome** | the thing the reader gets | the outcome is specific and desired | it can sound like every competitor |
| 2 | **Mechanism** | how it is done, uniquely | the mechanism is the differentiator | it can be opaque to a cold reader |
| 3 | **Objection** | the doubt, answered in the headline | the doubt is the actual blocker | it can sound defensive |
| 4 | **Tension** | the thing that is wrong, named | the reader recognises it instantly | it can feel negative for a child audience |
| 5 | **Artifact** | point at the thing itself | the artifact is remarkable on sight | it needs the artifact to be real |
| 6 | **Category re-frame** | "not X, but Y" | the category is crowded and misread | it picks a fight you must win |

For each headline, write the **proof line** that must sit near it. A headline
without a nearby proof is a slogan.

**Worked set for Zivon** (draft, not approved copy — see
[../examples/zivon-landing-brief.md](../examples/zivon-landing-brief.md)):

| # | Headline | Proof line it needs |
|---|---|---|
| 1 | See why the ray bends, not just that it does. | the simulation, moving |
| 2 | Ask the page. Out loud. In Hinglish. | a real 20 s turn + transcript |
| 3 | You read it. You nodded. You still can't do the numerical. | the worked step, on screen |
| 4 | The diagram in your book cannot move. This one can. | the same diagram, interactive |
| 5 | Class 10 · Light. Ask it anything about this paragraph. | the anchored answer, highlighted |
| 6 | Not a chatbot with a textbook stapled on. | the review gates + citations |

Note that none of them say "AI". That is deliberate: "AI" is the category, not
the promise, and it triggers the "another wrapper" objection before the page has
earned a hearing.

## 6. The subhead

The subhead has three jobs and no fourth:

1. **Qualify** — who this is for (class, subject, language).
2. **Specify** — the mechanism or the scope the headline left out.
3. **De-risk** — the one fact that removes the biggest objection ("free to
   start", "no account", "works on a 2 GB phone").

It is not a second headline, not a paragraph, and not a list. One sentence, two
at most.

## 7. CTA copy

A button label is an instruction, not a mood.

```
[verb] + [object] + [qualifier if it removes a doubt]
Open a chapter
Try Class 10 · Light
Ask your first doubt — free
Start with one chapter, no account
```

Rules:

- **Name the outcome, not the mechanism.** "Open a chapter", not "Submit".
- **Keep the same words everywhere.** The hero CTA and the final CTA are the same
  action and must read identically; changing the label makes the reader re-decide.
- **No pressure verbs.** "Grab", "Unlock", "Claim your spot" are urgency
  costumes.
- **No vague verbs.** "Get started" tells the reader nothing about what happens
  next. Say what the first screen after the click contains.
- **State the friction removed, if any.** "No account" beside the button
  outperforms "Sign up free" because it answers the objection at the point of
  action.
- **One primary button per screen.** A secondary action is a text link, visually
  subordinate, and never the same weight.

## 8. Microcopy: the states nobody writes until they ship

Every interactive element on the landing page has states, and each state has
one job: tell the reader what happened and what they can do.

| Element | State | Copy contract |
|---|---|---|
| Demo player | **default** | say what will play and how long: "20 seconds, Hinglish, with transcript" |
| | **playing** | the transcript advances; a stop control is always visible |
| | **blocked by browser** | "Your browser blocked the audio. Play it here." — never a silent failure |
| | **offline** | "You're offline. The transcript is below." |
| | **no audio asset** | render no player at all; show the transcript. Never a dead control |
| Signup / trial | **idle** | say what happens after the click, in one line |
| | **loading** | a short, honest line; no fake progress |
| | **error** | what failed, what to do, and a way to continue without the account |
| | **rate-limited** | when it resets, in plain time ("resets at midnight") |
| Language switch | **untranslated** | never fall back silently; say the page is English-only and link the reason |
| Page | **JS off** | all copy, all prices, all objections present; the demo replaced by its transcript |
| | **empty catalogue** | say why it is empty and what will fill it; never a blank grid |

Rules that apply to all of them:

- **No error that only says "something went wrong".** Name the thing.
- **Never a dead control.** If the asset or the feature is not there, do not
  render the affordance.
- **Never a spinner where a sentence would do.** Landing-page waits are short;
  a spinner adds anxiety without information.
- **Never blame the reader.** "That link has expired" beats "You entered an
  invalid link".

## 9. Words to avoid, and what to write instead

Drawn from GOV.UK's published list of words that confuse readers `[E]`, plus the
vocabulary this category overuses.

| Avoid | Write |
|---|---|
| leverage, utilise | use |
| facilitate | run, help, set up (say which) |
| empower | allow, let |
| transform | say what changes |
| robust, seamless, frictionless | say what does not break, or delete |
| deliver (an outcome) | make, give, show |
| journey | (delete; say the steps) |
| personalised learning journey | say what is personalised and how |
| AI-powered | say what the model does that a page cannot |
| revolutionary, next-generation, cutting-edge | (delete; no replacement exists) |
| unlock, supercharge, 10x | say the number or delete |
| world-class, best-in-class | (delete) |
| hub, portal, one-stop shop | the page or the product's real name |

And the category-specific ones, which are the most damaging because they are the
most common:

- **"Personalised"** — say *what* is adapted: the explanation, the difficulty,
  the language. Otherwise it means "we have a user table".
- **"Interactive"** — name the interaction: a slider, a simulation, a question
  with feedback.
- **"Agentic", "reasoning", "frontier model"** — internal vocabulary. The reader
  cares what they can do, not how it is built.
- **"For every student"** — a coverage claim. If it is not true for Class 11, it
  is false.

## 10. No fake urgency

Urgency is only honest when it is structural: a real deadline, a real cohort, a
real capacity limit, enforced by the system.

| Allowed | Not allowed |
|---|---|
| "Class 10 · Light is live now; Class 11 lands in January" (a real date) | "Limited time!" with no end date |
| "Free while in beta" (a real policy) | a countdown that resets on reload |
| "This chapter is still being written" (a real state) | "Only 3 seats left" with no cap |
| A dated notice | "Hurry" |

Unsupported urgency, invented scarcity, and fake social proof are not merely
tasteless: regulators treat them as deceptive practices and have taken action
against them `[E]`. See [proof-and-trust.md](proof-and-trust.md).

## 11. English, Hindi, Hinglish

The product supports three languages; the landing page must show, not claim,
that it does.

- **Show a real sample in the first screen.** A language badge is a promise; one
  line of actual Hinglish copy is proof.
- **Translate the promise, not the words.** A literal translation of an English
  headline usually produces something that reads like an advertisement for a
  different product. Write the headline in each language from the reader's
  problem.
- **Hinglish is a language, not a transliteration.** Code-mixing follows real
  speech patterns (the technical noun stays in English, the framing is Hindi).
  Get a native reader to check it; a model-drafted Hinglish line reads plausibly
  and wrongly.
- **Never silently fall back.** If a locale is missing, say so on the page. A
  silent English fallback teaches the reader that the language control is a
  decoration.
- **Set `lang` correctly** on each locale's content, including `hi-Latn` for
  Hinglish, so screen readers and fonts behave.

## 12. The word-level value test

Applicable to every string on the page, one at a time:

1. Read the sentence with the adjective removed. Did anything change? Then the
   adjective was decoration.
2. Read it with the sentence removed. Did the reader lose a reason to believe,
   a reason to act, the ability to act, or the answer to an objection? If not,
   delete the sentence.
3. Read it aloud as if to a 15-year-old you like. Would you say it? If not,
   rewrite it.

(This is the third pass of the value-addition test in `SKILL.md`; it removes more
words than the other two combined.)
