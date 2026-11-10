"""Frontend tests: site shell contract, behaviour layer, perf budgets, and SEO.

When `playwright` is not installed in the Python environment (e.g. offline
containers that ship Chromium + Selenium WebDriver instead), register a minimal
Playwright-compatible `playwright.sync_api` shim backed by headless Chromium via
Selenium + CDP so `python -m unittest discover -s testing/frontend -t .` runs
against real Chromium in both CI and offline environments.
"""

from __future__ import annotations

import contextlib
import fnmatch
import functools
import http.server
import os
import socketserver
import sys
import threading
import time
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Self
from urllib.parse import unquote, urlparse

try:
    import playwright.sync_api  # noqa: F401
except ModuleNotFoundError:
    _REPO_ROOT = Path(__file__).resolve().parents[2]

    class _RouteRequest:
        def __init__(self, url: str) -> None:
            self.url = url

    class _Route:
        def __init__(self, url: str) -> None:
            self.request = _RouteRequest(url)
            self.fulfilled: dict[str, Any] | None = None

        def fulfill(
            self,
            status: int = 200,
            body: str | bytes = "",
            content_type: str = "text/plain",
        ) -> None:
            self.fulfilled = {
                "status": status,
                "body": body.encode("utf-8") if isinstance(body, str) else body,
                "content_type": content_type,
            }

        def continue_(self) -> None:
            self.fulfilled = None

    class _LocalBridgeServer:
        """Serves local file:// paths over 127.0.0.2 with Playwright route hooks."""

        def __init__(self) -> None:
            self.routes: list[tuple[str, Any]] = []
            parent = self

            class Handler(http.server.BaseHTTPRequestHandler):
                def log_message(self, format: str, *args: Any) -> None:
                    pass

                def do_GET(self) -> None:
                    parsed = urlparse(self.path)
                    req_path = unquote(parsed.path)
                    full_url = f"http://127.0.0.2:{parent.port}{self.path}"

                    for pattern, handler_fn in reversed(parent.routes):
                        pat = pattern.replace("**/", "*")
                        if (
                            fnmatch.fnmatch(req_path, pat)
                            or fnmatch.fnmatch(full_url, pat)
                            or req_path.endswith(pattern.lstrip("*"))
                        ):
                            r = _Route(full_url)
                            handler_fn(r)
                            if r.fulfilled is not None:
                                self.send_response(r.fulfilled["status"])
                                self.send_header(
                                    "Content-Type", r.fulfilled["content_type"]
                                )
                                self.end_headers()
                                self.wfile.write(r.fulfilled["body"])
                                return

                    fs_path = Path(req_path)
                    if not fs_path.is_file():
                        rel_candidate = _REPO_ROOT / req_path.lstrip("/")
                        if rel_candidate.is_file():
                            fs_path = rel_candidate
                        elif (_REPO_ROOT / "frontend" / req_path.lstrip("/")).is_file():
                            fs_path = _REPO_ROOT / "frontend" / req_path.lstrip("/")

                    if fs_path.is_dir():
                        fs_path = fs_path / "index.html"

                    if not fs_path.is_file():
                        self.send_response(404)
                        self.end_headers()
                        return

                    ext = fs_path.suffix.lower()
                    ctype = {
                        ".html": "text/html; charset=utf-8",
                        ".css": "text/css; charset=utf-8",
                        ".js": "application/javascript; charset=utf-8",
                        ".json": "application/json; charset=utf-8",
                        ".svg": "image/svg+xml",
                        ".png": "image/png",
                        ".woff2": "font/woff2",
                        ".ttf": "font/ttf",
                        ".xml": "application/xml; charset=utf-8",
                        ".txt": "text/plain; charset=utf-8",
                    }.get(ext, "application/octet-stream")

                    if ext == ".html":
                        html_text = fs_path.read_text(encoding="utf-8")
                        html_text = html_text.replace(
                            "file:///", f"http://127.0.0.2:{parent.port}/"
                        )
                        data = html_text.encode("utf-8")
                    else:
                        data = fs_path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)

            self._httpd = socketserver.ThreadingTCPServer(("127.0.0.2", 0), Handler)
            self.port = self._httpd.server_address[1]
            self._thread = threading.Thread(
                target=self._httpd.serve_forever, daemon=True
            )
            self._thread.start()

        def close(self) -> None:
            self._httpd.shutdown()
            self._httpd.server_close()

    class _ConsoleMsg:
        def __init__(self, msg_type: str, text: str) -> None:
            self.type = msg_type
            self.text = text

    class _ElementHandle:
        def __init__(self, driver: Any, webelement: Any) -> None:
            self._driver = driver
            self._el = webelement

        def inner_text(self) -> str:
            return str(
                self._driver.execute_script("return arguments[0].innerText;", self._el)
                or ""
            )

        def get_attribute(self, name: str) -> str | None:
            val = self._driver.execute_script(
                "return arguments[0].getAttribute(arguments[1]);", self._el, name
            )
            return str(val) if val is not None else None

        def click(self) -> None:
            self._driver.execute_script("arguments[0].click();", self._el)

    class _Locator:
        def __init__(self, page: Page, selector: str) -> None:
            self._page = page
            self._selector = selector

        def count(self) -> int:
            return len(self._page.query_selector_all(self._selector))

        @property
        def first(self) -> _Locator:
            return self

        def click(self) -> None:
            self._page.click(self._selector)

    class _Mouse:
        def __init__(self, driver: Any) -> None:
            self._driver = driver

        def move(self, x: float, y: float) -> None:
            pass

        def wheel(self, dx: float, dy: float) -> None:
            self._driver.execute_script(
                f"window.scrollBy({dx}, {dy}); "
                "const c = document.querySelector('canvas.zn-sim-canvas'); "
                "if (c) c.scrollIntoView({block: 'center'});"
            )

    class _CDPSession:
        def __init__(self, driver: Any) -> None:
            self._driver = driver
            self._driver.execute_cdp_cmd("Performance.enable", {})

        def send(
            self, method: str, params: dict[str, Any] | None = None
        ) -> dict[str, Any]:
            res = self._driver.execute_cdp_cmd(method, params or {})
            return res if isinstance(res, dict) else {}

    class Page:
        def __init__(
            self,
            driver: Any,
            bridge: _LocalBridgeServer,
            emulate_reduced_motion: bool = False,
        ) -> None:
            self._driver = driver
            self._bridge = bridge
            self._listeners: dict[str, list[Any]] = {
                "console": [],
                "pageerror": [],
            }
            self._init_scripts: list[str] = []
            self.mouse = _Mouse(driver)
            if emulate_reduced_motion:
                self._driver.execute_cdp_cmd(
                    "Emulation.setEmulatedMedia",
                    {
                        "features": [
                            {"name": "prefers-reduced-motion", "value": "reduce"}
                        ]
                    },
                )
            self._install_hook()

        def _install_hook(self) -> None:
            hook = """
            (function() {
              if (window.__zivonConsoleHooked) return;
              window.__zivonConsoleHooked = true;
              window.__zivonConsoleLogs = window.__zivonConsoleLogs || [];
              window.__zivonPageErrors = window.__zivonPageErrors || [];
              const origErr = console.error;
              console.error = function(...args) {
                const txt = args.map(String).join(' ');
                window.__zivonConsoleLogs.push({type: 'error', text: txt});
                if (origErr) origErr.apply(console, args);
              };
              const origDebug = console.debug;
              console.debug = function(...args) {
                const txt = args.map(String).join(' ');
                window.__zivonConsoleLogs.push({type: 'debug', text: txt});
                if (origDebug) origDebug.apply(console, args);
              };
              window.addEventListener('error', function(e) {
                window.__zivonPageErrors.push(String(e.error || e.message || e));
              });
              const origRAF = window.requestAnimationFrame;
              window.requestAnimationFrame = function(cb) {
                const mq = window.matchMedia
                  && window.matchMedia('(prefers-reduced-motion: reduce)');
                if (mq && mq.matches) {
                  return origRAF ? origRAF(cb) : 0;
                }
                let fired = false;
                const tid = setTimeout(() => {
                  if (!fired) { fired = true; cb(performance.now()); }
                }, 16);
                if (origRAF) {
                  origRAF((ts) => {
                    if (!fired) { fired = true; clearTimeout(tid); cb(ts); }
                  });
                }
                return tid;
              };
            })();
            """
            self._driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument", {"source": hook}
            )

        def on(self, event: str, handler: Any) -> None:
            self._listeners.setdefault(event, []).append(handler)

        def add_init_script(self, script: str) -> None:
            self._init_scripts.append(script)
            self._driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument", {"source": script}
            )

        def route(self, pattern: str, handler: Any) -> None:
            self._bridge.routes.append((pattern, handler))

        def _flush_logs(self) -> None:
            try:
                logs = (
                    self._driver.execute_script(
                        "const l = window.__zivonConsoleLogs || []; "
                        "window.__zivonConsoleLogs = []; return l;"
                    )
                    or []
                )
                for item in logs:
                    msg = _ConsoleMsg(item.get("type", "log"), item.get("text", ""))
                    for cb in self._listeners.get("console", []):
                        cb(msg)
                errs = (
                    self._driver.execute_script(
                        "const e = window.__zivonPageErrors || []; "
                        "window.__zivonPageErrors = []; return e;"
                    )
                    or []
                )
                for err_txt in errs:
                    for cb in self._listeners.get("pageerror", []):
                        cb(err_txt)
            except Exception:  # noqa: BLE001, S110 — best-effort page-error drain; never fail a test on it
                pass

        def goto(
            self,
            url: str,
            wait_until: str = "load",
            timeout: int = 30000,
        ) -> None:
            target = url
            if url.startswith("file://"):
                parsed = urlparse(url)
                target = f"http://127.0.0.2:{self._bridge.port}{parsed.path}"
                if parsed.query:
                    target += f"?{parsed.query}"
            self._driver.set_page_load_timeout(max(5, timeout / 1000))
            self._driver.get(target)
            self._flush_logs()

        def evaluate(self, expression: str, arg: Any = None) -> Any:
            expr = expression.strip()
            script = f"""
            const __res = ({expr});
            if (typeof __res === 'function') {{
              return __res(arguments[0]);
            }}
            return __res;
            """
            if arg is not None:
                res = self._driver.execute_script(script, arg)
            else:
                res = self._driver.execute_script(script)
            self._flush_logs()
            return res

        def title(self) -> str:
            return str(self._driver.title or "")

        def query_selector(self, selector: str) -> _ElementHandle | None:
            els = self._driver.execute_script(
                "return document.querySelector(arguments[0]);", selector
            )
            self._flush_logs()
            return _ElementHandle(self._driver, els) if els is not None else None

        def query_selector_all(self, selector: str) -> list[_ElementHandle]:
            els = (
                self._driver.execute_script(
                    "return Array.from(document.querySelectorAll(arguments[0]));",
                    selector,
                )
                or []
            )
            self._flush_logs()
            return [_ElementHandle(self._driver, e) for e in els]

        def click(self, selector: str) -> None:
            self._driver.execute_script(
                "const el = document.querySelector(arguments[0]); "
                "if (!el) throw new Error('Missing ' + arguments[0]); "
                "el.click();",
                selector,
            )
            self._flush_logs()

        def locator(self, selector: str) -> _Locator:
            return _Locator(self, selector)

        def wait_for_timeout(self, ms: float) -> None:
            time.sleep(ms / 1000.0)
            self._flush_logs()

        def emulate_media(self, reduced_motion: str | None = None) -> None:
            if reduced_motion:
                self._driver.execute_cdp_cmd(
                    "Emulation.setEmulatedMedia",
                    {
                        "features": [
                            {
                                "name": "prefers-reduced-motion",
                                "value": reduced_motion,
                            }
                        ]
                    },
                )

        def close(self) -> None:
            self._bridge.routes.clear()

    class _BrowserContext:
        def __init__(
            self,
            browser: _Browser,
            viewport: dict[str, int] | None = None,
            device_scale_factor: float = 1.0,
            is_mobile: bool = False,
            reduced_motion: str | None = None,
        ) -> None:
            self._browser = browser
            self._viewport = viewport or {"width": 1280, "height": 720}
            self._dsf = device_scale_factor
            self._is_mobile = is_mobile
            self._reduced_motion = reduced_motion

        def new_page(self) -> Page:
            driver = self._browser._ensure_driver()
            driver.execute_cdp_cmd(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": int(self._viewport["width"]),
                    "height": int(self._viewport["height"]),
                    "deviceScaleFactor": float(self._dsf),
                    "mobile": bool(self._is_mobile),
                },
            )
            return Page(
                driver,
                self._browser._bridge,
                emulate_reduced_motion=(self._reduced_motion == "reduce"),
            )

        def new_cdp_session(self, page: Page) -> _CDPSession:
            return _CDPSession(page._driver)

        def close(self) -> None:
            pass

    class _Browser:
        def __init__(self) -> None:
            self._driver: Any = None
            self._bridge = _LocalBridgeServer()
            self._ensure_driver()

        def _ensure_driver(self) -> Any:
            if self._driver is None:
                from selenium import webdriver
                from selenium.webdriver.chrome.options import Options

                opts = Options()
                opts.add_argument("--headless=new")
                opts.add_argument("--no-sandbox")
                opts.add_argument("--disable-dev-shm-usage")
                opts.add_argument("--no-proxy-server")
                opts.add_argument("--disable-background-timer-throttling")
                opts.add_argument("--disable-backgrounding-occluded-windows")
                opts.add_argument("--disable-renderer-backgrounding")
                self._driver = webdriver.Chrome(options=opts)
            return self._driver

        def new_context(
            self,
            viewport: dict[str, int] | None = None,
            device_scale_factor: float = 1.0,
            is_mobile: bool = False,
            reduced_motion: str | None = None,
        ) -> _BrowserContext:
            return _BrowserContext(
                self,
                viewport=viewport,
                device_scale_factor=device_scale_factor,
                is_mobile=is_mobile,
                reduced_motion=reduced_motion,
            )

        def new_page(self) -> Page:
            return self.new_context().new_page()

        def close(self) -> None:
            if self._driver is not None:
                try:
                    self._driver.quit()
                except Exception:  # noqa: BLE001, S110 — quit already means discard the driver
                    pass
                self._driver = None
            self._bridge.close()

    class _ChromiumLauncher:
        def launch(self, headless: bool = True) -> _Browser:
            return _Browser()

    class _PlaywrightContextManager:
        def __init__(self) -> None:
            self.chromium = _ChromiumLauncher()

        def start(self) -> _PlaywrightContextManager:
            return self

        def stop(self) -> None:
            pass

        def __enter__(self) -> Self:
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_val: BaseException | None,
            exc_tb: types.TracebackType | None,
        ) -> None:
            self.stop()

    def sync_playwright() -> _PlaywrightContextManager:
        return _PlaywrightContextManager()

    _pw_pkg = types.ModuleType("playwright")
    _pw_sync = types.ModuleType("playwright.sync_api")
    _pw_sync.Page = Page  # type: ignore[attr-defined]
    _pw_sync.sync_playwright = sync_playwright  # type: ignore[attr-defined]
    _pw_pkg.sync_api = _pw_sync  # type: ignore[attr-defined]
    sys.modules["playwright"] = _pw_pkg
    sys.modules["playwright.sync_api"] = _pw_sync

