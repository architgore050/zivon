"""`scripts/deploy_smoke.sh` — the post-boot smoke script (DEPLOY-PREP).

Hermetic, key-free, no Docker and no real site: the script is run via
subprocess against a local canned-origin HTTP server (a `http.server` in a
thread) that answers the eight documented checks. The server's status map is
mutated per case, so every PASS and FAIL path of the script is proven:

1. happy path — all eight checks print PASS, `RESULT: PASS`, exit 0
   (health with db ok, /healthz, /, the catalogue 301, the lesson shell, an
   asset, the WS-shaped /voice/ws answer, and the admin guard refusing an
   anonymous caller with 401/503);
2. a broken admin guard (anonymous call answered 200) FAILs the run — this is
   a stop-the-line check, not a note;
3. a voice route that plain-404s FAILs (the nginx /voice/ proxy is missing);
4. a backend that serves /v1/health 200 WITHOUT db ok FAILs;
5. an unreachable origin (dead port) FAILs with no crash and exit 1;
6. no-arg usage exits 2 with a usage line.
"""

from __future__ import annotations

import http.server
import socketserver
import subprocess
import threading
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "deploy_smoke.sh"

# path -> (status, body). The happy path mirrors what the real stack answers
# through the edge (docs/deployment/prototype-deployment.md §6).
HAPPY = {
    "/v1/health": (200, '{"status":"ok","db":"ok"}'),
    "/healthz": (200, "ok\n"),
    "/": (200, "<html>landing</html>"),
    "/courses/10/physics": (301, ""),
    "/class-10-physics/": (200, "<html>class 10</html>"),
    "/assets/app.css": (200, "body{}"),
    "/voice/ws": (400, "ws"),  # WS-shaped refusal (uvicorn rejects the probe)
    "/v1/admin/summary": (503, '{"error":"E-SERVICE-UNAVAILABLE"}'),
}


def _make_handler(status: dict[str, tuple[int, str]]):
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: object) -> None:
            pass  # quiet

        def do_GET(self) -> None:
            path = self.path.split("?")[0]
            entry = status.get(path)
            if entry is None:
                code, body = 404, "not found"
            else:
                code, body = entry
            payload = body.encode("utf-8")
            self.send_response(code)
            if path == "/courses/10/physics" and code == 301:
                self.send_header("Location", "/class-10-physics/")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_HEAD = do_GET

    return Handler


class SmokeScriptTestCase(unittest.TestCase):
    def run_smoke(self, base: str) -> tuple[int, str]:
        proc = subprocess.run(
            ["/bin/bash", str(SCRIPT), base],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        return proc.returncode, proc.stdout + proc.stderr

    def serve(self, status: dict[str, tuple[int, str]]):
        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        httpd = Server(("127.0.0.1", 0), _make_handler(status))
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(thread.join, 5)
        return f"http://127.0.0.1:{port}"


class TestHappyPath(SmokeScriptTestCase):
    def test_all_eight_checks_pass(self) -> None:
        base = self.serve(dict(HAPPY))
        code, out = self.run_smoke(base)
        self.assertEqual(code, 0, out)
        self.assertIn("RESULT: PASS", out)
        self.assertEqual(out.count("\nPASS "), 8, out)
        for needle in (
            "PASS /v1/health 200, db ok",
            "PASS /healthz 200",
            "PASS / 200",
            "PASS /courses/10/physics 301",
            "PASS /class-10-physics/ 200",
            "PASS /assets/app.css 200",
            "PASS /voice/ws HTTP 400",
            "PASS /v1/admin/summary HTTP 503",
        ):
            self.assertIn(needle, out)

    def test_admin_guard_401_also_passes(self) -> None:
        status = dict(HAPPY)
        status["/v1/admin/summary"] = (401, '{"error":"E-UNAUTHORIZED"}')
        base = self.serve(status)
        code, out = self.run_smoke(base)
        self.assertEqual(code, 0, out)
        self.assertIn("PASS /v1/admin/summary HTTP 401", out)


class TestFailurePaths(SmokeScriptTestCase):
    def _assert_fails(self, status: dict[str, tuple[int, str]], needle: str) -> None:
        base = self.serve(status)
        code, out = self.run_smoke(base)
        self.assertEqual(code, 1, out)
        self.assertIn("RESULT: FAIL", out)
        self.assertIn(needle, out)

    def test_open_admin_guard_fails_the_run(self) -> None:
        status = dict(HAPPY)
        status["/v1/admin/summary"] = (200, '{"ok":true}')
        self._assert_fails(status, "the admin API answered without a token")

    def test_plain_404_voice_route_fails(self) -> None:
        status = dict(HAPPY)
        status["/voice/ws"] = (404, "not found")
        self._assert_fails(status, "/voice/ws: HTTP 404")

    def test_health_without_db_ok_fails(self) -> None:
        status = dict(HAPPY)
        status["/v1/health"] = (200, '{"status":"ok","db":"boot_failed"}')
        self._assert_fails(status, "db not ok")

    def test_missing_static_page_fails(self) -> None:
        status = dict(HAPPY)
        del status["/class-10-physics/"]
        self._assert_fails(status, "/class-10-physics/: HTTP 404")

    def test_unreachable_origin_fails_cleanly(self) -> None:
        self.serve(dict(HAPPY))
        # pick a port that is (almost surely) not listening: reuse the same
        # server address AFTER it is closed is racy — use a fresh dead socket.
        import socket

        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        dead = f"http://127.0.0.1:{s.getsockname()[1]}"
        s.close()
        code, out = self.run_smoke(dead)
        self.assertEqual(code, 1, out)
        self.assertIn("RESULT: FAIL", out)

    def test_missing_argument_exits_2(self) -> None:
        proc = subprocess.run(
            ["/bin/bash", str(SCRIPT)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("usage:", proc.stderr)


if __name__ == "__main__":
    unittest.main()
