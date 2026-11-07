# OWASP Top 10:2025: what to look for in a diff

Contents: A01 Access Control · A02 Misconfiguration · A03 Supply Chain · A04 Cryptography · A05 Injection · A06 Insecure Design · A07 Authentication · A08 Integrity · A09 Logging · A10 Exceptional Conditions · API-specific · Web-specific

Use as a memory aid after you've traced sources to sinks, not as a substitute for tracing. (SSRF was folded into A01 in the 2025 edition.)

## A01 Broken Access Control (includes SSRF)
Look for:
- Handlers that fetch a record by user-supplied ID without scoping to the caller (`WHERE id = ?` instead of `WHERE id = ? AND owner_id = ?`): IDOR / BOLA.
- Authorization done only in the UI or client; missing server-side check on a new route, GraphQL resolver, RPC method, background job, or admin action.
- Role checks using client-supplied claims; privilege fields (`role`, `is_admin`, `tenant_id`) settable via mass assignment.
- Multi-tenant queries missing the tenant filter; caches keyed without tenant/user.
- Path traversal (`../`) in file reads/writes/downloads; forced browsing to unlinked endpoints.
- **SSRF**: server fetches a user-supplied URL (webhooks, image fetch, import-from-URL, PDF render). Require allow-listed hosts/schemes, block link-local/metadata/private ranges (e.g. 169.254.169.254), re-validate after redirects and DNS resolution.
- Open redirects after login; CORS reflecting arbitrary origins with credentials.
Good: central policy layer, deny-by-default, object-level checks next to data access, tests for "user A cannot read user B".

## A02 Security Misconfiguration
- Debug mode, verbose errors, default credentials, sample endpoints, directory listing enabled.
- Missing/loosened security headers (CSP, HSTS, X-Content-Type-Options, frame protections), permissive CORS.
- Cloud/infra: public storage, `0.0.0.0/0` ingress, wildcard IAM, containers as root/privileged, secrets in env of images, unauthenticated admin/metrics ports.
- XML parsers with external entities enabled; framework features left on that the app doesn't need.
Good: secure defaults, config validated at startup, environment parity, minimal surface.

## A03 Software Supply Chain Failures (new/expanded in 2025)
- New or bumped dependencies: verify the name is exactly the intended package, publisher and maintenance are credible, version is pinned via lockfile, no suspicious install/postinstall scripts.
- AI-suggested package names that may not exist or may be squatted.
- CI: actions/orbs/images referenced by mutable tag (`@main`, `:latest`) rather than commit SHA/digest; `curl | sh` installs; build steps that fetch unpinned artifacts; secrets exposed to PRs from forks; overly broad `GITHUB_TOKEN` permissions.
- Lockfile drift or deleted lockfile; dependencies pulled from git branches or unofficial registries; vendored code with no provenance.
- Missing SBOM/audit step where the project otherwise has one.
Good: pinned and reviewed updates, minimal deps, provenance/signing where practical, `npm audit`/`pip-audit`/`cargo audit`/Dependabot in CI.

## A04 Cryptographic Failures
- Plaintext or weakly protected sensitive data at rest/in transit; HTTP where HTTPS is needed; disabled certificate verification.
- Passwords hashed with fast hashes (MD5/SHA-1/SHA-256 without KDF) instead of argon2id/bcrypt/scrypt; missing per-user salt (handled by proper libs).
- Home-grown crypto; ECB mode; static/hard-coded keys or IVs; nonce reuse; non-CSPRNG randomness for tokens/reset links.
- Secrets compared with `==` (use constant-time comparison); JWTs with `alg: none`, unchecked `alg`, or missing expiry/audience checks.
- Keys stored with the data they protect; no rotation path.

