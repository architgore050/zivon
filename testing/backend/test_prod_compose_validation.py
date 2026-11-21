"""`scripts/validate_prod_compose.py` — the pre-boot compose validator (DEPLOY-PREP).

Hermetic, key-free, no Docker: the validator is run in-process (the importlib
`scripts/` entry-point pattern) against

1. the REAL `docker-compose.prod.yml` + `docker/caddy/Caddyfile` with an
   in-memory dummy env (generated with `secrets` at test time — dummy values
   never touch the repo tree), proving the shipped deployment contract still
   resolves on BOTH parser paths (PyYAML when installed, the stdlib minimal
   parser always — CI's tests job has no PyYAML), and
2. a synthetic fixture snippet (`fixtures/prod_compose/`) mutated per-case to
   prove the FAIL paths: a missing required var, a domain/origin mismatch,
   the forbidden `dev` email backend, an incomplete smtp transport, a broken
   migrate gate, and a Caddyfile with a literal site address.

A security contract closes the suite: the report names variables, never
values — no dummy secret may appear in any output.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import secrets
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "testing" / "backend" / "fixtures" / "prod_compose"
COMPOSE_FIXTURE = FIXTURES / "compose-fixture.yml"
CADDY_FIXTURE = FIXTURES / "Caddyfile-fixture"
CADDY_LITERAL = FIXTURES / "Caddyfile-literal-domain"
REAL_COMPOSE = REPO_ROOT / "docker-compose.prod.yml"
REAL_CADDY = REPO_ROOT / "docker" / "caddy" / "Caddyfile"

try:
    import yaml  # noqa: F401  (used only to decide whether the pyyaml path runs)

    HAS_PYYAML = True
except ImportError:  # pragma: no cover — CI's tests job has no PyYAML
    HAS_PYYAML = False

PARSERS = ["minimal"] + (["pyyaml"] if HAS_PYYAML else [])


def _load_validator() -> ModuleType:
    """Import the script the way an operator runs it."""
    path = REPO_ROOT / "scripts" / "validate_prod_compose.py"
    spec = importlib.util.spec_from_file_location("validate_prod_compose", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # register BEFORE exec: dataclasses resolves cls.__module__ via sys.modules
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V = _load_validator()


def _dummy_env(**overrides: str) -> dict[str, str]:
    """Throwaway dummy values (example.com / token_hex) — never committed."""
    values = {
        "ZIVON_APP_BASE_URL": "https://zivon.example.com",
        "ZIVON_DOMAIN": "zivon.example.com",
        "ZIVON_ACME_EMAIL": "ops@example.com",
        "POSTGRES_PASSWORD": secrets.token_hex(16),
        "ZIVON_SESSION_TOKEN_KEY": secrets.token_hex(32),
        "ZIVON_IP_HASH_SALT": secrets.token_hex(32),
        "ZIVON_ADMIN_TOKEN": secrets.token_hex(32),
        "ZIVON_EMAIL_BACKEND": "smtp",
        "ZIVON_EMAIL_FROM": "Zivon <no-reply@zivon.example.com>",
        "ZIVON_SMTP_HOST": "smtp.example.com",
        "ZIVON_SMTP_PORT": "587",
        "ZIVON_SMTP_USER": "dummy-user",
        "ZIVON_SMTP_PASSWORD": secrets.token_hex(16),
        "ZIVON_SMTP_STARTTLS": "true",
    }
    values.update(overrides)
    return values


class ValidatorTestCase(unittest.TestCase):
    """Runs the CLI in-process and asserts on (exit code, report text)."""

    def _run(
        self,
        env: dict[str, str],
        compose: Path = COMPOSE_FIXTURE,
        caddyfile: Path = CADDY_FIXTURE,
        parser: str = "minimal",
        profile: str = "edge",
    ) -> tuple[int, str]:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / "dummy.env.prod"
            env_path.write_text(
                "\n".join(f"{k}={v}" for k, v in env.items()) + "\n", encoding="utf-8"
            )
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = V.main(
                    [
                        "--env",
                        str(env_path),
                        "--compose",
                        str(compose),
                        "--caddyfile",
                        str(caddyfile),
                        "--parser",
                        parser,
                        "--profile",
                        profile,
                    ]
                )
            report = out.getvalue()
        self.assertNotIn(str(env_path), report)
        return code, report

    def assert_pass(self, report: str, contains: str) -> None:
        self.assertIn(contains, report)

    def assert_fails_with(self, code: int, report: str, needle: str) -> None:
        self.assertEqual(code, 1, f"expected FAIL exit 1, got {code}\n{report}")
        self.assertIn(needle, report)


class TestFixtureSnippet(ValidatorTestCase):
    """The synthetic fixture — every FAIL path, forced mutations included."""

    def test_happy_path_passes_on_both_parsers(self) -> None:
        for parser in PARSERS:
            with self.subTest(parser=parser):
                code, report = self._run(_dummy_env(), parser=parser)
                self.assertEqual(code, 0, report)
                self.assertIn("OUTCOME: PASS", report)
                self.assert_pass(report, "required-var")
                self.assert_pass(report, "migrate-gate")
                self.assert_pass(report, "localhost-binding")
                self.assert_pass(report, "caddyfile-domain")

    def test_missing_required_var_fails(self) -> None:
        env = _dummy_env()
        del env["ZIVON_SESSION_TOKEN_KEY"]
        code, report = self._run(env)
        self.assert_fails_with(code, report, "ZIVON_SESSION_TOKEN_KEY is REQUIRED")
        self.assertIn("OUTCOME: FAIL", report)

    def test_empty_required_var_fails(self) -> None:
        code, report = self._run(_dummy_env(POSTGRES_PASSWORD=""))
        self.assert_fails_with(code, report, "POSTGRES_PASSWORD is REQUIRED")

    def test_domain_mismatch_fails(self) -> None:
        code, report = self._run(
            _dummy_env(ZIVON_DOMAIN="other.example.net"),
        )
        self.assert_fails_with(code, report, "does not match the host of")

    def test_non_https_origin_fails(self) -> None:
        code, report = self._run(
            _dummy_env(ZIVON_APP_BASE_URL="http://zivon.example.com")
        )
        self.assert_fails_with(code, report, "must start with https://")

    def test_forbidden_dev_email_backend_fails(self) -> None:
        code, report = self._run(_dummy_env(ZIVON_EMAIL_BACKEND="dev"))
        self.assert_fails_with(code, report, "refused in the prod posture")

    def test_smtp_without_host_fails(self) -> None:
        code, report = self._run(_dummy_env(ZIVON_SMTP_HOST=""))
        self.assert_fails_with(code, report, "requires ZIVON_SMTP_HOST")

    def test_resend_without_api_key_fails(self) -> None:
        code, report = self._run(
            _dummy_env(
                ZIVON_EMAIL_BACKEND="resend",
                ZIVON_RESEND_API_KEY="",
                ZIVON_SMTP_HOST="",
            )
        )
        self.assert_fails_with(code, report, "requires ZIVON_RESEND_API_KEY")

    def test_unsafe_db_password_fails(self) -> None:
        code, report = self._run(_dummy_env(POSTGRES_PASSWORD="p@ss:word"))
        self.assert_fails_with(code, report, "contains @ : / ? or #")

    def test_broken_migrate_gate_fails(self) -> None:
        text = COMPOSE_FIXTURE.read_text(encoding="utf-8")
        broken = text.replace(
            "condition: service_completed_successfully", "condition: service_started"
        )
        self.assertNotEqual(text, broken)
        with tempfile.TemporaryDirectory() as tmp:
            compose = Path(tmp) / "compose-broken.yml"
            compose.write_text(broken, encoding="utf-8")
            code, report = self._run(_dummy_env(), compose=compose)
        self.assert_fails_with(code, report, "service_completed_successfully")

    def test_wrong_migrate_command_fails(self) -> None:
        text = COMPOSE_FIXTURE.read_text(encoding="utf-8")
        broken = text.replace(
            '"python", "-m", "db.migrate", "upgrade", "head"',
            '"python", "-m", "db.migrate", "downgrade", "-1"',
        )
        self.assertNotEqual(text, broken)
        with tempfile.TemporaryDirectory() as tmp:
            compose = Path(tmp) / "compose-broken.yml"
            compose.write_text(broken, encoding="utf-8")
            code, report = self._run(_dummy_env(), compose=compose)
        self.assert_fails_with(code, report, "migrate no longer runs")

    def test_publicly_bound_backend_port_fails(self) -> None:
        text = COMPOSE_FIXTURE.read_text(encoding="utf-8")
        broken = text.replace('- "127.0.0.1:18085:8000"', '- "18085:8000"')
        self.assertNotEqual(text, broken)
        with tempfile.TemporaryDirectory() as tmp:
            compose = Path(tmp) / "compose-broken.yml"
            compose.write_text(broken, encoding="utf-8")
            code, report = self._run(_dummy_env(), compose=compose)
        self.assert_fails_with(code, report, "not bound to 127.0.0.1")

    def test_literal_domain_caddyfile_fails(self) -> None:
        code, report = self._run(_dummy_env(), caddyfile=CADDY_LITERAL)
        self.assert_fails_with(code, report, "does not take its site address from")

    def test_edge_profile_without_domain_fails(self) -> None:
        code, report = self._run(_dummy_env(ZIVON_DOMAIN="", ZIVON_ACME_EMAIL=""))
        self.assert_fails_with(code, report, "ZIVON_DOMAIN must be set")

    def test_none_profile_skips_edge_requirements(self) -> None:
        env = _dummy_env(ZIVON_DOMAIN="", ZIVON_ACME_EMAIL="")
        code, report = self._run(env, profile="none")
        self.assertEqual(code, 0, report)
        self.assertIn("OUTCOME: PASS", report)


class TestRealDeploymentFiles(ValidatorTestCase):
    """The SHIPPED contract: docker-compose.prod.yml + Caddyfile as committed."""

    def test_real_compose_resolves_with_dummy_env(self) -> None:
        for parser in PARSERS:
            with self.subTest(parser=parser):
                code, report = self._run(
                    _dummy_env(),
                    compose=REAL_COMPOSE,
                    caddyfile=REAL_CADDY,
                    parser=parser,
                )
                self.assertEqual(code, 0, report)
                # the five REQUIRED vars the compose file demands
                for var in (
                    "POSTGRES_PASSWORD",
                    "ZIVON_APP_BASE_URL",
                    "ZIVON_EMAIL_BACKEND",
                    "ZIVON_SESSION_TOKEN_KEY",
                    "ZIVON_IP_HASH_SALT",
                ):
                    self.assertIn(f"{var} is set", report)
                self.assertIn("OUTCOME: PASS", report)

    def test_real_compose_parsers_agree_on_the_parsed_model(self) -> None:
        """pyyaml and the stdlib minimal parser must read the same contract:
        services, per-service environment keys, ports, depends conditions and
        the migrate command."""
        if not HAS_PYYAML:  # pragma: no cover
            self.skipTest("PyYAML not installed")
        snapshots: dict[str, dict] = {}
        for parser in ("pyyaml", "minimal"):
            model = V.parse_compose(REAL_COMPOSE, parser)
            self.assertIsNone(model.parse_error, parser)
            snapshots[parser] = {
                name: {
                    "env": sorted(svc.get("environment", {}).items()),
                    "ports": sorted(str(p) for p in svc.get("ports", [])),
                    "depends": svc.get("depends_conditions", {}),
                    "command": svc.get("command"),
                }
                for name, svc in model.services.items()
            }
        self.assertEqual(snapshots["pyyaml"], snapshots["minimal"])
        self.assertIn("migrate", snapshots["minimal"])

    def test_report_never_contains_dummy_secret_values(self) -> None:
        """Security contract: the report names variables, never values."""
        env = _dummy_env()
        secrets_used = [
            env["POSTGRES_PASSWORD"],
            env["ZIVON_SESSION_TOKEN_KEY"],
            env["ZIVON_IP_HASH_SALT"],
            env["ZIVON_ADMIN_TOKEN"],
            env["ZIVON_SMTP_PASSWORD"],
        ]
        for parser in PARSERS:
            with self.subTest(parser=parser):
                _code, report = self._run(
                    env, compose=REAL_COMPOSE, caddyfile=REAL_CADDY, parser=parser
                )
                for value in secrets_used:
                    self.assertNotIn(value, report)

    def test_real_compose_missing_required_var_fails(self) -> None:
        env = _dummy_env()
        del env["ZIVON_IP_HASH_SALT"]
        code, report = self._run(env, compose=REAL_COMPOSE, caddyfile=REAL_CADDY)
        self.assert_fails_with(code, report, "ZIVON_IP_HASH_SALT is REQUIRED")


class TestEnvFileParsing(ValidatorTestCase):
    """The dotenv reader: quotes, comments, export prefix, bad lines."""

    def test_quoted_values_and_comments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / "e.env"
            env_path.write_text(
                "# comment line\n"
                'export ZIVON_DOMAIN="zivon.example.com"\n'
                "ZIVON_ACME_EMAIL='ops@example.com'\n"
                "\n"
                "POSTGRES_PASSWORD=plain123\n",
                encoding="utf-8",
            )
            env = V.load_env_file(env_path)
        self.assertEqual(env["ZIVON_DOMAIN"], "zivon.example.com")
        self.assertEqual(env["ZIVON_ACME_EMAIL"], "ops@example.com")
        self.assertEqual(env["POSTGRES_PASSWORD"], "plain123")

    def test_bad_line_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / "e.env"
            env_path.write_text("this line has no equals\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                V.load_env_file(env_path)

    def test_missing_env_file_errors_exit_2(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = V.main(["--env", "/nonexistent/.env.prod"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
