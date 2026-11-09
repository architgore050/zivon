"""The admin dashboard v0 (dashboard-spec.md): one small FastAPI app, six
views, two trigger buttons, ADR-0026 auth, server-rendered HTML only.

Non-goals kept honest: no model calls, no writes to the store except its own
audit events, no client-side framework, no external assets (CSP
`default-src 'self'`), no Grafana replacement (link out). The buttons invoke
`scripts/trigger-tests.sh` / `scripts/trigger-factory-run.sh` — the scripts
stay the implementation (TIMELINE.md "Admin trigger commands").

X-Request-Id is bound at the HTTP edge and returned on every response
(logging-api.md §7).
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from logging_manager import log_event
from logging_manager.context import bind_from_headers, current_context

from .auth import SESSION_COOKIE, AdminAuth
from .cluster import cluster_available, factory_run_in_progress, job_log_tail, test_jobs
from .queries import LogStore, RunsArtifacts

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# trigger-factory-run.sh renders the topic through sed into the Job template,
# so the topic space is an ALLOWLIST, enforced here and in the script itself
# (the script must not trust its caller): first char alphanumeric, then
# alphanumerics / spaces / hyphens / underscores, 80 chars total. Anything
# else (& $ ; | quotes backslash newline ...) is rejected, never sanitized.
_TOPIC_ALLOWED = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,79}$")

# The only scripts _run_action may execute (CodeQL py/path-injection +
# py/command-line-injection): argv[0] must be one of these constants — no
# path separators, no leading dash, no other repo file. _ARG_ALLOWED covers
# every argv[1:] element the buttons pass (topic, digit class, "dashboard",
# the "--fresh" constant): first char alphanumeric blocks option injection
# ("--evil" as an argument), and the same set is re-checked in _run_action so
# the CodeQL barrier dominates the subprocess sink in the same function.
_ALLOWED_SCRIPTS = ("trigger-tests.sh", "trigger-factory-run.sh")
_ARG_ALLOWED = re.compile(r"^(?:[A-Za-z0-9][A-Za-z0-9 _-]{0,79}|--fresh)$")

# Run ids are factory slugify() output (factory/artifacts.py): lowercase
# alphanumerics and hyphens, 63 chars max. Same slug as dashboard/queries.py;
# validated at the route so an id can never reach a filesystem path.
_RUN_ID_ALLOWED = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
}


def _secure_cookies() -> bool:
    return os.environ.get("ZIVON_PUBLIC_BASE_URL", "").startswith("https://")


def _grafana_url() -> str:
    return os.environ.get("ZIVON_GRAFANA_URL", "").strip()


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Every HTTP edge (spec.md §3): accept a well-formed inbound
    X-Request-Id or generate one; always return it; hardening headers on
    every response."""

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        request_id = bind_from_headers(request.headers)
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response


