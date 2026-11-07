# Security review for LLM, agent, tool, and MCP code

Read this when the diff calls a model, builds prompts, gives a model tools, runs model-generated code, or integrates an MCP server or plugin. These systems add a failure class classic checklists miss: **the model can be instructed by data**.

## The core question: the "lethal trifecta"

An agent is dangerous when one context combines all three:
1. Access to **private data** (files, email, DB, secrets, other users' content)
2. Exposure to **untrusted content** (web pages, emails, issues/PRs, documents, tool outputs, user uploads, other agents' output)
3. A way to **communicate or act externally** (HTTP requests, sending messages, rendering images/links, writing files, running commands, committing code)

If a change creates or widens that combination, it is a **major**, and a **blocker** if it handles real user data with no mitigation. Mitigation means *removing a leg*: strip external egress, drop access to private data for that task, or isolate untrusted content in a context with no tools. Prompt-level "ignore malicious instructions" warnings are not a mitigation; treat them as a speed bump.

## Checklist

**Prompt injection and data/instruction mixing**
- Is untrusted text concatenated into prompts alongside instructions? Is it at least delimited and labeled, and is the model's authority over tools independent of what that text says?
- Indirect injection paths: retrieved docs (RAG), scraped pages, tool results, issue/PR bodies, filenames, commit messages, image/PDF text.
- Markdown/HTML rendered from model output can exfiltrate data via image URLs or links. Is rendering sanitized and are external fetches blocked?

**Excessive agency and tool permissions**
- Does each tool have the narrowest scope (read-only where possible, specific directories, specific hosts, scoped tokens)?
- Destructive or irreversible actions (delete, send, pay, deploy, force-push, grant access) require human confirmation or are impossible by construction.
- Is there an allow-list of commands/paths/domains rather than a deny-list? Shell tools especially.
- Do sub-agents or tools inherit more privilege than the task needs? Is credential use per-task rather than ambient?

**Output handling**
- Model output is untrusted input to everything downstream: never interpolate into SQL, shell, file paths, HTML, or `eval` without the same controls you'd apply to user input.
- Structured-output parsing is strict and failures fail closed; no "best-effort" parse that grants permissions.
- Generated code is sandboxed (no network, no host secrets, resource limits, ephemeral FS) if it is executed at all.

**Secrets and data exposure**
- No API keys, tokens, or system prompts containing secrets in client-side code, logs, traces, analytics, or prompts.
- User data sent to third-party model providers is covered by the project's data policy; PII is minimized/redacted; retention is understood.
- Cross-user leakage: shared caches, shared conversation memory, vector stores without per-tenant filtering.

**MCP servers, plugins, and skills**
- Is the server/plugin from a trusted, pinned source? Treat installing one like adding a dependency with code-execution rights (see supply chain).
- Tool descriptions and tool results are untrusted text that the model reads; a malicious server can embed instructions. Check for over-broad auto-approval settings.
- Remote servers: authentication, transport security, and what data each tool call sends out.

**Abuse and cost**
- Rate limits, per-user quotas, max tokens/steps/tool calls, and timeouts so a loop or hostile user can't run up cost or hang the service ("unbounded consumption").
- Idempotency and loop detection for agents that retry.

**Observability and testing**
- Are tool calls and approvals logged for audit (without logging secrets)?
- Are there adversarial tests or evals: injection strings in retrieved content, attempts to escape the sandbox, tool-misuse attempts?

## Typical findings and levels
| Finding | Level |
|---|---|
| Agent with shell/network + private data reads untrusted web/email/issue content | blocker/major |
| Model output interpolated into SQL/shell/HTML | blocker |
| Tool token is account-wide when task needs one repo/folder | major |
| No confirmation on destructive tool action | major |
| No max-steps/cost cap on agent loop | minor–major |
| Untrusted text unlabeled in prompt (but tools are properly constrained) | minor |

Reference frameworks: OWASP Top 10 for LLM Applications; OWASP guidance on agentic AI threats. Check the current versions when citing them.
