---
name: example-skill
description: <What the skill does, in one or two sentences, third person.> Use when <the situations, user phrasings, and task contexts that should trigger it>. <Add the near-miss wording that should also trigger it, if the model tends to under-trigger.>
license: MIT
compatibility: <Optional. Required tools, packages, network, or client. Delete if none.>
metadata:
  owner: <team-or-person>
  version: "0.1"
---

# <Skill name>

<One paragraph: the goal, the audience, and what "done" looks like. Explain why
this skill exists; the reason generalizes better than a rule list.>

## When to use this

- <Trigger 1, phrased as the user would say it>
- <Trigger 2>
- <Trigger 3>

Do not use it for <out-of-scope task>; use <other skill/tool> instead.

## Preconditions

- <Files, tools, access, or context the agent must have>
- <What to do if a precondition is missing>

## Procedure

1. <First concrete step. Name the exact file/command/API.>
2. <Second step.>
3. <Third step. Point to a reference only if this step needs it:
   read `references/<topic>.md` when <condition>.>
4. <Verification step: run the validator / check the output contract.>

## Output contract

<The exact shape of the result: sections, fields, file names, formats. Prefer a
short template over prose description.>

```markdown
## <Section>
- <Item>
```

## Failure handling

- If <likely failure>, then <specific recovery>.
- If <ambiguous case>, ask the user rather than guessing.
- If <destructive action>, require explicit confirmation.

## Worked example

**Input:** <realistic user request>

**Actions:** <the steps above, compressed>

**Output:** <the shape, with real-looking content>

## Gotchas

- <Environment-specific fact that defies a reasonable assumption>
- <Name mismatch: `user_id` in DB, `uid` in auth, `accountId` in billing>
- <Non-obvious ordering or permission rule>

## References

| File | Read when |
|---|---|
| `references/<topic>.md` | <specific condition> |
| `scripts/<tool>.py` | <specific condition; say it is deterministic> |

## Changelog

- YYYY-MM-DD — v0.1 — initial version.
