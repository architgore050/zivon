"""The headless render gate (PL3, interactive-artifacts.md §3 step 4, §6).

Build-time, Playwright, key-free, and OUTSIDE the student request path (the
turn has already delivered text). The gate is the proof that survives a lint
miss: with every network request aborted it asserts the document

- loads with zero console errors/warnings and zero unhandled rejections,
- attempts no network request (any attempt is a failure, not a log line),
- never navigates: no frame-navigated event after the initial load and the
  committed URL is unchanged (the sandbox permits a frame to navigate itself;
  CSP `frame-src 'none'` and this assertion are what stop it, §5.4),
- has no horizontal overflow at 360 px (`scrollWidth <= clientWidth + 2`),
- posts the harness `ready` message within 5 s,
- keeps the median sampled fps >= 24 with no long task > 200 ms — measured
  under the 4x CPU throttle the doctrine names (interactive-artifacts.md §4
  "floor 24 fps at 4x CPU throttle"; artifacts that never post an `fps`
  sample — static diagrams — pass trivially),
- stays inside the 1,500-node DOM cap measured in the real browser.

The report carries timings and counts only — never the artifact HTML (§6).
Browser tooling is a dev/test dependency (workstreams.md §4): when Playwright
or Chromium is missing the gate raises `RenderGateUnavailable` and the build
ships on lint alone with `render_ms = NULL` — recorded, not silent.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from .artifacts import MAX_DOM_NODES

READY_TIMEOUT_MS = 5000
RUN_MS = 3000
FPS_FLOOR = 24.0
LONG_TASK_MS = 200
OVERFLOW_SLACK_PX = 2
# The fps/long-task budget is measured under the 4x CPU throttle (§4).
CPU_THROTTLE_RATE = 4.0

# The gate loads the document from a reserved, route-fulfilled URL so the
# "committed URL equals the requested URL" assertion is meaningful; every
# other request is aborted and counted as a network attempt (§3 step 4).
_GATE_DOC_URL = "https://zivon-artifact-gate.invalid/artifact.html"

# The harness channel the gate listens for (§4): nothing else counts.
_READY_MESSAGE = {"source": "zivon-artifact", "type": "ready"}


class RenderGateUnavailable(RuntimeError):
    """Playwright/Chromium is not installed; the gate cannot run honestly."""


@dataclass
class RenderReport:
    """Counts and timings only — the artifact HTML never lands here (§6)."""

    render_ms: int
    failures: list[str] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    network_attempts: int = 0
    navigated: bool = False
    overflow_360: bool = False
    ready_ms: int | None = None
    dom_nodes: int = 0
    median_fps: float | None = None
    max_long_task_ms: float | None = None
    reduced_motion_ok: bool | None = None

    @property
    def ok(self) -> bool:
        return not self.failures


def run_render_gate(
    html: str,
    *,
    viewport_width: int = 360,
    run_ms: int = RUN_MS,
    check_reduced_motion: bool = True,
) -> RenderReport:
    """Load the artifact headlessly with network aborted and assert §3 step 4.

    Raises `RenderGateUnavailable` when the browser tooling is absent; every
    gate assertion failure lands in `report.failures` (render_ms included)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RenderGateUnavailable(
            "playwright is not installed (dev/test dependency); the render "
            "gate cannot run honestly — install it or run lint-only builds"
        ) from exc

    started = time.monotonic()
    report = RenderReport(render_ms=0)
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:
            raise RenderGateUnavailable(
                f"Chromium unavailable for the render gate: {type(exc).__name__}"
            ) from exc
        try:
            context = browser.new_context(
                viewport={"width": viewport_width, "height": 640}
            )
            _gate_page(context, html, report, run_ms)
            if check_reduced_motion:
                rm_context = browser.new_context(
                    viewport={"width": viewport_width, "height": 640},
                    reduced_motion="reduce",
                )
                try:
                    _reduced_motion_page(rm_context, html, report)
                finally:
                    rm_context.close()
        finally:
            browser.close()
    report.render_ms = int((time.monotonic() - started) * 1000)
    if report.dom_nodes > MAX_DOM_NODES:
        report.failures.append(
            f"dom_nodes={report.dom_nodes} exceeds the {MAX_DOM_NODES} cap"
        )
    return report


