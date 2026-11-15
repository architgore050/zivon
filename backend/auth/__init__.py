"""Account auth, sessions, and profile logic for the full-frontend product.

The device-pseudonymous voice stack (`backend/identity.py`) is untouched: guest
devices keep working, and an account is an additive identity that a device can
be linked to. The public surface is `backend/routes/auth.py` +
`backend/routes/me.py`; everything security-relevant lives here so the routes
stay thin. Design record: `docs/backend/adr/0029-accounts-and-session-cookies.md`.
"""

from __future__ import annotations

from .service import AuthContext, AuthService, SessionGrant

__all__ = ["AuthContext", "AuthService", "SessionGrant"]