def create_app() -> FastAPI:
    app = FastAPI(title="zivon-dashboard", docs_url=None, redoc_url=None)
    auth = AdminAuth()
    app.add_middleware(CorrelationMiddleware)
    app.mount(
        "/static",
        StaticFiles(directory=str(Path(__file__).parent / "static")),
        name="static",
    )

    def _store() -> LogStore:
        return LogStore.from_env()

    def _wants_html(request: Request) -> bool:
        return "text/html" in request.headers.get("accept", "text/html")

    def _session_id(request: Request) -> str | None:
        return request.cookies.get(SESSION_COOKIE)

    def _render(
        request: Request,
        template: str,
        *,
        store: LogStore | None = None,
        status_code: int = 200,
        **context: Any,
    ) -> HTMLResponse:
        base = {
            "request": request,
            "request_id": current_context().get("request_id"),
            "grafana_url": _grafana_url(),
            "csrf_token": auth.csrf_for(_session_id(request)) or "",
            "store_error": store.error if store else None,
            "cluster_up": cluster_available(),
            "alert_count": len(context.get("alerts", [])),
        }
        base.update(context)
        return TEMPLATES.TemplateResponse(
            request, template, base, status_code=status_code
        )

    # ------------------------------------------------------------- health
    @app.get("/healthz")
    def healthz() -> JSONResponse:
        """Probes: 200 when the process is up AND the store is reachable OR
        the fallback is active — a dashboard that cannot read the store says
        so on the page, it does not flap (dashboard-spec.md §1)."""
        if os.environ.get("ZIVON_LOG_DSN", "").strip():
            store = _store()
            ok = store.reachable
            mode = "postgres" if store.reachable else "unreachable"
        else:
            ok = True  # no DSN: the JSONL fallback is the store's mode
            mode = "fallback"
        return JSONResponse(
            status_code=200 if ok else 503, content={"ok": ok, "store": mode}
        )

    # -------------------------------------------------------- auth routes
    @app.get("/admin/login", response_class=HTMLResponse)
    def login_form(request: Request) -> Any:
        if auth.verify(_session_id(request)):
            return RedirectResponse("/admin", status_code=303)
        return _render(
            request,
            "login.html",
            login_csrf=auth.login_csrf_token(),
            unconfigured=not auth.configured(),
        )

    @app.post("/admin/login")
    def login_submit(
        request: Request,
        token: str = Form(default=""),
        csrf: str = Form(default=""),
    ) -> Any:
        if not auth.login_csrf_valid(csrf):
            return _render(
                request,
                "login.html",
                login_csrf=auth.login_csrf_token(),
                unconfigured=not auth.configured(),
                error="invalid request (stale form — reload)",
                status_code=401,
            )
        source_ip = request.client.host if request.client else "unknown"
        session_id = auth.login(token, source_ip)
        if session_id is None:
            status = 503 if not auth.configured() else 401
            if status == 503:
                return JSONResponse(
                    status_code=503,
                    content={"error": "admin auth is not configured (fail-closed)"},
                )
            return _render(
                request,
                "login.html",
                login_csrf=auth.login_csrf_token(),
                unconfigured=not auth.configured(),
                error="invalid token",
                status_code=401,
            )
        response = RedirectResponse("/admin", status_code=303)
        response.set_cookie(
            SESSION_COOKIE,
            session_id,
            max_age=12 * 3600,
            httponly=True,
            samesite="strict",
            secure=_secure_cookies(),
            path="/",
        )
        return response

    @app.post("/admin/logout")
    def logout(request: Request) -> Any:
        auth.logout(_session_id(request))
        response = RedirectResponse("/admin/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    # ------------------------------------------------------------ guard
    def _guard(request: Request) -> Any:
        """Everything except /admin/login and /healthz (ADR-0026 §3)."""
        if not auth.configured():
            return JSONResponse(
                status_code=503,
                content={"error": "admin auth is not configured (fail-closed)"},
            )
        if auth.verify(_session_id(request)):
            return None
        if _wants_html(request):
            return RedirectResponse("/admin/login", status_code=303)
        return JSONResponse(status_code=401, content={"error": "unauthenticated"})

    # ------------------------------------------------------------- views
    @app.get("/admin", response_class=HTMLResponse)
    def overview(request: Request) -> Any:
        denied = _guard(request)
        if denied:
            return denied
        store = _store()
        runs = store.recent_runs(limit=5)
        errors = store.error_feed(limit=200)
        voice = store.voice_percentiles()
        credits = store.credit_usage()
        return _render(
            request,
            "overview.html",
            store=store,
            alerts=store.alerts(),
            runs=runs,
            error_count=len(errors["rows"]),
            voice_p95=voice["windows"]["24h"].get("p95_ms"),
            voice_count=voice["windows"]["24h"].get("count", 0),
            credit_latest=credits["latest"],
        )

    @app.get("/admin/runs", response_class=HTMLResponse)
    def runs_view(request: Request) -> Any:
        denied = _guard(request)
        if denied:
            return denied
        store = _store()
        return _render(
            request,
            "runs.html",
            store=store,
            alerts=store.alerts(),
            runs=store.recent_runs(limit=20),
            manual_running=factory_run_in_progress(),
        )

    @app.get("/admin/runs/{run_id}", response_class=HTMLResponse)
    def run_detail_view(request: Request, run_id: str) -> Any:
        denied = _guard(request)
        if denied:
            return denied
        # Run-id allowlist at the HTTP edge (the queries layer re-checks it):
        # anything outside the slug space (separators, traversal, encoded
        # slashes) is no run at all — 404, never handed to a path.
        if not _RUN_ID_ALLOWED.fullmatch(run_id):
            return JSONResponse(status_code=404, content={"error": "unknown run"})
        store = _store()
        detail = store.run_detail(run_id)
        artifacts = RunsArtifacts()
        report = artifacts.report(run_id)
        return _render(
            request,
            "run_detail.html",
            store=store,
            alerts=[],
            detail=detail,
            report=report,
            artifact_exists=artifacts.has_run(run_id),
        )

    @app.get("/admin/tests", response_class=HTMLResponse)
    def tests_view(request: Request) -> Any:
        denied = _guard(request)
        if denied:
            return denied
        store = _store()
        jobs = test_jobs(limit=10)
        tails = {job["name"]: job_log_tail(job["name"]) for job in jobs[:3]}
        return _render(
            request,
            "tests.html",
            store=store,
            alerts=store.alerts(),
            jobs=jobs,
            log_tails=tails,
        )

    @app.get("/admin/voice", response_class=HTMLResponse)
    def voice_view(request: Request) -> Any:
        denied = _guard(request)
        if denied:
            return denied
        store = _store()
        voice = store.voice_percentiles()
        return _render(
            request,
            "voice.html",
            store=store,
            alerts=store.alerts(),
            voice=voice,
            gate_c_ms=4000,
        )

    @app.get("/admin/credits", response_class=HTMLResponse)
    def credits_view(request: Request) -> Any:
        denied = _guard(request)
        if denied:
            return denied
        store = _store()
        credits = store.credit_usage()
        return _render(
            request,
            "credits.html",
            store=store,
            alerts=store.alerts(),
            credits=credits,
        )

    @app.get("/admin/errors", response_class=HTMLResponse)
    def errors_view(request: Request) -> Any:
        denied = _guard(request)
        if denied:
            return denied
        store = _store()
        feed = store.error_feed()
        return _render(
            request,
            "errors.html",
            store=store,
            alerts=store.alerts(),
            feed=feed,
        )

    @app.get("/admin/publish", response_class=HTMLResponse)
    def publish_view(request: Request) -> Any:
        denied = _guard(request)
        if denied:
            return denied
        store = _store()
        publish = store.publish_status()
        return _render(
            request,
            "publish.html",
            store=store,
            alerts=store.alerts(),
            publish=publish,
        )

    # -------------------------------------------------------- the buttons
    def _run_action(
        request: Request,
        action: str,
        argv: list[str],
        csrf: str | None,
    ) -> Any:
        """The two trigger buttons: session + CSRF double-submit, then the
        SAME script the admin runs by hand; every invocation is an L3
        dashboard.action_triggered event with action/args/result."""
        if not auth.csrf_valid(_session_id(request), csrf):
            return JSONResponse(status_code=403, content={"error": "bad CSRF token"})
        # Path guard (py/path-injection): argv[0] must be an allowlisted
        # constant (no separators / leading dash possible past this line),
        # then resolve() + is_relative_to keeps the executable inside
        # <repo>/scripts even if ZIVON_REPO_DIR itself were attacker-shaped.
        if not argv or argv[0] not in _ALLOWED_SCRIPTS:
            return JSONResponse(status_code=500, content={"error": "unknown script"})
        repo = Path(os.environ.get("ZIVON_REPO_DIR", str(REPO_ROOT))).resolve()
        scripts_dir = (repo / "scripts").resolve()
        script = (scripts_dir / argv[0]).resolve()
        if not script.is_relative_to(scripts_dir):
            return JSONResponse(status_code=500, content={"error": "script path"})
        if not script.is_file():
            result = f"script missing: scripts/{argv[0]}"
            ok = False
        else:
            # Command guard (py/command-line-injection): every argv element is
            # re-checked against the same allowlist the handlers enforce, so
            # the barrier dominates the subprocess sink in this function.
            # List form + shell=False: no element is shell-parsed, and the
            # first-char-alphanumeric rule blocks option injection ("--evil").
            # ("--fresh" is the sole hyphen-leading constant, matched exactly.)
            # Each element is appended to safe_args only after its own check,
            # so the list reaching subprocess carries validated values only.
            safe_args: list[str] = []
            for arg in argv[1:]:
                if not _ARG_ALLOWED.fullmatch(arg):
                    return JSONResponse(
                        status_code=500,
                        content={"error": "invalid script argument"},
                    )
                safe_args.append(arg)
            try:
                proc = subprocess.run(
                    [str(script), *safe_args],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                    shell=False,
                    cwd=str(repo),
                )
                ok = proc.returncode == 0
                result = (proc.stdout + proc.stderr).strip()[:400] or (
                    "exit 0" if ok else f"exit {proc.returncode}"
                )
            except subprocess.TimeoutExpired:
                ok = False
                result = "timed out after 60s"
        log_event(
            "dashboard.action_triggered",
            {"action": action, "args": argv[1:], "result": result[:300]},
        )
        if _wants_html(request):
            target = "/admin/tests" if action == "tests-now" else "/admin/runs"
            return RedirectResponse(target, status_code=303)
        return JSONResponse(
            status_code=200 if ok else 500, content={"action": action, "result": result}
        )

    @app.post("/admin/actions/tests-now")
    def action_tests_now(request: Request, csrf: str = Form(default="")) -> Any:
        denied = _guard(request)
        if denied:
            return denied
        return _run_action(
            request, "tests-now", ["trigger-tests.sh", "dashboard"], csrf
        )

    @app.post("/admin/actions/factory-run")
    def action_factory_run(
        request: Request,
        topic: str = Form(default=""),
        class_level: str = Form(default=""),
        fresh: str = Form(default=""),
        csrf: str = Form(default=""),
    ) -> Any:
        denied = _guard(request)
        if denied:
            return denied
        topic = topic.strip()
        if "\r" in topic or "\n" in topic:
            # an explicit newline rejection (a regex alone is not enough:
            # "$" can match before a trailing newline in some engines).
            return JSONResponse(
                status_code=422, content={"error": "topic must be one line"}
            )
        if not _TOPIC_ALLOWED.fullmatch(topic):
            return JSONResponse(
                status_code=422,
                content={
                    "error": (
                        "topic must start with a letter or digit and then "
                        "contain only letters, digits, spaces, hyphens and "
                        "underscores (max 80 chars)"
                    )
                },
            )
        class_int: int | None = None
        if class_level:
            if not class_level.isdigit() or not 6 <= int(class_level) <= 12:
                return JSONResponse(
                    status_code=422, content={"error": "class must be 6-12"}
                )
            class_int = int(class_level)
        if factory_run_in_progress():
            return JSONResponse(
                status_code=409,
                content={
                    "error": "a factory run is already in progress (manual-only rule)"
                },
            )
        argv = ["trigger-factory-run.sh", topic]
        if class_int is not None:
            # int round-trip: the argv element is int-derived, never the raw
            # form string (CodeQL py/command-line-injection clean by type).
            argv.append(str(class_int))
        if fresh:
            argv.append("--fresh")
        return _run_action(request, "factory-run", argv, csrf)

    return app


app = create_app()