def _open_gate_page(context: Any, html: str) -> Any:
    """A page whose navigation to `_GATE_DOC_URL` is fulfilled locally with the
    artifact document; everything else is aborted and counted as an attempt.
    Init scripts (the harness listener) are registered before the navigation."""
    page = context.new_page()
    page.add_init_script(_INSTRUMENT_SCRIPT)

    def on_request(request: Any) -> None:
        if request.url != _GATE_DOC_URL:
            report_requests(page)

    page.on("request", on_request)
    context.route("**/*", lambda route: route.abort())
    context.route(
        _GATE_DOC_URL,
        lambda route: route.fulfill(body=html, content_type="text/html; charset=utf-8"),
    )
    return page


def report_requests(page: Any) -> None:
    """Record a non-document request attempt on the page's report (the page
    carries the report object via a bound attribute set by _gate_page)."""
    report = getattr(page, "_zivon_gate_report", None)
    if report is not None:
        report.network_attempts += 1


def _throttle_cpu(page: Any) -> None:
    """Apply the §4 4x CPU throttle via CDP for the fps/long-task window.
    A browser without the CDP domain would make the throttle a no-op, so a
    failure here is swallowed only when the domain is genuinely missing."""
    try:
        session = page.context.new_cdp_session(page)
        session.send("Emulation.setCPUThrottlingRate", {"rate": CPU_THROTTLE_RATE})
    except Exception as exc:
        raise RenderGateUnavailable(
            f"CPU throttling unavailable for the render gate: {type(exc).__name__}"
        ) from exc


