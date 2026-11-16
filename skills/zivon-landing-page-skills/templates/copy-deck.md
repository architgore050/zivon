# Copy deck

Every string on the page, in one file, before anything is built. If a string is
not in the deck, it does not ship.

---

## Header

```
Page:          /
Version:       v0.1
Author:
Date:
Locale(s):     EN | हिन्दी | Hinglish
Word count:    <hero>  /  <full page>
```

## 1. The promise

```
One promise (<= 20 words):

Substitution test:  put a competitor's name in it. Still true?   Y / N
                                                   (N is the pass)
Read-aloud test:    say it to a 15-year-old. Would you?          Y / N
```

## 2. Headlines

Five variants, each from a **different** strategy. See
[../references/copywriting-and-microcopy.md](../references/copywriting-and-microcopy.md)
§5 and [hero-variants.md](hero-variants.md).

| # | Strategy | Headline (≤ 9 words) | Proof line it needs | Words that carry it |
|---|---|---|---|---|
| 1 | Outcome | | | |
| 2 | Mechanism | | | |
| 3 | Objection | | | |
| 4 | Tension | | | |
| 5 | Artifact | | | |

```
Chosen for the first build:
Because:
The variant we will test against it (one variable):
```

## 3. Subhead

Three jobs: qualify, specify, de-risk. One or two sentences.

```
Qualify (who / class / subject / language):
Specify (the mechanism the headline left out):
De-risk (the biggest objection, answered in a fact):
```

## 4. CTA

```
Primary label (≤ 4 words, verb + object):
What happens after the click (one sentence):
Friction removed (shown beside the button):
Secondary action (a text link, or "none"):
Final CTA label (identical to the primary):
```

## 5. Section copy

One block per section. The claim is a sentence; the evidence is a thing.

```
### <Section name>
Claim:        <one sentence>
Evidence:     <artifact / source / number>
Body:         <2-3 sentences, or none>
Microcopy:    <if interactive: the states>
```

Repeat for each section in the storyboard.

## 6. Microcopy and states

| Element | State | Copy |
|---|---|---|
| Demo player | default | |
| | playing | |
| | blocked by browser | |
| | offline | |
| | asset missing | (blank = render nothing) |
| CTA | idle | |
| | loading | |
| | error | |
| | rate-limited | |
| Language switch | missing locale | |
| Page | JS off | |
| | empty catalogue | |
| Form (if any) | label / hint / error / success | |

Rules: no "something went wrong"; no dead controls; no spinner where a sentence
would do; no blaming the reader.

## 7. FAQ

Four to eight questions, in the reader's words, each answered in one or two
sentences with a fact.

```
Q1:
A1:

Q2:
A2:

Q3:
A3:
```

Check: is the primary objection in the FAQ, or answered in the body? If it is
only in the FAQ, it is buried.

## 8. Meta

```
<title>            <55-60 chars, the promise + qualifier>
<meta description> <140-155 chars, the promise + the action>
<og:title>         same as title
<og:description>   same as description
<og:image>         the artifact, 1200x630, with alt text
canonical          /
hreflang           en / hi / hi-Latn -> the alternate URLs, or a documented reason
```

The meta description is copy, not a keyword field. It is the page's ad inside a
search result.

## 9. Banned-word pass

Search the deck for each and replace or delete.

```
[ ] leverage / utilise          -> use
[ ] facilitate                  -> run / help / set up
[ ] empower                     -> allow / let
[ ] transform                   -> say what changes
[ ] robust / seamless           -> say what does not break
[ ] journey                     -> delete
[ ] personalised                -> say what is personalised
[ ] interactive                 -> name the interaction
[ ] AI-powered / agentic        -> say what the model does
[ ] revolutionary / next-gen    -> delete
[ ] unlock / supercharge / 10x  -> say the number, or delete
[ ] world-class / best-in-class -> delete
[ ] official / affiliated       -> only with a document
[ ] guaranteed                  -> only if legally true
```

## 10. Multi-language pass

```
EN checked by:
हिन्दी checked by (native reader):
Hinglish checked by (native reader):
Translated as a promise (not word-for-word):   Y / N
`lang` attributes set per locale:              Y / N
Untranslated fallback announced, not silent:   Y / N
```

## 11. Final checks

- [ ] Every claim in the deck appears in the claim ledger with evidence
- [ ] Every number has a definition, a date, and a source
- [ ] Every person has a name, a consent record, and a date
- [ ] No word from §9 survives
- [ ] The hero copy passes the 5-second test with a stranger
- [ ] The headings, read alone, form a sentence
- [ ] Reading level: aim for the plain end (the benchmark correlation, not a rule)
- [ ] The whole deck fits on two screens of paper (if it does not, the page is
      a brochure)
