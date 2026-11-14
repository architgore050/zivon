# Maintenance

A skill is a small piece of software with a prose interface. It rots when the
API it names changes, when the model changes, when the client changes its
discovery rules, or when the source repo disappears. This file is the
after-ship plan.

## 1. Review cadence

| Skill class | Examples | Cadence | Why |
|---|---|---|---|
| Fast-moving | model APIs, pricing, cloud consoles, package managers | **30 days** | Names, limits, and prices change quarterly |
| Product-coupled | a specific client's plugin/skill format | **90 days** or on client release | Discovery paths and frontmatter rules change |
| Stable method | code review, writing, design critique | **6 months** | The method ages slowly; examples still rot |
| Frozen | archived/legacy skill kept for reproducibility | **12 months**, read-only | Confirm it still loads; do not improve |

A skill with no owner and no cadence is already deprecated; mark it.

## 2. Staleness triggers (review immediately)

- The upstream repo is archived, renamed, or transferred.
- A release changes the API, CLI flag, file path, or output format the skill
  names.
- The client changes discovery rules, frontmatter fields, or precedence.
- The model changes enough that the skill's examples or "gotchas" no longer
  reproduce.
- A link in `references/` 404s.
- A registry removes the skill, or its install count collapses.
- A security advisory or malicious-skill report names the source.
- A user reports the skill triggering on the wrong task, or failing to trigger.
- A price/limit/legal fact in the skill passes its "verified on" date.

## 3. What to re-check on every review

```text
[ ] SKILL.md still matches the current task and client
[ ] description still triggers on the intended prompts (run 3)
[ ] every reference link resolves
[ ] every command still runs (or is marked unverified)
[ ] examples still produce the documented shape
[ ] license/provenance block still accurate
[ ] no secrets/PII introduced
[ ] validator passes: python3 scripts/check_skills.py --strict --bundle <path>
[ ] changelog updated with date + change
```

## 4. Versioning and changelog

Use `metadata.version` as a string and a short changelog in the skill README:

```markdown
## Changelog

- 2026-11-14 — v1.1 — retargeted to OpenCode V2 discovery; replaced example.
- 2026-08-02 — v1.0 — initial extraction from the release workflow.
```

Semver is optional but useful: `MAJOR` when the trigger or output contract
changes, `MINOR` when procedure/references change, `PATCH` for typos and links.
Record the upstream commit when the skill is derived from one.

## 5. Trigger monitoring

The description is the part most likely to silently fail. Track:

- **False negatives** — the user asked for the task and the skill did not load.
  Add the phrasing they used to the description.
- **False positives** — the skill loaded for an unrelated task. Narrow the
  description or add a "do not use for…" line in the body.
- **Collisions** — two skills with overlapping descriptions; the agent picks one
  arbitrarily. Merge or disambiguate.

A cheap protocol: keep 5 prompts (3 should trigger, 2 should not) in the skill's
README or `evals/`, and re-run them after any description edit. Record the
result and date. If you have an eval harness, assert on which skill loaded.

## 6. Eval regression

When the skill has checkable output, keep `evals/evals.json` with 2–3 realistic
prompts and assertions. After a change:

1. Run with the new version and the previous version (snapshot it first).
2. Compare pass rate, time, and tokens.
3. Accept the change only if it improves or holds the metric without a large
   cost increase.
4. Record the iteration in a workspace folder, not in the skill itself.

The method is in SRC-003; the short version is: same prompts, with/without (or
old/new), evidence for every PASS, and a delta table.

## 7. Deprecation

When a skill should no longer be used:

1. Set `metadata.deprecated: "true"` and add a one-line reason + replacement at
   the top of `SKILL.md`.
2. Keep the folder for one cycle so existing installs do not break silently.
3. Remove it from the bundle README/index and from any router skill.
4. Archive the repo/tag if you control it; keep the changelog.
5. If it was published to a registry, update or unpublish per the registry's
   rules; record the date.

Do not delete a skill that other skills reference without updating the
references first.

## 8. Source catalog refresh

The catalog in this bundle is a snapshot. Refresh it quarterly:

1. Re-run the "access tested" method for each row; update the status/date.
2. Check the "what did not work" table; a block may have lifted, or a workaround
   may have broken.
3. Add new registries/directories; mark dead ones.
4. Update the trust tier if a source changed ownership or review process.
5. Bump the bundle `metadata.evidence_date` and note the refresh in the README.

Do not silently delete a failed source: the failure is useful evidence.

## 9. Ownership

Every skill needs a named owner (person or team) and a backup. The owner is
responsible for the cadence, the changelog, and responding to reports. A skill
with no owner is a liability; mark it deprecated or delete it.

In this repo, put the owner in `metadata.owner` and in the bundle README.

## 10. Maintenance anti-patterns

- **Silent edits**: changing behavior without a changelog entry.
- **Reference drift**: adding a `references/` file but never mentioning it in
  `SKILL.md`, so it is dead weight.
- **Copy drift**: adapting an upstream skill but never recording the source
  commit, so you cannot diff the next release.
- **Eval deletion**: removing a failing assertion instead of fixing the skill.
- **Zombie skills**: deprecated but still discoverable, with no warning.
- **Refresh theater**: bumping the date without re-running the checks.
