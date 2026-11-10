#!/usr/bin/env python3
"""Workflow sanity checks for the Zivon CI files (local gate hardening).

Checks every workflow under `.github/workflows/` (*.yml AND *.yaml) and every
composite action under `.github/actions/**/action.yml|action.yaml` for the
repo's own hardening rules (docs/deployment/cicd.md § Hardening rules):

  1. YAML parses (github-actions semantics approximated: `on` key quirks).
  2. Every third-party `uses:` — step-level AND job-level reusable-workflow
     calls — is pinned to a full 40-char commit SHA (`./local` paths exempt).
  3. Top-level `permissions:` key exists on every workflow, and
     `permissions: write-all` is rejected at workflow AND job level.
  4. `pull_request_target` is rejected (fork code with a write token).
  5. No product secret names appear in the workflow text — dot AND bracket
     reference forms (`secrets.NAME` / `secrets['NAME']`). Reported by file +
     rule only: the matched expression never reaches the job log.
  6. Every job either has `steps` or a reusable-workflow `uses`.
  7. `if:` conditions are non-empty strings; `run:` bodies are non-empty.

Run the rule fixtures with `--self-test` (CI's quality job runs it before the
real scan, so the checker itself cannot silently rot). Exit 0 = green.
Stdlib + PyYAML only.
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

import yaml

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

# A `uses:` value is SHA-pinned when the part after `@` is a full commit hash.
SHA_PINNED = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
LOCAL_ACTION = re.compile(r"^\./")
# Both `secrets.NAME` and `secrets['NAME']` / `secrets["NAME"]`.
SECRET_REF = re.compile(r"secrets\s*[.\[]\s*['\"]?([A-Za-z0-9_]+)")


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


def _load(path: Path):
    return yaml.load(path.read_text(), Loader=_UniqueKeyLoader)


def _check_uses(value: object, where: str, failures: list[str]) -> None:
    """Rule 2: a non-local `uses:` must carry a full commit SHA."""
    if not value:
        return
    uses = str(value)
    if LOCAL_ACTION.match(uses):
        return
    if not SHA_PINNED.match(uses):
        failures.append(f"{where}: `uses` not SHA-pinned: {uses}")


def _check_permissions(value: object, where: str, failures: list[str]) -> None:
    """Rule 3: `write-all` is forbidden wherever permissions are set."""
    if isinstance(value, str) and value.strip() == "write-all":
        failures.append(f"{where}: `permissions: write-all` is forbidden")


def _check_secrets(text: str, name: str, failures: list[str]) -> None:
    """Rule 5: no product secret names, in dot or bracket reference form.

    The report names the FILE and the rule only — never the matched
    expression or the secret name it resolved to. A `secrets.X` reference is
    the taint source for CodeQL's clear-text-logging query, and this checker's
    findings go to stdout (the workflow step log); echoing the match would
    make the gate itself the leak. One finding per file is also enough to act
    on: the rule is "no product secret references at all".
    """
    referenced = set(SECRET_REF.findall(text))
    if referenced.intersection(FORBIDDEN_SECRET_NAMES):
        failures.append(
            f"{name}: references a forbidden product secret name "
            "(rule 5: product secrets never reach CI; use runtime config)"
        )


def _check_steps(
    steps: object, where: str, failures: list[str], required: bool
) -> None:
    if not steps:
        if required:
            failures.append(f"{where}: job has no steps")
        return
    if not isinstance(steps, list):
        failures.append(f"{where}: steps is not a list")
        return
    for idx, step in enumerate(steps):
        label = f"{where}.steps[{idx}]"
        if not isinstance(step, dict):
            failures.append(f"{label}: not a mapping")
            continue
        _check_uses(step.get("uses"), label, failures)
        cond = step.get("if")
        if cond is not None and not str(cond).strip():
            failures.append(f"{label}: empty `if:`")
        if "run" in step and not str(step["run"]).strip():
            failures.append(f"{label}: empty `run:`")


def check_workflow(path: Path, name: str) -> list[str]:
    failures: list[str] = []
    try:
        data = _load(path)
    except Exception as exc:  # noqa: BLE001 - report and continue
        return [f"{name}: {exc}"]
    if not isinstance(data, dict):
        return [f"{name}: workflow is not a mapping"]

    _check_secrets(path.read_text(), name, failures)

    # `on:` is parsed by PyYAML as boolean True (YAML 1.1) — accept both keys.
    on = data.get(True, data.get("on"))
    if on is None:
        failures.append(f"{name}: missing `on:` trigger block")
    elif isinstance(on, dict) and "pull_request_target" in on:
        # Rule 4: fork-code-with-write-token pattern; this repo never allows it.
        failures.append(
            f"{name}: `pull_request_target` is forbidden (fork code with a write token)"
        )

    if "permissions" not in data:
        failures.append(f"{name}: missing top-level permissions block")
    _check_permissions(data.get("permissions"), name, failures)

    jobs = data.get("jobs") or {}
    if not jobs:
        failures.append(f"{name}: no jobs")
    if not isinstance(jobs, dict):
        return failures + [f"{name}: jobs is not a mapping"]
    for job_name, job in jobs.items():
        where = f"{name}:{job_name}"
        if not isinstance(job, dict):
            failures.append(f"{where}: job is not a mapping")
            continue
        _check_permissions(job.get("permissions"), where, failures)
        job_uses = job.get("uses")
        if job_uses is not None:
            # Rule 6: a reusable-workflow call needs no `steps`, but its
            # `uses` is still subject to the SHA-pin rule.
            _check_uses(job_uses, where, failures)
            if job.get("steps") is None:
                continue
        _check_steps(job.get("steps"), where, failures, required=True)
    return failures


def check_action(path: Path, name: str) -> list[str]:
    """Composite actions: no `on`/`jobs`/`permissions` of their own — only the
    step-level hardening rules apply (`runs.steps`)."""
    failures: list[str] = []
    try:
        data = _load(path)
    except Exception as exc:  # noqa: BLE001 - report and continue
        return [f"{name}: {exc}"]
    if not isinstance(data, dict):
        return [f"{name}: action is not a mapping"]
    _check_secrets(path.read_text(), name, failures)
    runs = data.get("runs") or {}
    if isinstance(runs, dict) and runs.get("using") == "composite":
        _check_steps(runs.get("steps"), name, failures, required=True)
    return failures


def _discover(repo: Path) -> list[tuple[Path, str]]:
    """Every workflow *.yml AND *.yaml plus .github/actions/**/action.yml|yaml."""
    files: list[tuple[Path, str]] = []
    wf = repo / ".github" / "workflows"
    for pattern in ("*.yml", "*.yaml"):
        files.extend((p, p.name) for p in sorted(wf.glob(pattern)))
    actions = repo / ".github" / "actions"
    if actions.is_dir():
        for pattern in ("action.yml", "action.yaml"):
            for p in sorted(actions.rglob(pattern)):
                files.append((p, str(p.relative_to(repo))))
    return files


def scan(repo: Path) -> tuple[list[str], list[tuple[Path, str]]]:
    failures: list[str] = []
    files = _discover(repo)
    if not files:
        failures.append("no workflow or action files found")
    for path, name in files:
        if path.parent.name == "actions" or "/actions/" in path.as_posix():
            failures.extend(check_action(path, name))
        else:
            failures.extend(check_workflow(path, name))
    return failures, files


# ---------------------------------------------------------------------------
# Rule fixtures — every rule above has a positive and/or negative case.
# ---------------------------------------------------------------------------
_SHA = "a" * 40


def _selftest() -> int:
    clean = f"""
