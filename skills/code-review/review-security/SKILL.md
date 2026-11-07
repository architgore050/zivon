---
name: review-security
description: Security lens for code review. Use when reviewing or auditing code that touches authentication, authorization, user input, SQL/shell/HTML/file-path/URL handling, crypto, secrets, sessions, file uploads, deserialization, third-party dependencies, CI/CD or GitHub Actions config, Docker/infra files, or LLM/agent/tool-calling code. Also use for any request mentioning vulnerabilities, OWASP, injection, XSS, SSRF, CSRF, secrets in code, supply chain, prompt injection, or "is this secure". Applies OWASP Top 10:2025 via data-flow tracing rather than keyword matching.
---

# Security Review

Security review is about **attacker-controlled data reaching something powerful**. Checklists help you remember categories, but findings come from tracing: where does untrusted input enter, what does it touch, and what stops it from doing damage?

Findings use the shared format and severity scale from the `code-review` skill. For per-category detail read `references/owasp-2025-checklist.md`; for code that calls LLMs, agents, tools, or MCP servers also read `references/agentic-and-llm.md`.

## Method

1. **Model the change in two sentences.** What new trust boundary, input, privilege, or sensitive data does this diff introduce or alter? If the answer is "none", say so and do only the quick scans below.
2. **Trace sources to sinks.**
   - *Sources*: request params/body/headers/cookies, uploaded files and filenames, webhook payloads, message-queue events, DB rows written by users, env/config, third-party API responses, LLM output, and anything read from a file or URL the user influences.
   - *Sinks*: SQL/NoSQL queries, shell/exec, `eval`/dynamic import, template rendering, HTML output, file-system paths, outbound HTTP (SSRF), redirects, deserializers, logging, regexes, and authorization decisions.
   - For each source→sink path, name what sanitizes, validates, or constrains it. If nothing does, you have a finding. If something does, confirm it's the *right* control for that sink (e.g. escaping for HTML is not escaping for SQL).
3. **Check authorization on every new entry point.** Authentication ("who are you") is usually handled by a framework; authorization ("may *you* touch *this object*") is where bugs live. For every new route, handler, job, or query, ask: is the check present, is it enforced server-side, and does it verify ownership of the specific resource (not just "is logged in")?
4. **Scan the diff for the quick wins** (below).
5. **Calibrate.** State the attack path in one or two sentences (who, with what input, gets what). No plausible path → downgrade or drop. Describe attacks to justify the finding; don't write working exploits.

## Quick scans (do these on every diff that isn't trivial)

- **Secrets**: keys, tokens, passwords, connection strings, private keys, `.env` files, test fixtures with real credentials. Check the *whole diff and new files*, including config, CI, docs, and notebooks. A committed secret is a **blocker** even if "rotated later"; it lives in git history and must be revoked.
- **New dependencies**: does the package exist and is it the one intended (typosquats, hallucinated names)? Is it maintained, pinned via lockfile, and free of install-time scripts that run code? Is the license compatible? Flag dependencies added for trivial functionality.
- **Dangerous APIs**: `eval`, `exec`, `os.system`, `subprocess(shell=True)`, `pickle`/`yaml.load`/unsafe deserializers, `innerHTML`/`dangerouslySetInnerHTML`, string-built SQL, `verify=False`/disabled TLS checks, `Math.random`/`random` for security tokens, MD5/SHA1 for passwords, hard-coded IVs/keys, `chmod 777`, `*` CORS with credentials.
- **Fail-open behavior**: `catch {}` that continues as if authorized, default-allow branches, auth checks that run *after* the side effect, feature flags that default to the unsafe path.
- **Error and log hygiene**: stack traces or internal details returned to clients; secrets, tokens, or PII written to logs; missing logging of security-relevant events (auth failures, permission denials, admin actions).
- **CI/CD and infra**: workflows with `pull_request_target` running untrusted code, third-party actions not pinned to a commit SHA, overly broad `permissions:` or tokens, secrets echoed into logs, containers running as root, public buckets, wildcard IAM.

## Principles to judge fixes by

- **Validate at the boundary, encode at the sink.** Allow-lists beat deny-lists. Parameterized queries beat escaping. Don't invent sanitizers.
- **Deny by default.** New endpoints should be inaccessible until explicitly granted.
- **Least privilege** for tokens, DB users, IAM roles, container capabilities, and CI permissions.
- **Use the platform's primitives** for crypto, sessions, CSRF, and password hashing (argon2/bcrypt/scrypt). Hand-rolled crypto or auth is a **major** by default.
- **Fail closed**, and make failure paths no more informative to attackers than success paths.
- **Defense in depth is minor, not blocker**: a missing second layer only becomes a blocker if the first layer is also absent or bypassable.

## Severity guidance

| Situation | Typical level |
|---|---|
| Reachable injection, auth bypass, IDOR/BOLA, committed secret, RCE, SSRF to internal network | blocker |
| Missing authz on a sensitive-but-not-yet-exposed path, weak crypto for real data, unpinned CI action with write token | major |
| Missing rate limit, verbose error, defense-in-depth gap, outdated-but-not-vulnerable dependency | minor |
| Theoretical issue needing attacker capabilities they already have | drop or `question` |

## Output additions

After the findings, add a short **Security notes** block when relevant: assumptions made (e.g. "assumed the gateway enforces auth"), areas you couldn't verify (e.g. generated clients, infra defined elsewhere), and a recommendation for follow-up tooling (SAST, dependency audit, secret scanning) if the repo lacks it, without pretending the review replaces those tools.
