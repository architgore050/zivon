"""`scripts/backup_db.sh` — the host-side DB backup script (DEPLOY-PREP).

Hermetic, key-free, NO Docker (this path runs everywhere; the sandbox and CI
have no docker daemon): the ONE call the script makes into the stack —
`docker compose ... exec -T postgres sh -c 'pg_dump ...'` — is served by a
fake `docker` executable on PATH that emits canned pg_dump-shaped output.

Proven here:
1. success: the dump lands OUTSIDE the repo in the requested dir, mode 600,
   non-empty, gzip-intact, decompresses to real pg_dump content (the
   `-- PostgreSQL database dump` header), temp `.partial` file cleaned up,
   PASS line printed, exit 0;
2. every failure path exits 1 with a FAIL line naming the problem: an empty
   dump (a gzipped EMPTY stream is a valid gzip — regression for the
   empty-gzip acceptance bug), a failing pg_dump, a gzip stream whose
   decompressed content is not a pg_dump, and a missing env file;
3. retention: a dump older than ZIVON_BACKUP_RETENTION_DAYS is pruned, a
   fresh one is kept, and a non-numeric retention keeps everything (WARN).

The env file passed to the script is a THROWAWAY dummy in a temp dir — real
secrets are never touched, and no value is ever printed.
"""

from __future__ import annotations

import io
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "backup_db.sh"

# What a real pg_dump (plain SQL) always starts with — the script's
# content-verification check keys on this exact header line.
PG_DUMP_HEADER = "-- PostgreSQL database dump\n"
DUMP_BODY = PG_DUMP_HEADER + "\nCREATE TABLE t (id int);\n"

FAKE_DOCKER = textwrap.dedent(
    """\
    #!/bin/sh
    # Fake `docker` for backup_db.sh tests: emulates the single
    # `exec -T postgres sh -c 'pg_dump ...'` call the script makes.
    mode="${FAKE_DUMP_MODE:-ok}"
    for arg in "$@"; do
      case "$arg" in
        *pg_dump*)
          case "$mode" in
            ok)      printf '%s\\n\\nCREATE TABLE t (id int);\\n' \
                       '-- PostgreSQL database dump'; exit 0 ;;
            empty)   exit 0 ;;
            fail)    echo 'pg_dump: error: simulated failure' >&2; exit 7 ;;
            garbage) printf 'plain bytes, not a pg_dump\\n'; exit 0 ;;
          esac
          ;;
      esac
    done
    echo "fake-docker: unexpected invocation: $*" >&2
    exit 64
    """
)


class BackupScriptTestCase(unittest.TestCase):
    """Runs the script in a sandboxed temp world: fake docker on PATH."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.bin / "docker").write_text(FAKE_DOCKER, encoding="utf-8")
        os.chmod(self.bin / "docker", 0o755)
        self.backup_dir = self.root / "backups"
        self.backup_dir.mkdir()
        # throwaway env file: dummy names, never real values
        self.env_file = self.root / "dummy.env.prod"
        self.env_file.write_text(
            "POSTGRES_USER=zivon\n"
            "POSTGRES_DB=zivon\n"
            "POSTGRES_PASSWORD=dummy-password-not-a-secret\n",
            encoding="utf-8",
        )
        os.chmod(SCRIPT, 0o755)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_backup(
        self, mode: str = "ok", retention: str | None = None
    ) -> tuple[int, str, str]:
        env = dict(os.environ)
        env["PATH"] = f"{self.bin}:{env['PATH']}"
        env["FAKE_DUMP_MODE"] = mode
        env["ZIVON_ENV_FILE"] = str(self.env_file)
        env["ZIVON_BACKUP_DIR"] = str(self.backup_dir)
        env.pop("ZIVON_BACKUP_RETENTION_DAYS", None)
        if retention is not None:
            env["ZIVON_BACKUP_RETENTION_DAYS"] = retention
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            proc = subprocess.run(
                ["/bin/bash", str(SCRIPT)],
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        return (
            proc.returncode,
            proc.stdout + out.getvalue(),
            proc.stderr + err.getvalue(),
        )

    def dumps(self) -> list[Path]:
        return sorted(self.backup_dir.glob("zivon-db-*.sql.gz"))


class TestSuccessPath(BackupScriptTestCase):
    def test_dump_created_verified_and_cleaned(self) -> None:
        code, out, err = self.run_backup()
        self.assertEqual(code, 0, f"stdout:\n{out}\nstderr:\n{err}")
        files = self.dumps()
        self.assertEqual(len(files), 1, out)
        dump = files[0]
        # non-empty + gzip-integrity + real pg_dump content after decompress
        self.assertGreater(dump.stat().st_size, 0)
        import gzip

        content = gzip.decompress(dump.read_bytes()).decode("utf-8")
        self.assertIn("PostgreSQL database dump", content)
        self.assertIn("CREATE TABLE t", content)
        # mode 600 — a dump holds personal data; owner-read only
        self.assertEqual(stat.S_IMODE(dump.stat().st_mode), 0o600)
        # the .partial temp file must not survive
        self.assertEqual(list(self.backup_dir.glob("*.partial")), [])
        self.assertIn("PASS backup:", out)

    def test_retention_prunes_old_dumps_only(self) -> None:
        old = self.backup_dir / "zivon-db-20260101-000000.sql.gz"
        old.write_bytes(b"old")
        import os as _os
        import time as _time

        ancient = _time.time() - 40 * 86400
        _os.utime(old, (ancient, ancient))
        code, out, _err = self.run_backup(retention="14")
        self.assertEqual(code, 0, out)
        self.assertFalse(old.exists(), "dump older than the window must be pruned")
        self.assertEqual(len(self.dumps()), 1)
        self.assertIn("pruned 1 dump", out)

    def test_non_numeric_retention_keeps_everything(self) -> None:
        old = self.backup_dir / "zivon-db-20260101-000000.sql.gz"
        old.write_bytes(b"old")
        code, out, err = self.run_backup(retention="soon")
        self.assertEqual(code, 0, out)
        self.assertTrue(old.exists(), "a non-numeric retention must never delete")
        self.assertIn("WARN", err + out)


class TestFailurePaths(BackupScriptTestCase):
    def test_empty_dump_refused(self) -> None:
        """A gzipped EMPTY stream is a valid gzip — it must NOT count as a backup."""
        code, out, err = self.run_backup(mode="empty")
        self.assertEqual(code, 1, f"stdout:\n{out}\nstderr:\n{err}")
        self.assertIn("FAIL backup:", out + err)
        self.assertEqual(self.dumps(), [], "no dump file may be kept for an empty dump")

    def test_pg_dump_failure_refused(self) -> None:
        code, out, err = self.run_backup(mode="fail")
        self.assertEqual(code, 1)
        self.assertIn("FAIL backup:", out + err)
        self.assertEqual(self.dumps(), [])

    def test_non_pgdump_content_refused(self) -> None:
        """gzip-valid bytes that are not a pg_dump (wrong container/endpoint)."""
        code, out, err = self.run_backup(mode="garbage")
        self.assertEqual(code, 1)
        self.assertIn("pg_dump header", out + err)
        self.assertEqual(self.dumps(), [])

    def test_missing_env_file_refused(self) -> None:
        env = dict(os.environ)
        env["PATH"] = f"{self.bin}:{env['PATH']}"
        env["ZIVON_ENV_FILE"] = str(self.root / "does-not-exist.env.prod")
        env["ZIVON_BACKUP_DIR"] = str(self.backup_dir)
        proc = subprocess.run(
            ["/bin/bash", str(SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("env file not found", proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
