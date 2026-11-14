# Content review report

Copy this into the review comment. Replace every angle-bracket field; delete sections the PR does not touch, but keep "Not reviewed" and the verdict.

```markdown
## Review: <branch / PR title>

**Verdict:** Approve | Approve with comments | Request changes
**Summary:** <2–3 sentences: what the artifact is, its overall quality, the single most important issue.>
**Lenses applied:** content-quality, <implementation, tests, security, …>
**Skipped:** <lens>: <reason>

### Artifact and stage map

| Field | Value |
|---|---|
| Artifact class | lesson page / block pack / check set / translation / narration / catalogue / prompt-checker |
| Artifact path | `<path or run id>` |
| Pipeline stage(s) | `<00-ingest … 12-narration>` |
| Gate that approved it | `<03-check / 07-perf / 09-review / 10b-transcheck / 11-link>` |
| Contract read | `<docs/...>` |
| Reference compared | `<page / golden / expected.json>` |

### Evidence run

| Check | Command | Result |
|---|---|---|
| Unit / integration | `python -m unittest discover -s testing/content_factory/unit -t .` | `<N/N OK>` |
| Translation / narration | `python -m unittest discover -s testing/translation -t .` | `<N/N OK>` |
| Frontend shell | `python -m unittest discover -s testing/frontend -t .` | `<N/N OK>` |
| Evals smoke | `python -m evals run --suite smoke --mock` | `<PASS / run id>` |
| Regression diff | `python -m evals diff --prev <id> --curr <id>` | `<no regression / details>` |
| Lint / format | `ruff check . && ruff format --check .` | `<clean>` |
| Spec hygiene | `python3 scripts/check_specs.py` | `<clean>` |
| Page walkthrough | `<360 px, JS off, keyboard, console>` | `<result>` |

### Rubric

| Dimension | Score (0–3) | Evidence |
|---|---:|---|
| Grounding and factual accuracy | <0–3> | <one sentence> |
| Check integrity | <0–3> | <one sentence> |
| Curriculum coverage and structure | <0–3> | <one sentence> |
| Language and localization | <0–3> | <one sentence> |
| Technical page integrity | <0–3> | <one sentence> |
| Evidence and eval coverage | <0–3> | <one sentence> |
| **Total** | **<0–18>** | <ready / ship with debt / request changes / do not publish> |

The highest-leverage change: <the one change that would raise the lowest dimension the most>.

### Blockers

- `[blocker][content-quality][confirmed] <path>:<line or item id>: <issue>.`
  Why it matters: <learner or publish consequence>.
  Fix: <specific change + the stage/check that should prevent recurrence>.

### Major

- `[major][content-quality][confirmed] <path>:<line or item id>: <issue>.`
  Why it matters: <consequence>.
  Fix: <specific change>.

### Minor and nits

- `[minor][content-quality][likely] <path>:<line>: <issue>.`
  Why it matters: <consequence>.
  Fix: <specific change>.

- `nit: <taste-level point with no learning/claim impact>.`

### Questions

- `[question][content-quality][suspected] <path>:<line>: <what you need to know and the specific input that worries you>.`

### What's good

- <Something specific worth repeating: a clear explanation, an honest locale flag, a well-grounded item, a useful test.>

### Coverage

| Area | Inspected | Result |
|---|---|---|
| Blocks / checks | <all / N of M, stratified by …> | <pass / findings> |
| Answer keys | <all> | <pass / findings> |
| Citations / source claims | <all factual blocks / N traced> | <pass / findings> |
| Locales | <en, hi, hi-Latn> | <pass / findings> |
| Diagrams / simulations | <all / N> | <pass / findings> |
| Narration | <all speakable blocks / N> | <pass / findings> |
| Links / catalogue / sitemap | <all> | <pass / findings> |
| Accessibility / 360 px / JS off | <surfaces> | <pass / findings> |
| Perf / console | <profile / page> | <pass / findings> |

### Content debt

| Finding | Severity | Artifact | Owner | Reproduction | Target |
|---|---|---|---|---|---|
| <finding> | <major/minor> | `<path>` | <workstream/person> | <how to see it> | <release/follow-up> |

### Not reviewed / assumptions

- <What you did not open, generate, listen to, or verify; why.>
- <Assumptions made (for example, the source pack was treated as authoritative).>
- <Pre-existing published defects reported but not blocking this PR.>
```

## Verdict rules

- Any **blocker** → Request changes.
- **Major** only → Request changes unless the owner explicitly accepts it as logged debt with artifact, owner, and reproduction; factual errors, wrong keys, off-chapter teaching, and false claims never qualify.
- Otherwise → Approve, with comments if there are minors worth reading.
- If the PR is content-only, say whether the approval covers the **content** only or the code path too.
- Always state what you did not review, so the approval is not read as broader than it is.

## Finding format reminder

```
[severity][content-quality][confidence] path:line or item id: Issue in one sentence.
Why it matters: the concrete learner or publish consequence.
Fix: the specific change, plus the stage/check that should prevent recurrence.
```

Severity: `blocker`, `major`, `minor`, `nit`, `question`, `praise`.
Confidence: `confirmed` (opened/recomputed), `likely` (strong reading), `suspected` (a question, not an accusation).
