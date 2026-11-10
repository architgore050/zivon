"""kubectl wrappers — the dashboard's cluster probe (V1's manual-only rule,
V2's Job status + log tail).

The dashboard is a remote control for the SAME scripts (dashboard-spec.md
§5: it adds no third path), and its run/test views read Job status the way
`scripts/trigger-tests.sh` and `scripts/logs-factory-run.sh` do — via
label/name lookups. A missing kubectl (local dev, unit tests) is an honest
"cluster unavailable" state, never a fabricated one. RBAC: the pod's
ServiceAccount needs the read + create-jobs grants from integration note
I-1 (the infra agent owns the Role wiring).
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

NAMESPACE = "zivon"


def kubectl(args: list[str], timeout_s: int = 15) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["kubectl", *args],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return 127, "", "kubectl not available"
    except subprocess.TimeoutExpired:
        return 124, "", "kubectl timed out"


def cluster_available() -> bool:
    rc, _, _ = kubectl(["get", "ns", NAMESPACE, "-o", "name"], timeout_s=10)
    return rc == 0


def list_jobs() -> list[dict[str, Any]]:
    """All Jobs in the namespace, newest first (V1/V2 rows)."""
    rc, out, _ = kubectl(["get", "jobs", "-n", NAMESPACE, "-o", "json"])
    if rc != 0:
        return []
    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        return []
    jobs: list[dict[str, Any]] = []
    for item in payload.get("items", []):
        metadata = item.get("metadata", {})
        status = item.get("status", {})
        jobs.append(
            {
                "name": metadata.get("name", ""),
                "task": (metadata.get("labels") or {}).get("task", ""),
                "active": status.get("active", 0),
                "succeeded": status.get("succeeded", 0),
                "failed": status.get("failed", 0),
                "start_time": status.get("startTime"),
                "completion_time": status.get("completionTime"),
            }
        )
    jobs.sort(key=lambda job: job.get("start_time") or "", reverse=True)
    return jobs


def factory_run_in_progress() -> bool:
    """The manual-only rule, visible: a run is 'running' only while a
    factory-run-* Job is active (dashboard-spec.md §4 V1)."""
    return any(
        job["name"].startswith("factory-run-") and job["active"] for job in list_jobs()
    )


def test_jobs(limit: int = 10) -> list[dict[str, Any]]:
    """Suite runs: scheduled test-suite-* and manual test-manual-*/startup."""
    jobs = [job for job in list_jobs() if job["name"].startswith("test-")]
    return jobs[:limit]


def job_log_tail(job_name: str, lines: int = 40) -> str:
    rc, out, err = kubectl(
        ["logs", f"job/{job_name}", "-n", NAMESPACE, f"--tail={lines}"]
    )
    if rc != 0:
        return f"(log tail unavailable: {err.strip()[:120] or 'kubectl error'})"
    return out[-4000:]