def _gate_page(context: Any, html: str, report: RenderReport, run_ms: int) -> None:
    page = _open_gate_page(context, html)
    page._zivon_gate_report = report  # the request handler records attempts
    _throttle_cpu(page)

    def on_console(msg: Any) -> None:
        if msg.type in ("error", "warning"):
            report.console_errors.append(f"{msg.type}: {msg.text[:200]}")

    page.on("console", on_console)
    page.on("pageerror", lambda err: report.console_errors.append(f"pageerror: {err}"))

    initial_url = _GATE_DOC_URL
    page.goto(initial_url, wait_until="load")

    def on_navigated(_frame: Any) -> None:
        if page.url != initial_url:
            report.navigated = True

    page.on("framenavigated", on_navigated)

    # Harness messages: validate the schema the way the host does (§4).
    t0 = time.monotonic()
    fps_samples: list[float] = []
    long_tasks: list[float] = []
    end = time.monotonic() + run_ms / 1000
    while time.monotonic() < end:
        for item in _drain(page, "__zivonGateMessages"):
            if isinstance(item, dict):
                _collect_harness_message(item, report, t0, fps_samples)
        for item in _drain(page, "__zivonGateLongtasks"):
            if isinstance(item, (int, float)):
                long_tasks.append(float(item))
        if report.ready_ms is None and time.monotonic() > t0 + READY_TIMEOUT_MS / 1000:
            break
        page.wait_for_timeout(100)

    try:
        metrics = page.evaluate(
            "() => ({scroll: document.documentElement.scrollWidth,"
            " client: document.documentElement.clientWidth,"
            " nodes: document.getElementsByTagName('*').length,"
            " url: location.href})"
        )
    except Exception:  # noqa: BLE001 — the document died or navigated away
        metrics = {}
    report.dom_nodes = int(metrics.get("nodes") or 0)
    report.overflow_360 = (
        int(metrics.get("scroll") or 0)
        > int(metrics.get("client") or 0) + OVERFLOW_SLACK_PX
    )
    if report.overflow_360:
        report.failures.append(
            f"horizontal overflow (scrollWidth {metrics.get('scroll')} > "
            f"clientWidth {metrics.get('client')})"
        )
    if report.navigated or str(metrics.get("url", initial_url)) != initial_url:
        report.failures.append("the document navigated away from its own URL")
    if report.ready_ms is None:
        report.failures.append(
            f"no harness `ready` message within {READY_TIMEOUT_MS} ms"
        )
    if report.network_attempts:
        report.failures.append(
            f"{report.network_attempts} network request attempts (all aborted)"
        )
    if report.console_errors:
        report.failures.append(f"{len(report.console_errors)} console errors/warnings")
    if fps_samples:
        ordered = sorted(fps_samples)
        median = ordered[len(ordered) // 2]
        report.median_fps = round(median, 1)
        if median < FPS_FLOOR:
            report.failures.append(
                f"median fps {median:.1f} below the {FPS_FLOOR} floor"
            )
    report.max_long_task_ms = max(long_tasks) if long_tasks else None
    if report.max_long_task_ms is not None and report.max_long_task_ms > LONG_TASK_MS:
        report.failures.append(
            f"long task {report.max_long_task_ms:.0f} ms exceeds the {LONG_TASK_MS} ms budget"
        )
    page.close()


def _drain(page: Any, array_name: str) -> list[Any]:
    """Splice out the instrumented window array; a crashed/self-navigated page
    reads as empty (the navigation check covers it)."""
    try:
        value = page.evaluate(f"() => (window.{array_name} || []).splice(0)")
    except Exception:  # noqa: BLE001 — the document died or navigated away
        return []
    return value if isinstance(value, list) else []


def _collect_harness_message(
    msg: dict[str, Any], report: RenderReport, t0: float, fps_samples: list[float]
) -> None:
    if msg.get("source") != "zivon-artifact":
        report.failures.append(f"foreign harness message: {str(msg)[:80]}")
        return
    mtype = msg.get("type")
    if mtype == "ready" and report.ready_ms is None:
        report.ready_ms = int((time.monotonic() - t0) * 1000)
    elif mtype == "fps":
        frames, elapsed = msg.get("frames"), msg.get("elapsed_ms")
        if (
            isinstance(frames, (int, float))
            and isinstance(elapsed, (int, float))
            and elapsed > 0
        ):
            fps_samples.append(float(frames) / float(elapsed) * 1000.0)


def _reduced_motion_page(context: Any, html: str, report: RenderReport) -> None:
    """§3 step 4: a reduced-motion context renders a static frame — the page
    must still load cleanly and post `ready` (no crash, no animation error)."""
    page = _open_gate_page(context, html)
    page._zivon_gate_report = report
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)[:200]))
    page.goto(_GATE_DOC_URL, wait_until="load")
    ready = False
    deadline = time.monotonic() + READY_TIMEOUT_MS / 1000
    while time.monotonic() < deadline and not ready:
        msgs = _drain(page, "__zivonGateMessages")
        ready = any(
            isinstance(m, dict)
            and m.get("source") == "zivon-artifact"
            and m.get("type") == "ready"
            for m in msgs
        )
        if not ready:
            page.wait_for_timeout(100)
    report.reduced_motion_ok = ready and not errors
    if not ready:
        report.failures.append("reduced-motion context: no harness `ready` message")
    if errors:
        report.failures.append("reduced-motion context raised page errors")
    page.close()


_INSTRUMENT_SCRIPT = """
(() => {
  window.__zivonGateMessages = [];
  window.__zivonGateLongtasks = [];
  window.addEventListener('message', (event) => {
    if (event.data && typeof event.data === 'object') {
      window.__zivonGateMessages.push(event.data);
    }
  });
  try {
    const obs = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        window.__zivonGateLongtasks.push(entry.duration);
      }
    });
    obs.observe({entryTypes: ['longtask']});
  } catch (e) { /* longtask not supported: skip the budget check */ }
})();
"""


def lint_seeded_defects(defects: dict[str, str]) -> dict[str, list[str]]:
    """The pure-lint half of the seeded-defect runner (workstreams.md §4.3).

    Maps each seeded defect name to the lint hits it produces; the eval
    checker (`DET-PL03-LINT`) asserts every defect fails with its expected
    rule and the golden stays clean. No browser needed — key-free.
    """
    from .artifacts import lint_artifact_html

    return {name: lint_artifact_html(html) for name, html in defects.items()}


# --- DET-PL03-SANDBOX: the red-team escape test --------------------------------
#
# The red-team document is NOT linted (it is the attack simulator, not a build
# product). It runs inside a real sandboxed iframe (opaque origin) of a host
# page and reports every attempt through the harness channel; the host page
# then proves the containment assertions from its own side.

