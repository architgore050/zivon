"""Navigation registry for the server-rendered shell.

A nav entry is added only when its route exists: a link that lands on a 404 is
a dead control. Feature workstreams append their entry here in the same PR
that lands the route (F3 dashboard/progress, F5 practice, F6 speaking,
F7 tests/series).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class NavItem:
    """One top-level app/public navigation link."""

    key: str
    label: str
    href: str


# The signed-in shell. Today `/app` is the only app route that exists; the
# rest of the entries land with their owning workstream.
APP_NAV: Final[tuple[NavItem, ...]] = (
    NavItem("dashboard", "Dashboard", "/app"),
    NavItem("courses", "Courses", "/courses"),
)

# The public shell is used by the auth/error pages F0 renders. Public
# discovery pages themselves stay static and carry their own nav (F1).
PUBLIC_NAV: Final[tuple[NavItem, ...]] = (
    NavItem("courses", "Courses", "/courses"),
    NavItem("method", "Method", "/method/"),
    NavItem("about", "About", "/about/"),
)


def nav_for(shell_kind: str) -> tuple[NavItem, ...]:
    """Return the nav set for a shell variant (`app` or anything else)."""
    return APP_NAV if shell_kind == "app" else PUBLIC_NAV


def active_nav(path: str, items: tuple[NavItem, ...]) -> str | None:
    """Return the key of the most specific nav item matching `path`.

    Longest href wins, so `/app/progress` selects a future `/app/progress`
    entry over `/app` instead of lighting two links at once.
    """
    matches = [
        item
        for item in items
        if path == item.href or path.startswith(item.href.rstrip("/") + "/")
    ]
    if not matches:
        return None
    return max(matches, key=lambda item: len(item.href)).key


__all__ = [
    "APP_NAV",
    "PUBLIC_NAV",
    "NavItem",
    "active_nav",
    "nav_for",
]