name: clean
on:
  pull_request:
    branches: [main]
permissions: {{}}
jobs:
  q:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@{_SHA}
      - run: echo hi
  reuse:
    uses: octo/repo/.github/workflows/x.yml@{_SHA}
"""

    def run(text: str, filename: str = "wf.yml", subdir: str = "workflows"):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            base = repo / ".github" / subdir
            base.mkdir(parents=True)
            (base / filename).write_text(text)
            return scan(repo)[0]

    cases: list[tuple[str, str, str, bool, str, str]] = [
        (
            "clean workflow passes",
            clean,
            "wf.yml",
            False,
            "workflows",
            "",
        ),
        (
            "unpinned step action",
            "name: x\non: push\npermissions: {}\njobs:\n  q:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v7\n",
            "wf.yml",
            True,
            "workflows",
            "`uses` not SHA-pinned: actions/checkout@v7",
        ),
        (
            "unpinned reusable-workflow job",
            "name: x\non: push\npermissions: {}\njobs:\n  r:\n    uses: octo/repo/.github/workflows/x.yml@main\n",
            "wf.yml",
            True,
            "workflows",
            "`uses` not SHA-pinned: octo/repo/.github/workflows/x.yml@main",
        ),
        (
            "local action is exempt from the pin",
            "name: x\non: push\npermissions: {}\njobs:\n  q:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: ./.github/actions/foo\n",
            "wf.yml",
            False,
            "workflows",
            "",
        ),
        (
            "job with no steps and no uses",
            "name: x\non: push\npermissions: {}\njobs:\n  empty:\n    runs-on: ubuntu-latest\n",
            "wf.yml",
            True,
            "workflows",
            "job has no steps",
        ),
        (
            "bracket-form forbidden secret",
            "name: x\non: push\npermissions: {}\njobs:\n  q:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo \"${{ secrets['ZIVON_API_KEY'] }}\"\n",
            "wf.yml",
            True,
            "workflows",
            "references a forbidden product secret name",
        ),
        (
            "write-all permissions rejected",
            "name: x\non: push\npermissions: write-all\njobs:\n  q:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n",
            "wf.yml",
            True,
            "workflows",
            "`permissions: write-all` is forbidden",
        ),
        (
            "pull_request_target rejected",
            "name: x\non:\n  pull_request_target: {}\npermissions: {}\njobs:\n  q:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n",
            "wf.yml",
            True,
            "workflows",
            "`pull_request_target` is forbidden",
        ),
        (
            "*.yaml workflows are discovered",
            "name: x\non: push\npermissions: {}\njobs:\n  q:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v7\n",
            "extra.yaml",
            True,
            "workflows",
            "`uses` not SHA-pinned",
        ),
        (
            "composite action steps are checked",
            "name: x\nruns:\n  using: composite\n  steps:\n    - uses: actions/checkout@v7\n",
            "action.yml",
            True,
            "actions/foo",
            "`uses` not SHA-pinned",
        ),
    ]

    failed = 0
    for label, text, filename, expect_fail, subdir, needle in cases:
        failures = run(text, filename=filename, subdir=subdir)
        joined = "\n".join(failures)
        if expect_fail:
            if needle not in joined:
                failed += 1
                print(f"SELFTEST FAIL: {label}: missing {needle!r}\n  got: {failures}")
            else:
                print(f"selftest ok: {label}")
        elif failures:
            failed += 1
            print(f"SELFTEST FAIL: {label}: expected no failures, got {failures}")
        else:
            print(f"selftest ok: {label}")
    if failed:
        print(f"\n{failed} self-test case(s) failed.")
        return 1
    print("\nAll workflow-checker self-tests passed.")
    return 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return _selftest()
    repo = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parents[1]
    failures, files = scan(repo)
    for path, name in files:
        print(f"{name}: checked")
    if failures:
        print("\nFAILURES:")
        for failure in failures:
            print(" -", failure)
        return 1
    print("\nAll workflow sanity checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
