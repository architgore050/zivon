# Evaluation rubric

A scored way to decide whether a candidate skill (or MCP server, prompt pack,
or plugin) is worth installing, adapting, or rejecting. Score **0–2** per
dimension: `0` = fails/unknown, `1` = partial/fixable, `2` = good. Ten
dimensions, 20 points max, plus hard gates that override the total.

Use [../templates/skill-audit.md](../templates/skill-audit.md) to record a real
audit. Date every score: registries and repos change.

## Hard gates (check before scoring)

Any of these is an automatic **reject**, regardless of score:

1. **No usable license** for the intended use (copying/adapting), and the
   author cannot be reached.
2. **Malicious or unsafe behavior**: credential access, exfiltration, hidden
   instructions, destructive commands, obfuscated payloads, or a script you
   cannot explain.
3. **Unverifiable identity**: install command resolves to a different repo than
   the one reviewed, or the repo/author cannot be identified.
4. **Prompt injection that overrides the user or the harness**: instructions to
   ignore prior instructions, conceal actions, or fetch and execute remote
   content.
5. **Illegal or policy-violating content** (stolen data, bypass instructions,
   regulated advice presented as authoritative).

If a gate is uncertain, treat it as failed until verified. "Unknown" is not a
pass.

## The ten dimensions

### 1. Source trust (0–2)

| Score | Test |
|---|---|
| 2 | Official spec/docs or first-party vendor repo; structured registry entry; author identifiable; repo history and releases |
| 1 | Known community author or curated list; verifiable repo but thin history |
| 0 | Anonymous gist, aggregator scrape, social post, or a repo whose popularity does not match its age/history |

Verify, do not infer: open the repo, read the README, check the license file,
check `pushed_at`.

### 2. Trigger fit (0–2)

| Score | Test |
|---|---|
| 2 | Description names the task and the situations the user will actually be in; it would beat competing skills on those prompts |
| 1 | Related but needs rewriting; may fire on the wrong prompts |
| 0 | Description is generic ("helps with documents") or describes a different task |

Test with 3 real prompts: one obvious, one phrased casually, one near-miss that
should **not** trigger. A skill that fires on the near-miss is a 1 at best.

### 3. Body quality (0–2)

| Score | Test |
|---|---|
| 2 | Goal + procedure + output contract + gotchas + one worked example; specific to the domain; no filler |
| 1 | Usable after edits; missing contract or gotchas; some generic advice |
| 0 | Vague, contradictory, or mostly restates what the model already knows |

The best signal: does it contain knowledge the model would get wrong without
it? Environment-specific gotchas are the highest-value content.

### 4. License and provenance (0–2)

| Score | Test |
|---|---|
| 2 | Clear license compatible with the intended use; author, source URL, commit/date recorded |
| 1 | License clear but attribution/notice requirements need work; provenance partial |
| 0 | No license, conflicting licenses, or provenance unrecordable |

No license means **no copying or adaptation** beyond reading for ideas. See
[provenance-and-licensing.md](provenance-and-licensing.md).

### 5. Security (0–2)

| Score | Test |
|---|---|
| 2 | Instructions only; no scripts, or scripts read line-by-line and sandboxed; no network/credential access; no injection patterns |
| 1 | Scripts present but explainable and sandboxable; minor risky patterns; needs review before use |
| 0 | Obfuscation, credential/env access, exfiltration, `curl \| bash`, hidden instructions, unexplained binaries |

Scripts are the main risk: bundled scripts were 2.12× more likely to contain
vulnerabilities in a 42k-skill study, and script-based injections outperformed
text injections by ~30 percentage points in Skill-Inject. See
[security-and-prompt-injection.md](security-and-prompt-injection.md).

### 6. Maintenance (0–2)

| Score | Test |
|---|---|
| 2 | Commit within ~90 days, issues answered, releases/tags, no archived flag, CI/tests |
| 1 | Active within ~1 year, some issues unanswered, no releases |
| 0 | Archived, abandoned, or last commit > 1 year ago with no fork maintaining it |

For fast-moving domains (models, APIs, prices), tighten "recent" to 30–60 days.
A dead skill is worse than no skill because it encodes stale instructions.

### 7. Compatibility (0–2)

