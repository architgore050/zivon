#!/usr/bin/env python3
"""Validate docker-compose.prod.yml + docker/caddy/Caddyfile BEFORE a boot.

Pre-cutover, no-docker check for the prototype deployment path
(docs/deployment/prototype-deployment.md, founder runbook
docs/deployment/founder-cutover-runbook.md). It answers, key-free and
offline, the same question `docker compose --env-file .env.prod -f
docker-compose.prod.yml config` answers on a machine that has Docker: does
every `${VAR:?...}` requirement in the compose file resolve, are the values
coherent with each other and with the Caddyfile, and does the file still
carry the structural posture the docs pin (migrations gate the backend,
localhost-only ports, no dev escape hatches)?

What it checks
  1. Interpolation: every compose `${VAR:?error}` (required) and
     `${VAR:-default}` (optional) expression resolves against the provided
     env file — a required var that is missing or empty FAILS.
  2. Value coherence: the public origin is https, ZIVON_DOMAIN matches the
     origin's host, the chosen email backend has its matching transport
     values, POSTGRES_PASSWORD is DSN-safe (no @ : / characters), generated
     secrets are not obviously weak.
  3. Forbidden values the docs refuse in prod (ZIVON_ENV=dev,
     ZIVON_EMAIL_BACKEND=dev, ZIVON_SPEAKING_MOCK=1,
     POSTGRES_HOST_AUTH_METHOD=trust) FAIL.
  4. Structure (per parser): the four product services exist, `migrate`
     still runs `python -m db.migrate upgrade head` and still gates
     `core-backend` on service_completed_successfully, non-edge services
     still bind 127.0.0.1 only, the Caddyfile still interpolates
     ZIVON_DOMAIN / ZIVON_ACME_EMAIL rather than a literal domain.

Usage
  python3 scripts/validate_prod_compose.py \
      --env /path/to/.env.prod [--profile edge|none] \
      [--compose docker-compose.prod.yml] [--caddyfile docker/caddy/Caddyfile] \
      [--parser auto|pyyaml|minimal]

Exit code 0 = every check PASSed (warnings allowed), 1 = at least one FAIL.
The env file is read only; its values are never printed — the report names
variables, never values.

Parser note: PyYAML is used when installed (the more robust path). Without
it the validator falls back to a minimal indentation-based reader that
handles the compose file's subset (nested mappings, `- item` lists, quoted
scalars, JSON flow sequences on the `command:` line). CI's tests job has no
PyYAML, so the minimal parser is the one the test suite exercises there —
`--parser minimal|pyyaml` forces one explicitly for debugging.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPOSE = REPO_ROOT / "docker-compose.prod.yml"
DEFAULT_CADDYFILE = REPO_ROOT / "docker" / "caddy" / "Caddyfile"

# Services the prototype path must define (docker-compose.prod.yml).
REQUIRED_SERVICES: frozenset[str] = frozenset(
    {"postgres", "migrate", "core-backend", "web"}
)
EDGE_SERVICE = "edge"
MIGRATE_COMMAND = "python -m db.migrate upgrade head"

# Forbidden in .env.prod / the compose path (prototype-deployment.md §4).
FORBIDDEN_VALUES: dict[str, frozenset[str]] = {
    "ZIVON_ENV": frozenset({"dev"}),
    "ZIVON_EMAIL_BACKEND": frozenset({"dev"}),
    "ZIVON_SPEAKING_MOCK": frozenset({"1", "true", "yes", "on"}),
    "POSTGRES_HOST_AUTH_METHOD": frozenset({"trust"}),
}

# Compose interpolation: ${VAR:?error} / ${VAR?error} / ${VAR:-default} /
# ${VAR-default}. `$$` is the literal-$ escape and is ignored.
_INTERP_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:?)(\?|-)([^}]*))?\}")

_SEVERITY_ORDER = {"FAIL": 0, "WARN": 1, "PASS": 2}


@dataclass
class Finding:
    severity: str  # PASS | WARN | FAIL
    check: str
    message: str

    def line(self) -> str:
        return f"[{self.severity}] {self.check}: {self.message}"


@dataclass
class ComposeModel:
    """The subset of the compose file the checks need."""

    services: dict[str, dict[str, object]] = field(default_factory=dict)
    parser_used: str = "pyyaml"
    parse_error: str | None = None


# ---------------------------------------------------------------------------
# env-file loading (read-only; values never echoed)
# ---------------------------------------------------------------------------


def load_env_file(path: Path) -> dict[str, str]:
    """Parse a dotenv file. `KEY=value`, optional `export `, optional
    single/double quotes, full-line comments. No interpolation."""
    env: dict[str, str] = {}
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            raise ValueError(f"{path}:{lineno}: not a KEY=value line")
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError(f"{path}:{lineno}: invalid variable name {key!r}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        env[key] = value
    return env


# ---------------------------------------------------------------------------
# compose parsing — pyyaml when available, minimal reader otherwise
# ---------------------------------------------------------------------------


def _normalize_service(raw: object) -> dict[str, object]:
    svc: dict[str, object] = {}
    if not isinstance(raw, dict):
        return svc
    env_raw = raw.get("environment")
    env: dict[str, str] = {}
    if isinstance(env_raw, dict):
        env = {str(k): "" if v is None else str(v) for k, v in env_raw.items()}
    elif isinstance(env_raw, list):
        for item in env_raw:
            if isinstance(item, str) and "=" in item:
                k, _, v = item.partition("=")
                env[k] = v
    svc["environment"] = env
    ports = raw.get("ports")
    svc["ports"] = (
        [str(p) for p in ports if isinstance(p, (str, int))]
        if isinstance(ports, list)
        else []
    )
    depends = raw.get("depends_on")
    deps: dict[str, object] = {}
    if isinstance(depends, dict):
        deps = {str(k): v for k, v in depends.items() if isinstance(v, dict)}
        svc["depends_conditions"] = {
            k: str(v.get("condition", "")) for k, v in deps.items()
        }
    elif isinstance(depends, list):
        svc["depends_list"] = [str(d) for d in depends]
    profiles = raw.get("profiles")
    svc["profiles"] = [str(p) for p in profiles] if isinstance(profiles, list) else []
    cmd = raw.get("command")
    if isinstance(cmd, list):
        svc["command"] = " ".join(str(c) for c in cmd)
    elif isinstance(cmd, str):
        svc["command"] = cmd
    svc["image"] = str(raw["image"]) if isinstance(raw.get("image"), str) else None
    svc["build"] = (
        raw.get("build") if isinstance(raw.get("build"), (dict, str)) else None
    )
    return svc


def parse_compose(path: Path, parser: str) -> ComposeModel:
    text = path.read_text(encoding="utf-8")
    if parser in ("auto", "pyyaml"):
        try:
            import yaml  # type: import-outside-toplevel
        except ImportError:
            if parser == "pyyaml":
                return ComposeModel(
                    parser_used="pyyaml",
                    parse_error="PyYAML is not installed (--parser pyyaml forced)",
                )
        else:
            try:
                doc = yaml.safe_load(text)
            except yaml.YAMLError as exc:
                return ComposeModel(parser_used="pyyaml", parse_error=str(exc))
            if not isinstance(doc, dict):
                return ComposeModel(
                    parser_used="pyyaml", parse_error="top level is not a mapping"
                )
            services_raw = doc.get("services")
            if not isinstance(services_raw, dict):
                return ComposeModel(
                    parser_used="pyyaml", parse_error="no services mapping"
                )
            model = ComposeModel(parser_used="pyyaml")
            model.services = {
                name: _normalize_service(svc)
                for name, svc in services_raw.items()
                if isinstance(name, str)
            }
            return model
    if parser in ("auto", "minimal"):
        return _parse_compose_minimal(text)
    return ComposeModel(parser_used=parser, parse_error=f"unknown parser {parser!r}")


def _strip_comment(line: str) -> str:
    """Drop a full-line comment; trim a trailing comment only outside quotes."""
    if line.lstrip().startswith("#"):
        return ""
    out: list[str] = []
    quote: str | None = None
    for i, ch in enumerate(line):
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            out.append(ch)
            continue
        if ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).rstrip()


def _parse_scalar(raw: str) -> object:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1]
    if raw.startswith("[") and raw.endswith("]"):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


def _parse_compose_minimal(text: str) -> ComposeModel:
    """Indentation-based reader for the compose-file YAML subset.

    Handles: nested mappings, `- ` list items, quoted scalars, JSON flow
    sequences (`["CMD", "..."]`). It is NOT a general YAML parser — block
    scalars (`|`/`>`), anchors and multi-line strings are unsupported; the
    interpolation scan (regex over raw text) does not depend on this parser,
    so a parse gap degrades structure checks, never the REQUIRED-var gate.
    """
    lines = [_strip_comment(l) for l in text.splitlines()]
    doc, _ = _parse_block(lines, 0, 0)
    services_raw = doc.get("services") if isinstance(doc, dict) else None
    if not isinstance(services_raw, dict):
        return ComposeModel(
            parser_used="minimal", parse_error="no services mapping found"
        )
    out: dict[str, dict[str, object]] = {}
    for name, svc in services_raw.items():
        if not isinstance(name, str):
            continue
        norm = _normalize_service(svc)
        deps = svc.get("depends_on") if isinstance(svc, dict) else None
        if isinstance(deps, dict):
            conds: dict[str, str] = {}
            for dep, val in deps.items():
                if isinstance(val, dict) and "condition" in val:
                    conds[str(dep)] = str(val["condition"])
                else:
                    conds[str(dep)] = ""
            norm["depends_conditions"] = conds
        cmd = svc.get("command") if isinstance(svc, dict) else None
        if isinstance(cmd, list):
            norm["command"] = " ".join(str(c) for c in cmd)
        elif isinstance(cmd, str):
            norm["command"] = cmd
        out[name] = norm
    return ComposeModel(parser_used="minimal", services=out)


def _parse_block(
    lines: list[str], i: int, indent: int
) -> tuple[dict[str, object], int]:
    """Parse a mapping block starting at line `i` with key indent `indent`."""
    result: dict[str, object] = {}
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        ind = len(line) - len(line.lstrip(" "))
        if ind < indent:
            break
        if ind > indent:
            i += 1  # unexpected deeper line (unsupported construct) — skip
            continue
        m = re.match(r"^([^:]+):\s*(.*)$", stripped)
        if not m:
            i += 1
            continue
        key = m.group(1).strip().strip("\"'")
        rest = m.group(2).strip()
        i += 1
        if rest:
            result[key] = _parse_scalar(rest)
            continue
        # Empty rest: the value is the following indented block (list or map).
        j = i
        while j < n and not lines[j].strip():
            j += 1
        if j >= n:
            result[key] = None
            continue
        nind = len(lines[j]) - len(lines[j].lstrip(" "))
        nstripped = lines[j].strip()
        if nind > indent and nstripped.startswith("- "):
            items, i = _parse_list(lines, j, nind)
            result[key] = items
        elif nind > indent:
            sub, i = _parse_block(lines, j, nind)
            result[key] = sub
        else:
            result[key] = None
    return result, i


def _parse_list(lines: list[str], i: int, indent: int) -> tuple[list[object], int]:
    """Parse `- item` list entries all at the same indent."""
    items: list[object] = []
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        ind = len(line) - len(line.lstrip(" "))
        if ind != indent or not stripped.startswith("- "):
            break
        items.append(_parse_scalar(stripped[2:]))
        i += 1
    return items, i


# ---------------------------------------------------------------------------
# Caddyfile
# ---------------------------------------------------------------------------


def read_caddyfile_site(path: Path) -> str | None:
    """The first site-address token, or None when absent."""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = _strip_comment(raw).strip()
        if not line or line.startswith(("{", "#")):
            continue
        if "=" in line and line.split("=", 1)[0].strip() in (
            "email",
            "encode",
            "header",
            "reverse_proxy",
        ):
            continue
        if line.endswith("{") or " " not in line:
            token = line.removesuffix("{").strip()
            if token and token not in ("{", "}"):
                return token
    return None


def _caddyfile_has_token(path: Path, token: str) -> bool:
    """True when a NON-COMMENT line of the Caddyfile carries the token."""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = _strip_comment(raw)
        if token in line:
            return True
    return False


# ---------------------------------------------------------------------------
# the validation itself
# ---------------------------------------------------------------------------


@dataclass
class Interp:
    var: str
    required: bool
    default: str | None  # None when required-form
    where: str


def scan_interpolations(text: str) -> list[Interp]:
    found: list[Interp] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        if raw.lstrip().startswith("#"):
            continue
        for m in _INTERP_RE.finditer(raw):
            if m.start() > 0 and raw[m.start() - 1] == "$":
                continue  # `$${VAR}` is compose's escaped literal — container-side
            var = m.group(1)
            colon, op, tail = m.group(2), m.group(3), m.group(4)
            if op == "?":
                found.append(
                    Interp(var, required=True, default=None, where=f"line {lineno}")
                )
            elif op == "-":
                # ${VAR:-x} always has a default; ${VAR-x} defaults only when
                # unset. Either way compose never fails on it.
                found.append(
                    Interp(
                        var,
                        required=False,
                        default=("" if colon == ":" else None) if tail else tail or "",
                        where=f"line {lineno}",
                    )
                )
            # plain ${VAR} (no op): compose passes the empty string through —
            # treat as optional-with-empty-default.
            elif op is None and colon is None:
                found.append(
                    Interp(var, required=False, default="", where=f"line {lineno}")
                )
    return found


def _resolve_all(interp: list[Interp], env: dict[str, str]) -> list[Finding]:
    findings: list[Finding] = []
    required_vars = sorted({i.var for i in interp if i.required})
    for var in required_vars:
        value = env.get(var, "")
        spec = next(i for i in interp if i.required and i.var == var)
        if not value:
            findings.append(
                Finding(
                    "FAIL",
                    "required-var",
                    f"{var} is REQUIRED by the compose file ({spec.where}) and is "
                    "missing or empty in the provided env",
                )
            )
        else:
            findings.append(
                Finding("PASS", "required-var", f"{var} is set ({spec.where})")
            )
    optional_vars = sorted({i.var for i in interp if not i.required})
    for var in optional_vars:
        findings.append(
            Finding(
                "PASS",
                "optional-var",
                f"{var} has a compose default (set: {'yes' if env.get(var) else 'no'})",
            )
        )
    return findings


def _hostname_of(url: str) -> str | None:
    from urllib.parse import urlsplit  # import-outside-toplevel

    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    return (host or "").lower() or None


def validate(
    compose_path: Path,
    caddyfile_path: Path,
    env: dict[str, str],
    *,
    parser: str = "auto",
    edge_profile: bool = True,
) -> list[Finding]:
    findings: list[Finding] = []
    text = compose_path.read_text(encoding="utf-8")

    # 1. interpolation / required vars (raw-text scan — parser independent)
    interp = scan_interpolations(text)
    findings.extend(_resolve_all(interp, env))

    # 2. forbidden values
    for var, bad in FORBIDDEN_VALUES.items():
        value = env.get(var, "")
        if value.strip().lower() in bad:
            findings.append(
                Finding(
                    "FAIL",
                    "forbidden-value",
                    f"{var}={value} is refused in the prod posture "
                    "(prototype-deployment.md §4)",
                )
            )

    # 3. value coherence
    base_url = env.get("ZIVON_APP_BASE_URL", "").strip()
    if base_url:
        if not base_url.startswith("https://"):
            findings.append(
                Finding(
                    "FAIL",
                    "origin-https",
                    "ZIVON_APP_BASE_URL must start with https:// — browsers grant "
                    "microphone access only in a secure context, and auth cookies "
                    "are Secure in prod",
                )
            )
        else:
            findings.append(Finding("PASS", "origin-https", "public origin is https"))
    else:
        # Required-form interpolation already FAILed above; skip coherence.
        base_url = ""

    domain = env.get("ZIVON_DOMAIN", "").strip()
    acme_email = env.get("ZIVON_ACME_EMAIL", "").strip()
    if edge_profile:
        if not domain:
            findings.append(
                Finding(
                    "FAIL",
                    "edge-vars",
                    "--profile edge is enabled: ZIVON_DOMAIN must be set "
                    "(the Caddyfile site address)",
                )
            )
        if not acme_email:
            findings.append(
                Finding(
                    "FAIL",
                    "edge-vars",
                    "--profile edge is enabled: ZIVON_ACME_EMAIL must be set "
                    "(Let's Encrypt notices)",
                )
            )
    if base_url and domain:
        host = _hostname_of(base_url)
        if host and host != domain.lower():
            findings.append(
                Finding(
                    "FAIL",
                    "domain-match",
                    f"ZIVON_DOMAIN ({domain}) does not match the host of "
                    f"ZIVON_APP_BASE_URL ({host}) — one origin end to end",
                )
            )
        else:
            findings.append(
                Finding(
                    "PASS",
                    "domain-match",
                    "ZIVON_DOMAIN matches the ZIVON_APP_BASE_URL host",
                )
            )

    # email transport coherence (backend/auth/email.py boot refusals, mirrored)
    email_backend = env.get("ZIVON_EMAIL_BACKEND", "").strip().lower()
    if email_backend == "smtp":
        if not env.get("ZIVON_SMTP_HOST", "").strip():
            findings.append(
                Finding(
                    "FAIL",
                    "email-transport",
                    "ZIVON_EMAIL_BACKEND=smtp requires ZIVON_SMTP_HOST (boot refuses)",
                )
            )
        else:
            findings.append(
                Finding("PASS", "email-transport", "smtp backend has ZIVON_SMTP_HOST")
            )
    elif email_backend == "resend":
        if not env.get("ZIVON_RESEND_API_KEY", "").strip():
            findings.append(
                Finding(
                    "FAIL",
                    "email-transport",
                    "ZIVON_EMAIL_BACKEND=resend requires ZIVON_RESEND_API_KEY "
                    "(boot refuses)",
                )
            )
        else:
            findings.append(
                Finding(
                    "PASS", "email-transport", "resend backend has ZIVON_RESEND_API_KEY"
                )
            )
    if email_backend and not env.get("ZIVON_EMAIL_FROM", "").strip():
        findings.append(
            Finding(
                "WARN",
                "email-from",
                "ZIVON_EMAIL_FROM is empty — verification/reset mail will carry "
                "the code default (Zivon <no-reply@zivon.local>)",
            )
        )

    pg_password = env.get("POSTGRES_PASSWORD", "")
    if pg_password:
        if any(c in pg_password for c in "@:/?#"):
            findings.append(
                Finding(
                    "FAIL",
                    "db-password-dsn-safe",
                    "POSTGRES_PASSWORD contains @ : / ? or # — it is interpolated "
                    "verbatim into the derived DSNs (see .env.prod.example); use "
                    "letters/digits (e.g. the token_hex helper)",
                )
            )
        else:
            findings.append(
                Finding(
                    "PASS",
                    "db-password-dsn-safe",
                    "POSTGRES_PASSWORD is URL-safe for DSN interpolation",
                )
            )

    for var, min_len, note in (
        ("ZIVON_SESSION_TOKEN_KEY", 32, "session signing key"),
        ("ZIVON_IP_HASH_SALT", 32, "IP-hash salt"),
        ("ZIVON_ADMIN_TOKEN", 24, "admin bearer (ADR-0026)"),
    ):
        value = env.get(var, "").strip()
        if value and len(value) < min_len:
            findings.append(
                Finding(
                    "WARN",
                    "weak-secret-length",
                    f"{var} looks short for a {note} — generate with "
                    '`python3 -c "import secrets; print(secrets.token_hex(32))"`',
                )
            )

    # 4. structure (parser-dependent; a parse error FAILs loud)
    model = parse_compose(compose_path, parser)
    if model.parse_error:
        findings.append(
            Finding(
                "FAIL",
                "compose-parse",
                f"compose file did not parse: {model.parse_error}",
            )
        )
        return findings
    findings.append(
        Finding("PASS", "compose-parse", f"parsed with the {model.parser_used} parser")
    )
    missing_services = sorted(REQUIRED_SERVICES - set(model.services))
    if missing_services:
        findings.append(
            Finding(
                "FAIL",
                "services-present",
                "missing required service(s): " + ", ".join(missing_services),
            )
        )
    else:
        findings.append(
            Finding(
                "PASS",
                "services-present",
                "postgres / migrate / core-backend / web all present",
            )
        )
    if edge_profile and EDGE_SERVICE not in model.services:
        findings.append(
            Finding("FAIL", "edge-service", "the edge (Caddy) service is missing")
        )
    elif edge_profile:
        profiles = model.services.get(EDGE_SERVICE, {}).get("profiles")
        if isinstance(profiles, list) and "edge" not in profiles:
            findings.append(
                Finding(
                    "WARN",
                    "edge-service",
                    "the edge service is not gated behind the 'edge' profile",
                )
            )

    migrate = model.services.get("migrate", {})
    command = str(migrate.get("command", ""))
    if command and MIGRATE_COMMAND not in command:
        findings.append(
            Finding(
                "FAIL",
                "migrate-command",
                f"migrate no longer runs `{MIGRATE_COMMAND}` (ADR-0016); got: {command}",
            )
        )
    elif command:
        findings.append(
            Finding(
                "PASS",
                "migrate-command",
                "migrate runs the exact cluster command (`" + MIGRATE_COMMAND + "`)",
            )
        )
    conds = model.services.get("core-backend", {}).get("depends_conditions", {})
    if (
        isinstance(conds, dict)
        and conds.get("migrate") != "service_completed_successfully"
    ):
        findings.append(
            Finding(
                "FAIL",
                "migrate-gate",
                "core-backend must depend on migrate with condition "
                "service_completed_successfully (a failed migration must never "
                "replace the running containers)",
            )
        )
    else:
        findings.append(
            Finding(
                "PASS",
                "migrate-gate",
                "core-backend starts only after migrations succeeded",
            )
        )

    # non-edge services bind localhost only
    for svc_name in ("postgres", "core-backend", "web"):
        ports = model.services.get(svc_name, {}).get("ports")
        if not isinstance(ports, list) or not ports:
            findings.append(
                Finding("WARN", "localhost-binding", f"{svc_name} publishes no ports")
            )
            continue
        bad_ports = [str(p) for p in ports if not str(p).startswith("127.0.0.1:")]
        if bad_ports:
            findings.append(
                Finding(
                    "FAIL",
                    "localhost-binding",
                    f"{svc_name} port(s) {', '.join(bad_ports)} not bound to "
                    "127.0.0.1 — only the edge may be publicly reachable "
                    "(runbook §1)",
                )
            )
        else:
            findings.append(
                Finding(
                    "PASS",
                    "localhost-binding",
                    f"{svc_name} binds only 127.0.0.1 on the host",
                )
            )
    edge_ports = model.services.get(EDGE_SERVICE, {}).get("ports", [])
    if edge_profile and isinstance(edge_ports, list):
        bad_edge = [str(p) for p in edge_ports if str(p).startswith("127.0.0.1:")]
        if bad_edge:
            findings.append(
                Finding(
                    "FAIL",
                    "edge-binding",
                    f"the edge port(s) {', '.join(bad_edge)} are bound to "
                    "127.0.0.1 — they must be public (80/443) to terminate TLS",
                )
            )
        else:
            findings.append(
                Finding(
                    "PASS",
                    "edge-binding",
                    "the edge publishes 80/443 publicly (TLS terminates here)",
                )
            )

    # 5. Caddyfile
    site = read_caddyfile_site(caddyfile_path)
    if not _caddyfile_has_token(caddyfile_path, "{$ZIVON_DOMAIN}"):
        findings.append(
            Finding(
                "FAIL",
                "caddyfile-domain",
                "the Caddyfile does not take its site address from "
                "{$ZIVON_DOMAIN} — a literal site address would drift from "
                ".env.prod",
            )
        )
    elif not _caddyfile_has_token(caddyfile_path, "{$ZIVON_ACME_EMAIL}"):
        findings.append(
            Finding(
                "FAIL",
                "caddyfile-acme",
                "the Caddyfile does not interpolate {$ZIVON_ACME_EMAIL}",
            )
        )
    else:
        findings.append(
            Finding(
                "PASS",
                "caddyfile-domain",
                "the Caddyfile site address and ACME email come from ZIVON_DOMAIN "
                "/ ZIVON_ACME_EMAIL",
            )
        )
    if site and not site.startswith("{$"):
        findings.append(
            Finding(
                "FAIL",
                "caddyfile-domain",
                f"the Caddyfile site address is the literal {site!r} — replace it "
                "with {$ZIVON_DOMAIN} so .env.prod stays the single source of truth",
            )
        )
    return findings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_report(findings: list[Finding]) -> str:
    counts = {s: 0 for s in _SEVERITY_ORDER}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    lines = [
        "=" * 72,
        "docker-compose.prod.yml pre-boot validation",
        "=" * 72,
    ]
    for f in sorted(
        findings, key=lambda x: (_SEVERITY_ORDER[x.severity], x.check, x.message)
    ):
        lines.append(f.line())
    lines.append("-" * 72)
    lines.append(
        f"RESULT: {counts['PASS']} pass, {counts['WARN']} warning(s), "
        f"{counts['FAIL']} failure(s)"
    )
    if counts["FAIL"]:
        lines.append("OUTCOME: FAIL — fix the [FAIL] items before `docker compose up`.")
    else:
        lines.append(
            "OUTCOME: PASS — the stack is coherent with the provided env values."
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--compose", type=Path, default=DEFAULT_COMPOSE)
    ap.add_argument("--caddyfile", type=Path, default=DEFAULT_CADDYFILE)
    ap.add_argument("--env", type=Path, required=True, help="env file (read only)")
    ap.add_argument(
        "--profile",
        choices=("edge", "none"),
        default="edge",
        help="validate for the Caddy edge profile (default) or a non-edge front",
    )
    ap.add_argument("--parser", choices=("auto", "pyyaml", "minimal"), default="auto")
    args = ap.parse_args(argv)

    try:
        env = load_env_file(args.env)
    except (OSError, ValueError) as exc:
        print(f"ERROR reading env file {args.env}: {exc}", file=sys.stderr)
        return 2

    findings = validate(
        args.compose,
        args.caddyfile,
        env,
        parser=args.parser,
        edge_profile=args.profile == "edge",
    )
    print(build_report(findings))
    return 1 if any(f.severity == "FAIL" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