_REDACT_TEAM_PARENT_URL = "https://zivon-artifact-gate.invalid/host.html"
_SANDBOX_RUN_MS = 2500

_PARENT_PAGE = """<!doctype html><html><head><title>host</title></head><body>
<div id="keep">parent content</div>
<iframe id="art" sandbox="allow-scripts" referrerpolicy="no-referrer"></iframe>
<script>
  window.__attempts = [];
  window.__loads = 0;
  var frame = document.getElementById('art');
  frame.addEventListener('load', function () { window.__loads += 1; });
  window.addEventListener('message', function (event) {
    if (event.source === frame.contentWindow && event.data &&
        event.data.source === 'zivon-artifact') {
      window.__attempts.push(event.data);
    }
  });
</script>
</body></html>
"""


def run_sandbox_escape_test(redteam_html: str) -> dict[str, Any]:
    """Host the red-team document in a `sandbox="allow-scripts"` iframe and
    assert §5.4 containment. Returns `{"failures": [...], "attempts": [...]}`.

    Raises `RenderGateUnavailable` when Chromium is missing (an honest skip,
    never a fabricated pass)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RenderGateUnavailable(
            "playwright is not installed; the sandbox escape test cannot run honestly"
        ) from exc

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:
            raise RenderGateUnavailable(
                f"Chromium unavailable for the escape test: {type(exc).__name__}"
            ) from exc
        try:
            context = browser.new_context(viewport={"width": 640, "height": 480})
            context.route("**/*", lambda route: route.abort())
            context.route(
                _REDACT_TEAM_PARENT_URL,
                lambda route: route.fulfill(
                    body=_PARENT_PAGE, content_type="text/html; charset=utf-8"
                ),
            )
            context.route(
                _GATE_DOC_URL,
                lambda route: route.fulfill(
                    body=redteam_html, content_type="text/html; charset=utf-8"
                ),
            )
            page = context.new_page()
            page.goto(_REDACT_TEAM_PARENT_URL, wait_until="load")
            page.evaluate(
                "src => { document.getElementById('art').src = src; }", _GATE_DOC_URL
            )
            page.wait_for_timeout(_SANDBOX_RUN_MS)

            attempts = page.evaluate("() => window.__attempts || []")
            loads = int(page.evaluate("() => window.__loads || 0"))
            iframe_url = str(
                page.evaluate("() => document.getElementById('art').src || ''")
            )
            iframe_alive = bool(page.evaluate("() => !!document.getElementById('art')"))
            parent_nodes = int(
                page.evaluate("() => document.getElementsByTagName('*').length")
            )
            parent_title = str(page.title() or "")
            page.close()
        finally:
            browser.close()

    failures: list[str] = []
    attempts_index = {}
    for msg in attempts:
        if isinstance(msg, dict) and msg.get("type") == "state":
            try:
                payload = json.loads(str(msg.get("summary", "{}")))
                if isinstance(payload, dict):
                    attempts_index.update(payload)
            except ValueError:
                failures.append(f"red-team report unreadable: {str(msg)[:80]}")

    expectations = {
        "parent_dom_read": "blocked",
        "parent_storage_read": "blocked",
        "top_navigation": "blocked",
        "popup_open": "blocked",
        # The attempt is made; the containment proof is host-side: the frame
        # never navigates (URL unchanged, exactly one load), no popup exists.
        "form_submit": "attempted",
        "self_navigation_foreign": "attempted",
    }
    for attempt, want in expectations.items():
        got = attempts_index.get(attempt)
        if got != want:
            failures.append(
                f"red-team attempt {attempt!r} reported {got!r}, expected {want!r}"
            )
    if loads != 1:
        failures.append(
            f"the frame fired {loads} load events: a second load is the "
            "self-navigation tell and the host contract must unload it"
        )
    if iframe_url != _GATE_DOC_URL and iframe_alive:
        failures.append(f"the iframe src moved to {iframe_url} without a host unload")
    if parent_nodes < 4:  # the host page's own skeleton must be intact
        failures.append("the parent page lost DOM nodes")
    if parent_title != "host":
        failures.append(f"the parent page title changed to {parent_title!r}")
    return {"failures": failures, "attempts": attempts_index}
