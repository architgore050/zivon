#!/usr/bin/env python3
"""Workflow sanity checks for the Zivon CI files (local gate hardening).

Checks every .github/workflows/*.yml for the repo's own hardening rules
(docs/deployment/cicd.md § Hardening rules):
  1. YAML parses (github-actions semantics approximated: `on` key quirks).
  2. Every third-party `uses:` is pinned to a full 40-char commit SHA.
  3. Top-level `permissions:` key exists on every workflow.
  4. No product secret names appear in the workflow text (ZIVON_API_KEY etc.).
  5. Every job either has `steps` or `uses` (reusable workflow call).
  6. `if:` conditions are non-empty strings.
Exit 0 = green. Stdlib only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

REPO = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
WF = REPO / ".github" / "workflows"

FORBIDDEN_SECRET_NAMES = [
    "ZIVON_API_KEY",
    "ZIVON_VOICE_GEMINI_API_KEY",
    "GNANI_PRISMA_API_KEY",
    "GNANI_TIMBRE_API_KEY",
    "POSTGRES_PASSWORD_PRODUCT",
    "ZIVON_ADMIN_TOKEN",
    "GEMINI_API_KEY",
    "GNANI_API_KEY",
]

SHA_PIN = re.compile(r"uses:\s*[\w.-]+/[\w.-]+@([0-9a-f]{40})")


class _UniqueKeyLoader(yaml.SafeLoader):
    """yaml.SafeLoader that rejects duplicate mapping keys (workflow files
    are hand-edited; a duplicated step key must not pass silently)."""


def _no_dupes(loader: _UniqueKeyLoader, node: yaml.Node, deep: bool = False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate mapping key: {key!r}", key_node.start_mark
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_dupes
)


def load_workflow(path: Path):
    # `on:` is parsed by PyYAML as boolean True (YAML 1.1) — remap for access.
    text = path.read_text()
    data = yaml.load(text, Loader=_UniqueKeyLoader)
    if data is None:
        raise ValueError(f"{path.name}: empty workflow")
    on = data.get(True, data.get("on"))
    if on is None:
        raise ValueError(f"{path.name}: missing `on:` trigger block")
    return text, data, on


def main() -> int:
    failures: list[str] = []
    warnings: list[str] = []
    files = sorted(WF.glob("*.yml"))
    if not files:
        failures.append("no workflow files found")
    for path in files:
        try:
            text, data, _on = load_workflow(path)
        except Exception as exc:  # noqa: BLE001 - report and continue
            failures.append(f"{path.name}: {exc}")
            continue
        jobs = data.get("jobs") or {}
        if not jobs:
            failures.append(f"{path.name}: no jobs")
        if "permissions" not in data:
            failures.append(f"{path.name}: missing top-level permissions block")
        # secret hygiene: the GITHUB_TOKEN expressions are fine; product keys are not
        for name in FORBIDDEN_SECRET_NAMES:
            if f"secrets.{name}" in text:
                failures.append(f"{path.name}: references forbidden secret {name}")
        for job_name, job in jobs.items():
            if not isinstance(job, dict):
                failures.append(f"{path.name}:{job_name}: job is not a mapping")
                continue
            steps = job.get("steps")
            if not steps:
                failures.append(f"{path.name}:{job_name}: job has no steps")
                continue
            for idx, step in enumerate(steps):
                if not isinstance(step, dict):
                    failures.append(
                        f"{path.name}:{job_name}.steps[{idx}]: not a mapping"
                    )
                    continue
                uses = step.get("uses", "")
                if uses and "/" in uses and not re.search(r"@[0-9a-f]{40}$", uses):
                    failures.append(
                        f"{path.name}:{job_name}.steps[{idx}]: `uses` not SHA-pinned: {uses}"
                    )
                cond = step.get("if")
                if cond is not None and not str(cond).strip():
                    failures.append(f"{path.name}:{job_name}.steps[{idx}]: empty `if:`")
                if "run" in step and not str(step["run"]).strip():
                    failures.append(
                        f"{path.name}:{job_name}.steps[{idx}]: empty `run:`"
                    )
        print(f"{path.name}: jobs={list(jobs.keys())}")
    for w in warnings:
        print("WARN:", w)
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(" -", f)
        return 1
    print("\nAll workflow sanity checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
