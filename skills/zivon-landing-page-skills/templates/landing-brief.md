# Landing brief

Copy this file into the PR. It is one page, and it is written before anything
else. If a field cannot be filled, the page is not ready to be designed.

---

## Header

```
Page:            /                        (or the campaign URL)
Version:         v0.1
Author:
Date:
Status:          draft | review | approved
Frozen spec:     REQUIREMENTS.md §10.1 · FEATURE-MAP.md PUB-01
Doctrine:        docs/frontend/design-doctrine.md §1-§9 (§10 excluded)
```

## 1. The four framing sentences

Answer in one sentence each, no more.

```
Who lands here, and how they got here:
What they already believe when they arrive:
The single action this page exists to produce:
What would have to be true for them to take it:
```

If the fourth line is empty, stop. The page has no argument yet.

## 2. The reader

```
Reader (one person, one entrance):
Awareness stage:      unaware | problem | solution | product | most
Honest emotion:       <one word>
Must not exploit:     <the specific appeal we are refusing>
Language(s) on this page:  EN | हिन्दी | Hinglish
Device assumption:    360 px low-end Android, shared connection
```

## 3. The promise

```
One promise (the "so what" ladder's last rung):
Substitution test:  swap in a competitor's name - does the promise still hold?
                    (if yes, it is a category statement, rewrite it)
```

## 4. The action

```
Primary action:            <event name>
Button label:              <verb + object>
What happens after click:  <one sentence, exactly what the reader sees>
Friction removed:          <no account | free | no app install | ...>
Secondary action:          <a text link, or "none">
```

Exactly one primary action. A second one is a decision the page declined to
make.

## 5. Proof available today

List only what exists now. Not what launches next month.

```
Artifact 1:      <what it is>            <where it lives>       <owner>
Artifact 2:
Source/citation:
Dated number (with definition):
Real user quote (named, consented, dated):   <or "none yet">
```

If this section is empty, the page is not ready: build the proof first.

## 6. What we are refusing

Tick each, and note the specific sentence that was tempting.

- [ ] Fear of failing boards
- [ ] Shame / comparison / ranking
- [ ] Parental disappointment
- [ ] Scarcity or a countdown that is not enforced
- [ ] A testimonial that is not real, named, dated and consented
- [ ] "Official", "affiliated", "certified", "recommended" without a document
- [ ] A capability that is not shipped
- [ ] A privacy claim the code does not implement
- [ ] Borrowed authority ("IIT-designed", "research-backed" with no source)

```
The temptation we refused, and why:
```

## 7. Constraints

```
Sections required by the frozen spec:  top bar · hero · real 20 s Hinglish demo ·
                                       live mini-sim · how it works · syllabus strip ·
                                       practice/test-series block · privacy promise ·
                                       founder/build-in-public note · FAQ · footer
Sections we propose to cut or merge (with reason):
Sections we propose to add (with the objection they answer):
Compliance copy that must appear or be linked:  docs/compliance/notices.md
```

Changing the frozen list is a decision, recorded — not a silent edit. If the
brief proposes a different order, say so here and cite the argument rule it
serves (`page-anatomy.md` §4). The practice/test-series block is a frozen
section: merging it into Coverage is a proposal for the founder, not a default.

## 8. Success

```
Primary metric:      <event> / <denominator> over <window>
Baseline:            <number or "none - first measurement">
Target:              <what would count as working>
Qualitative tests:   five-second test (n=5), sceptic read (n=2), dates
Decision rule:       <what result means ship / iterate / revert>
```

## 9. Open questions for the founder

List them; do not guess the answers.

```
Q1:
Q2:
Q3:
```

## 10. Sign-off

```
Brief reviewed by:            <name>  <date>
Storyboard approved:          <name>  <date>
Copy deck approved:           <name>  <date>
Final visual verdict:         <founder>  <date>   (required before a product PR)
```