| Score | Test |
|---|---|
| 2 | Spec-compliant `SKILL.md`, portable frontmatter, no client-specific assumptions, documented client support |
| 1 | Works in one client; porting needs path/tool edits |
| 0 | Undocumented custom format, depends on unavailable tools, or conflicts with the host agent's rules |

Check: name matches directory, description length, relative links, tool names
(`Read`/`Bash` vs `@skill`), and whether it assumes a specific sandbox.

### 8. Testability (0–2)

| Score | Test |
|---|---|
| 2 | Ships evals/assertions or a validator; outputs are checkable; a baseline comparison is possible |
| 1 | Manual verification possible; no tests |
| 0 | No way to tell whether it worked |

Prefer skills with `evals/evals.json`, a validation script, or a deterministic
output contract. If none, write 2–3 assertions yourself before adopting.

### 9. Prompt-injection risk (0–2)

| Score | Test |
|---|---|
| 2 | No instruction that could override the user/harness; no remote fetch-and-execute; no concealment language |
| 1 | Aggressive tone or broad "always/never" rules that could conflict with host rules; review needed |
| 0 | Concealment, override, exfiltration, or "run this without asking" patterns |

This is separate from "security" (scripts) because instruction-level attacks
survive static scanning and are the hardest to detect. Score 0 on any
concealment or override language.

### 10. Adaptation cost (0–2)

| Score | Test |
|---|---|
| 2 | Drop-in: paths, tools, tone, and examples already fit |
| 1 | Moderate edits: rewrite examples/references, adjust tools, keep method |
| 0 | Rewrite: the method is wrong for the harness or the license forbids changes |

Estimate in hours, not vibes: a 2 is <30 min, a 1 is <half a day, a 0 is more
than writing from scratch.

## Decision

| Total | Gates | Decision |
|---|---|---|
| 16–20 | all pass | **Install**. Pin commit, record provenance, sandbox trial, then adopt |
| 11–15 | all pass | **Adapt**. Keep license/attribution; record changes; re-run evals |
| 6–10 | all pass | **Build** a smaller skill for your 20%; link the original as inspiration |
| 0–5 | any | **Reject** |
| any | any gate fails | **Reject** (or escalate to a human) |

Two nuances:

- A high total with a `0` on license or security is still a reject. The gates
  exist because those failures are expensive and sometimes irreversible.
- A low total can still be useful as **prior art**: read it, cite it, write your
  own. That is not "adapting" and does not require a derivative license, but it
  does require not copying expression.

## Scoring discipline

- **Label evidence**: `confirmed` (you ran/opened it), `likely` (strong reading),
  `suspected` (a hunch). Put the label next to each score in the audit.
- **Score the artifact, not the author.** A famous author's abandoned repo is
  still abandoned.
- **Do not average away a gate.** One zero on license/security is decisive.
- **Re-score after sandbox testing.** Real behavior beats README claims; a
  candidate that looked like a 2 on trigger fit may be a 1 once it fires on the
  wrong prompts.
- **Keep the audit.** The next agent should not repeat the work; a dated audit
  is also the evidence that the decision was deliberate.

## Worked example (real candidates, 2026-11-14)

| Dimension | `anthropics/skills@skill-creator` | Random "physics tutor" skill (106 installs) |
|---|---|---|
| Source trust | 2 (Anthropic repo, 194k stars) | 1 (community repo, thin history) |
| Trigger fit | 2 (creating/improving skills, evals) | 1 (tutoring, but not curriculum-specific) |
| Body quality | 2 (interview → draft → evals → iterate) | 1 (generic tutoring advice) |
| License | 1 (no repo license; per-skill `LICENSE.txt`) | 1 (check repo) |
| Security | 2 (instructions + scripts; reviewed) | 1 (unknown scripts) |
| Maintenance | 2 (pushed 2026-11-06) | 1 (recent but small) |
| Compatibility | 1 (Claude-centric subagent flow) | 2 (simple `SKILL.md`) |
| Testability | 2 (ships evals + scripts) | 0 (none) |
| Injection risk | 2 | 1 (unreviewed) |
| Adaptation cost | 1 (port subagent steps) | 1 (rewrite for Physics) |
| **Total** | **16 → install/adapt** | **10 → build** |

The example shows the rubric doing its job: the popular, well-maintained skill
wins on evidence, but still needs license and porting work; the niche skill is
not rejected for being small, it is rejected because it adds nothing the model
does not already know.