## A05 Injection
- SQL/NoSQL/LDAP/GraphQL built via string concatenation or f-strings; ORMs' raw escape hatches with interpolation.
- OS command injection (`shell=True`, backticks, `exec` with concatenated input); argument injection (user value starting with `-`).
- XSS: unescaped output in HTML/JS/attribute/URL contexts, `innerHTML`, `dangerouslySetInnerHTML`, `v-html`, template `|safe`; Markdown rendering without sanitization.
- Template injection, header/CRLF injection, log injection, expression-language injection, regex injection/ReDoS.
- Deserialization of untrusted data (`pickle`, Java native serialization, unsafe YAML, `eval` of JSON-like strings).
Good: parameterized queries, context-aware output encoding, allow-list validation, no dynamic code from input.

## A06 Insecure Design
- Missing abuse-case thinking: no rate limiting/lockout on login, OTP, password reset, expensive endpoints; no quotas or cost caps.
- Business-logic flaws: negative quantities, price/discount tampering client-side, race conditions on balance/inventory/coupons (TOCTOU), replayable actions, skipped workflow steps.
- Sensitive operations without re-authentication or confirmation; password reset that leaks account existence.
- Trusting client-side validation; no separation between tenants or privilege levels in the design.
Ask: "What would a malicious but legitimate user try?" Often best caught in `review-architecture`; note cross-reference.

## A07 Authentication Failures
- Weak/absent session management: predictable IDs, no rotation on login, no invalidation on logout/password change, long-lived tokens without revocation, tokens in URLs/localStorage where cookie flags (`HttpOnly`, `Secure`, `SameSite`) were appropriate.
- Credential stuffing exposure (no throttling, no MFA path), default accounts, weak password policy per project standard.
- Account recovery that bypasses auth; user enumeration via error messages or timing.
- OAuth/OIDC mistakes: unvalidated `state`/`nonce`, open redirect URIs, accepting unsigned tokens, mixing up access and ID tokens.

## A08 Software or Data Integrity Failures
- Auto-update or plugin loading without signature/integrity checks; scripts/CSS from CDNs without SRI.
- Deserialization of data from untrusted channels; unsigned cookies/state that drive privileged behavior.
- CI/CD pipeline that lets unreviewed code reach production; artifacts not verified between build and deploy.
- Trusting webhooks without signature verification and replay protection.

## A09 Logging & Alerting Failures
- Security events not logged (login failure, access denied, privilege change, input-validation failures on sensitive paths) or not attributable (no user/request ID).
- Sensitive data in logs (tokens, passwords, full card numbers, PII, auth headers, LLM prompts containing user secrets).
- Log injection via unsanitized newlines; logs writable by the app's own compromised process; no alerting path for the new feature.

## A10 Mishandling of Exceptional Conditions (new in 2025)
- Errors that **fail open**: exception → default-allow, partial success treated as success, `catch (Exception) { /* ignore */ }` around authz or validation.
- Unhandled null/empty/oversized/malformed input crashing the process or leaking stack traces; unbounded memory/CPU on hostile input (zip bombs, deeply nested JSON, giant uploads).
- Resource cleanup missing on error paths (locks, transactions, file handles, temp files), leaving the system in an exploitable half-state.
- Retry storms and unbounded retries on auth/payment endpoints; error messages that reveal internals.
- Missing transaction rollback so a failure midway leaves inconsistent security state (user created without role, role granted without audit entry).
Good: explicit error taxonomy, fail closed, bounded inputs, tested negative paths.

## API-specific (OWASP API Security)
- Object-level (BOLA) and function-level (BFLA) authorization on every endpoint; property-level exposure (returning fields the caller shouldn't see; accepting fields they shouldn't set).
- Unrestricted resource consumption: pagination limits, payload size, query depth/complexity for GraphQL, batch endpoints.
- Unsafe consumption of third-party APIs: trusting upstream responses, no timeouts, following redirects blindly.
- Improper inventory: old API versions or debug endpoints left exposed.

## Web-specific extras
- CSRF: state-changing requests authenticated by cookies need CSRF tokens or SameSite + origin checks.
- File uploads: validate type by content not extension, cap size, store outside web root, randomize names, serve with safe content-type/disposition, scan if policy requires.
- Clickjacking (frame-ancestors), postMessage origin checks, `target=_blank` without `rel=noopener`.
- Cache poisoning/host-header trust; subdomain takeover risk when removing DNS-backed resources.