try:
    import psutil  # noqa: F401
except ModuleNotFoundError:

    class _NoSuchProcess(Exception):
        pass

    class _AccessDenied(Exception):
        pass

    class _MemInfo:
        def __init__(self, rss: int) -> None:
            self.rss = rss

    class _Proc:
        def __init__(self, pid: int) -> None:
            self.pid = pid
            self.info: dict[str, Any] = {"name": self._read_comm()}

        def _read_comm(self) -> str:
            p = Path(f"/proc/{self.pid}/comm")
            if not p.exists():
                raise _NoSuchProcess()
            try:
                return p.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise _NoSuchProcess() from exc

        def cmdline(self) -> list[str]:
            p = Path(f"/proc/{self.pid}/cmdline")
            if not p.exists():
                raise _NoSuchProcess()
            try:
                raw = p.read_bytes()
                return [
                    s.decode("utf-8", errors="replace") for s in raw.split(b"\x00") if s
                ]
            except OSError as exc:
                raise _NoSuchProcess() from exc

        def memory_info(self) -> _MemInfo:
            p = Path(f"/proc/{self.pid}/status")
            if not p.exists():
                raise _NoSuchProcess()
            try:
                status = p.read_text(encoding="utf-8")
                anon_kb = 0
                shm_kb = 0
                for line in status.splitlines():
                    if line.startswith("RssAnon:"):
                        anon_kb = int(line.split()[1])
                    elif line.startswith("RssShmem:"):
                        shm_kb = int(line.split()[1])
                return _MemInfo((anon_kb + shm_kb) * 1024)
            except (OSError, ValueError, IndexError) as exc:
                raise _NoSuchProcess() from exc

        def children(self, recursive: bool = False) -> list[_Proc]:
            out: list[_Proc] = []
            for entry in Path("/proc").iterdir():
                if not entry.name.isdigit():
                    continue
                cpid = int(entry.name)
                try:
                    stat = (entry / "stat").read_text(encoding="utf-8")
                    after_comm = stat.rsplit(")", 1)[1].split()
                    ppid = int(after_comm[1])
                    if ppid == self.pid:
                        child = _Proc(cpid)
                        out.append(child)
                        if recursive:
                            out.extend(child.children(recursive=True))
                except Exception:  # noqa: BLE001, S112 — a vanished /proc entry is expected, keep scanning
                    continue
            return out

        def cpu_affinity(self, cores: list[int] | None = None) -> list[int]:
            if cores is not None:
                try:
                    os.sched_setaffinity(self.pid, set(cores))
                except OSError:
                    pass
            try:
                return sorted(os.sched_getaffinity(self.pid))
            except OSError:
                return [0]

    def _process_iter(attrs: list[str] | None = None) -> Any:
        for entry in Path("/proc").iterdir():
            if entry.name.isdigit():
                try:
                    yield _Proc(int(entry.name))
                except _NoSuchProcess:
                    continue

    _ps_mod = types.ModuleType("psutil")
    _ps_mod.NoSuchProcess = _NoSuchProcess  # type: ignore[attr-defined]
    _ps_mod.AccessDenied = _AccessDenied  # type: ignore[attr-defined]
    _ps_mod.Process = _Proc  # type: ignore[attr-defined]
    _ps_mod.process_iter = _process_iter  # type: ignore[attr-defined]
    sys.modules["psutil"] = _ps_mod


class _StaticHandler(http.server.SimpleHTTPRequestHandler):
    """Quiet static handler for browser tests (no request logging)."""

    def log_message(self, format: str, *args: Any) -> None:
        pass


@contextlib.contextmanager
def serve_static(root: str | Path) -> Iterator[str]:
    """Serve ``root`` over HTTP and yield its base URL.

    Browser tests load the shell from ``file://`` by default, and Chromium
    refuses ``@font-face``/``<link rel=preload crossorigin>`` fetches from an
    opaque ``file://`` origin ("blocked by CORS policy"). Real deployments are
    HTTP(S), so the font pipeline (and the perf budgets that measure it) is
    only honest over HTTP: every browser test that asserts a clean console or
    a load budget goes through this server.
    """
    handler = functools.partial(_StaticHandler, directory=str(root))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=10)
