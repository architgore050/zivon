"""Unit tests for the harness browser-pid identification.

The harness must measure the chromium IT launched - never a chrome process
that happens to be running on the machine (the developer's own browser).
psutil is faked; no real browser is launched here.
"""

import sys
import types
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from testing.content_factory.perf import harness


class FakeProc:
    def __init__(self, pid: int, name: str, cmdline: list[str]) -> None:
        self.pid = pid
        self.name = name
        self._cmdline = cmdline

    def cmdline(self) -> list[str]:
        return self._cmdline


def make_fake_psutil(procs: list[FakeProc]) -> types.SimpleNamespace:
    class NoSuchProcess(Exception):
        pass

    class AccessDenied(Exception):
        pass

    by_pid = {p.pid: p for p in procs}

    def process_iter(attrs=()):
        return [types.SimpleNamespace(pid=p.pid, info={"name": p.name}) for p in procs]

    def Process(pid: int) -> FakeProc:
        if pid not in by_pid:
            raise NoSuchProcess(pid)
        return by_pid[pid]

    return types.SimpleNamespace(
        process_iter=process_iter,
        Process=Process,
        NoSuchProcess=NoSuchProcess,
        AccessDenied=AccessDenied,
    )


CHROME_MAIN = ["chrome", "--headless=new", "--disable-gpu"]
CHROME_RENDERER = ["chrome", "--type=renderer", "--headless=new"]


class TestBrowserPid(unittest.TestCase):
    def _patch(self, procs: list[FakeProc]):
        return mock.patch.dict(sys.modules, {"psutil": make_fake_psutil(procs)})

    def test_ignores_preexisting_developer_chrome(self):
        procs = [
            FakeProc(100, "chrome", ["chrome"]),  # the developer's browser
            FakeProc(500, "chrome", CHROME_MAIN),  # ours: main process
            FakeProc(501, "chrome", CHROME_RENDERER),  # ours: renderer child
        ]
        with self._patch(procs):
            self.assertEqual(harness._browser_pid({100}), 500)

    def test_chromium_headless_shell_counts_as_chromium(self):
        procs = [
            FakeProc(
                700,
                "chromium_headless_shell",
                ["chromium_headless_shell", "--headless"],
            ),
        ]
        with self._patch(procs):
            self.assertEqual(harness._browser_pid(set()), 700)

    def test_non_browser_processes_are_filtered(self):
        procs = [
            FakeProc(
                300, "chromebox", ["chromebox"]
            ),  # name does not count? it does - prefix match
            FakeProc(301, "firefox", ["firefox"]),
        ]
        with self._patch(procs):
            # 'chromebox' starts with 'chrome' and is pre-existing -> excluded;
            # firefox is filtered by name. Nothing new -> None.
            self.assertIsNone(harness._browser_pid({300}))

    def test_no_new_process_returns_none(self):
        procs = [FakeProc(100, "chrome", ["chrome"])]
        with self._patch(procs):
            self.assertIsNone(harness._browser_pid({100}))

    def test_fallback_to_lowest_new_pid_when_flags_unfamiliar(self):
        procs = [
            FakeProc(610, "chrome", ["chrome", "--type=renderer"]),
            FakeProc(605, "chrome", ["chrome", "--some-new-flag"]),
        ]
        with self._patch(procs):
            self.assertEqual(harness._browser_pid(set()), 605)

    def test_no_psutil_returns_none(self):
        # _chromium_pids must degrade to None (RSS measurement is skipped)
        with mock.patch.dict(sys.modules, {"psutil": None}):
            self.assertIsNone(harness._chromium_pids())
            self.assertIsNone(harness._browser_pid(None))


if __name__ == "__main__":
    unittest.main()
