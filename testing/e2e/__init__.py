"""F11 acceptance-flow E2E suite — hermetic, key-free.

Run from the repo root:

    python -m unittest discover -s testing/e2e -t .
    # or
    python -m pytest testing/e2e -q

Level 1 modules (`test_flow_*.py`) drive the ten §17.1 acceptance flows at the
HTTP layer with FastAPI's TestClient against the real app: seeded hermetic
data flows through the real importer/store code paths, grading happens
server-side, and the state matrix's honest states are asserted where reachable
(guest guards, empty banks, answer-key withholding, idempotent submits). No
network, no keys, no browser.

Level 2 (`test_e2e_browser.py`) boots the real app under uvicorn on
127.0.0.1 with dev env and runs a few Chromium smoke tests over the most
critical UI paths. It skips with a reason when Playwright/Chromium is
unavailable — a skip is never reported as a pass.
"""
