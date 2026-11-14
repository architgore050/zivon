# Skill audit — `<candidate name>`

Copy this file into the workspace (not into the skill) and fill it in. One audit
per candidate. Date every claim; label evidence `confirmed`, `likely`, or
`suspected`.

## Identity

| Field | Value |
|---|---|
| Candidate | `<name>` |
| Source URL | `<url>` |
| Author / org | `<name>` |
| Version / commit | `<tag or SHA>` |
| Retrieved | `<YYYY-MM-DD>` |
| Registry entry | `<skills.sh / MCP registry / awesome list / direct>` |
| License | `<SPDX or "none found" or "see LICENSE.txt">` |
| Install command | `<exact command>` |
| Install count / stars | `<number + source>` |
| Last upstream commit | `<date>` |

## Hard gates

| Gate | Pass? | Evidence |
|---|---|---|
| License permits the intended use | ☐ | |
| No malicious/unsafe behavior (scripts reviewed) | ☐ | |
| Identity verifiable (install resolves to reviewed repo) | ☐ | |
| No prompt injection / override / concealment | ☐ | |
| Legal and policy compliant | ☐ | |

**Any unchecked gate = reject.** Do not average gates into the score.

## Score (0–2 each)

| # | Dimension | Score | Evidence (what you opened/ran) |
|---|---|---|---|
| 1 | Source trust | | |
| 2 | Trigger fit | | |
| 3 | Body quality | | |
| 4 | License and provenance | | |
| 5 | Security | | |
| 6 | Maintenance | | |
| 7 | Compatibility | | |
| 8 | Testability | | |
| 9 | Prompt-injection risk | | |
| 10 | Adaptation cost | | |
| | **Total / 20** | | |

## Trigger test

| Prompt (real user phrasing) | Should trigger? | Did it? | Notes |
|---|---|---|---|
| | yes | | |
| | yes | | |
| | no (near-miss) | | |

## Files reviewed

| File | Read? | Notes |
|---|---|---|
| `SKILL.md` | ☐ | |
| `references/*` | ☐ | |
| `scripts/*` | ☐ | every script read line by line |
| `assets/*` | ☐ | |
| other | ☐ | |

## Security notes

- Dangerous patterns found:
- Network/file/credential access:
- Hidden characters/binaries:
- Sandbox result:
- Residual risk:

## Decision

- **Decision:** install / adapt / build / reject
- **Reason (one paragraph):**
- **If install/adapt:** pin `<commit>`, record hash `<sha256>`, attribution text
  added to `<file>`.
- **If adapt:** changes made:
  1.
  2.
- **If build:** what prior art was reused as method (not expression):
- **Follow-up:** owner, review date, open questions.

## Reviewer

- Name:
- Date:
- Confidence in this audit: high / medium / low (why):
