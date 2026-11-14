#!/usr/bin/env python3
"""Validate agent-skill bundles without third-party dependencies.

Checks, per skill directory:
  * SKILL.md exists and its YAML frontmatter parses
  * `name` and `description` are present, valid, and sane
  * `name` matches the directory name
  * relative Markdown links resolve to real files
  * no secret-shaped strings or obvious PII
  * no TODO/TBD/FIXME placeholders in the entry files
  * SKILL.md stays within the progressive-disclosure budget
  * every references/*.md file is mentioned from SKILL.md
  * skill names are unique across the scanned tree

Modes:
  default   scan the skills tree, report errors and warnings, exit non-zero
            only on errors (legacy bundles without SKILL.md are warnings)
  --strict  treat warnings as errors and require SKILL.md + README.md per
            named bundle; use for a new bundle in CI

Usage:
  python3 scripts/check_skills.py
  python3 scripts/check_skills.py --strict --bundle skills/skill-creation
  python3 scripts/check_skills.py --json

Stdlib only. Exit 0 = no errors (or no warnings in strict mode).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = REPO / "skills"

# Directories inside a bundle that are support material, not nested skills.
NON_SKILL_DIRS = {
    "references",
    "templates",
    "scripts",
    "assets",
    "vendored",
    "node_modules",
    "__pycache__",
}
MAX_BODY_LINES = 500
MIN_STRICT_DESCRIPTION = 80
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`]*`")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
SECRET_PATTERNS = (
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bghp_[A-Za-z0-9]{36}\b")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("password_assignment", re.compile(r"""(?i)\bpassword\s*=\s*['"][^'"]{6,}['"]""")),
)
PLACEHOLDER_RE = re.compile(r"\b(TODO|TBD|FIXME|XXX)\b")


@dataclass(frozen=True)
class Finding:
    level: str  # "error" | "warning"
    code: str
    path: Path
    line: int
    message: str

    def render(self) -> str:
        location = f"{self.path}"
        if self.line:
            location += f":{self.line}"
        return f"{self.level.upper():7} [{self.code}] {location}: {self.message}"


@dataclass
class Skill:
    directory: Path
    bundle: Path
    name: str
    description: str
    body_lines: int


class FrontmatterError(ValueError):
    """Raised when a SKILL.md has no parseable YAML frontmatter."""


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_frontmatter(text: str) -> tuple[dict[str, str], int]:
    """Return (fields, body_start_line_index). Handles simple nested metadata."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise FrontmatterError("file must start with a '---' frontmatter block")
    closing = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            closing = index
            break
    if closing is None:
        raise FrontmatterError("frontmatter block has no closing '---'")

    fields: dict[str, str] = {}
    index = 1
    while index < closing:
        raw = lines[index]
        if not raw.strip() or raw.lstrip().startswith("#"):
            index += 1
            continue
        if raw.startswith((" ", "\t")):
            # Nested value (metadata, lists). Top-level keys only for this check.
            index += 1
            continue
        key, separator, value = raw.partition(":")
        if not separator:
            index += 1
            continue
        key = key.strip()
        value = value.strip()
        if value in {"|", ">", "|-", ">-"}:
            block: list[str] = []
            index += 1
            while index < closing and (
                not lines[index].strip() or lines[index].startswith((" ", "\t"))
            ):
                block.append(lines[index].strip())
                index += 1
            fields[key] = " ".join(part for part in block if part)
            continue
        fields[key] = _strip_quotes(value)
        index += 1
    return fields, closing + 1


def _visible_markdown(text: str) -> str:
    text = FENCE_RE.sub("", text)
    return INLINE_CODE_RE.sub("", text)


def _check_links(
    skill: Skill, body: str, body_start: int, findings: list[Finding]
) -> None:
    visible = _visible_markdown(body)
    for match in LINK_RE.finditer(visible):
        line = body_start + visible.count("\n", 0, match.start()) + 1
        target = match.group(1).strip()
        if not target or target.startswith(
            ("#", "http://", "https://", "mailto:", "tel:")
        ):
            continue
        target = target.split("#", 1)[0].split("?", 1)[0]
        if not target:
            continue
        resolved = (skill.directory / target).resolve()
        try:
            resolved.relative_to(skill.bundle.resolve())
        except ValueError:
            findings.append(
                Finding(
                    "warning",
                    "link-outside-bundle",
                    skill.directory / "SKILL.md",
                    line,
                    f"relative link escapes the bundle: {target}",
                )
            )
            continue
        if not resolved.exists():
            findings.append(
                Finding(
                    "error",
                    "broken-link",
                    skill.directory / "SKILL.md",
                    line,
                    f"relative link does not resolve: {target}",
                )
            )


def _scan_text_for_secrets(path: Path, findings: list[Finding]) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return
    for code, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            findings.append(
                Finding(
                    "error", f"secret:{code}", path, line, "secret-shaped string found"
                )
            )
    for match in EMAIL_RE.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        findings.append(
            Finding(
                "warning",
                "possible-pii",
                path,
                line,
                f"email address found: {match.group(0)} (confirm it is intentional)",
            )
        )


def validate_skill(directory: Path, bundle: Path) -> tuple[Skill | None, list[Finding]]:
    findings: list[Finding] = []
    skill_file = directory / "SKILL.md"
    if not skill_file.is_file():
        return None, findings

    try:
        text = skill_file.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [Finding("error", "unreadable", skill_file, 0, str(exc))]

    try:
        fields, body_start = parse_frontmatter(text)
    except FrontmatterError as exc:
        return None, [Finding("error", "frontmatter", skill_file, 0, str(exc))]

    name = fields.get("name", "").strip()
    description = fields.get("description", "").strip()

    if not name:
        findings.append(
            Finding("error", "name-missing", skill_file, 0, "frontmatter has no 'name'")
        )
    else:
        if not NAME_RE.match(name):
            findings.append(
                Finding(
                    "error",
                    "name-format",
                    skill_file,
                    0,
                    f"name {name!r} must be lowercase kebab-case (a-z, 0-9, single hyphens)",
                )
            )
        if len(name) > 64:
            findings.append(
                Finding("error", "name-length", skill_file, 0, "name exceeds 64 chars")
            )
        if name != directory.name:
            findings.append(
                Finding(
                    "warning",
                    "name-directory-mismatch",
                    skill_file,
                    0,
                    f"name {name!r} does not match directory {directory.name!r}",
                )
            )

    if not description:
        findings.append(
            Finding(
                "error",
                "description-missing",
                skill_file,
                0,
                "frontmatter has no 'description'",
            )
        )
    else:
        if len(description) > 1024:
            findings.append(
                Finding(
                    "error",
                    "description-length",
                    skill_file,
                    0,
                    f"description is {len(description)} chars (max 1024)",
                )
            )
        if "<" in description or ">" in description:
            findings.append(
                Finding(
                    "warning",
                    "description-xml",
                    skill_file,
                    0,
                    "description contains < or >",
                )
            )
        lowered = description.lower()
        if lowered.startswith(("i can ", "you can ", "this skill ")):
            findings.append(
                Finding(
                    "warning",
                    "description-person",
                    skill_file,
                    0,
                    "write the description in third person (what it does + when to use it)",
                )
            )

    body = "\n".join(text.splitlines()[body_start:])
    body_lines = len(body.splitlines())
    if body_lines > MAX_BODY_LINES:
        findings.append(
            Finding(
                "warning",
                "body-too-long",
                skill_file,
                0,
                f"body is {body_lines} lines; move detail into references/ (budget {MAX_BODY_LINES})",
            )
        )

    for match in PLACEHOLDER_RE.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        findings.append(
            Finding(
                "warning",
                "placeholder",
                skill_file,
                line,
                f"placeholder token {match.group(0)}",
            )
        )

    skill = Skill(directory, bundle, name or directory.name, description, body_lines)
    _check_links(skill, body, body_start, findings)

    references_dir = directory / "references"
    if references_dir.is_dir():
        mentioned = "references/" in body
        for ref in sorted(references_dir.glob("*.md")):
            if not mentioned and ref.name not in body:
                findings.append(
                    Finding(
                        "warning",
                        "reference-unmentioned",
                        skill_file,
                        0,
                        f"references/{ref.name} is never mentioned from SKILL.md",
                    )
                )

    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.suffix.lower() in {
            ".md",
            ".py",
            ".sh",
            ".js",
            ".ts",
            ".json",
            ".yaml",
            ".yml",
            ".txt",
        }:
            _scan_text_for_secrets(path, findings)

    return skill, findings


def _iter_skill_dirs(bundle: Path, max_depth: int = 3) -> list[Path]:
    """Find skill directories under a bundle, without descending into one."""
    found: list[Path] = []
    if (bundle / "SKILL.md").is_file():
        return [bundle]

    def walk(directory: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            children = sorted(directory.iterdir())
        except OSError:
            return
        for child in children:
            if not child.is_dir() or child.name.startswith("."):
                continue
            if child.name in NON_SKILL_DIRS:
                continue
            if (child / "SKILL.md").is_file():
                found.append(child)
                continue
            walk(child, depth + 1)

    walk(bundle, 1)
    return found


def validate_bundle(bundle: Path, strict: bool) -> tuple[list[Skill], list[Finding]]:
    findings: list[Finding] = []
    skills: list[Skill] = []
    if not bundle.is_dir():
        return [], [
            Finding("error", "bundle-missing", bundle, 0, "bundle directory not found")
        ]

    if strict:
        for required in ("SKILL.md", "README.md"):
            if not (bundle / required).is_file():
                findings.append(
                    Finding(
                        "error",
                        "required-file",
                        bundle / required,
                        0,
                        f"missing {required}",
                    )
                )

    candidates = _iter_skill_dirs(bundle)

    if not candidates:
        findings.append(
            Finding(
                "warning",
                "no-skill",
                bundle,
                0,
                "bundle contains no SKILL.md (flat or legacy layout; not validated)",
            )
        )
        return [], findings

    for directory in candidates:
        skill, skill_findings = validate_skill(directory, bundle)
        findings.extend(skill_findings)
        if skill is not None:
            skills.append(skill)
            if strict and len(skill.description) < MIN_STRICT_DESCRIPTION:
                findings.append(
                    Finding(
                        "warning",
                        "description-thin",
                        directory / "SKILL.md",
                        0,
                        f"description is {len(skill.description)} chars; strict mode wants "
                        f">= {MIN_STRICT_DESCRIPTION} to carry triggers",
                    )
                )
            if strict and "use when" not in skill.description.lower():
                findings.append(
                    Finding(
                        "warning",
                        "description-no-trigger",
                        directory / "SKILL.md",
                        0,
                        "description does not contain 'Use when ...'; say when to trigger",
                    )
                )

    return skills, findings


def discover_bundles(root: Path) -> list[Path]:
    bundles: list[Path] = []
    if not root.is_dir():
        return bundles
    for child in sorted(root.iterdir()):
        if (
            child.is_dir()
            and child.name not in NON_SKILL_DIRS
            and not child.name.startswith(".")
        ):
            bundles.append(child)
    return bundles


def check(
    root: Path, named: list[Path], strict: bool
) -> tuple[list[Skill], list[Finding]]:
    bundles = (
        [path if path.is_absolute() else REPO / path for path in named]
        if named
        else discover_bundles(root)
    )
    all_skills: list[Skill] = []
    all_findings: list[Finding] = []

    for bundle in bundles:
        skills, findings = validate_bundle(bundle, strict)
        all_skills.extend(skills)
        all_findings.extend(findings)

    seen: dict[str, Path] = {}
    for skill in all_skills:
        previous = seen.get(skill.name)
        if previous is not None:
            all_findings.append(
                Finding(
                    "error",
                    "duplicate-name",
                    skill.directory / "SKILL.md",
                    0,
                    f"skill name {skill.name!r} also used by {previous}",
                )
            )
        else:
            seen[skill.name] = skill.directory / "SKILL.md"

    return all_skills, all_findings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help="skills tree to scan (default: skills/)",
    )
    parser.add_argument(
        "--bundle",
        type=Path,
        action="append",
        default=[],
        metavar="PATH",
        help="validate one bundle (repeatable); overrides --root",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat warnings as errors and require SKILL.md + README.md",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--quiet", action="store_true", help="only the summary")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    skills, findings = check(args.root, args.bundle, args.strict)

    failed = any(f.level == "error" for f in findings)
    if args.strict and any(f.level == "warning" for f in findings):
        failed = True

    if args.json:
        print(
            json.dumps(
                {
                    "skills": [
                        {
                            "name": skill.name,
                            "path": str(skill.directory),
                            "bundle": str(skill.bundle),
                            "body_lines": skill.body_lines,
                        }
                        for skill in skills
                    ],
                    "findings": [
                        {
                            "level": finding.level,
                            "code": finding.code,
                            "path": str(finding.path),
                            "line": finding.line,
                            "message": finding.message,
                        }
                        for finding in findings
                    ],
                    "summary": {
                        "skills": len(skills),
                        "errors": sum(f.level == "error" for f in findings),
                        "warnings": sum(f.level == "warning" for f in findings),
                        "ok": not failed,
                    },
                },
                indent=2,
            )
        )
        return 1 if failed else 0

    if not args.quiet:
        for finding in findings:
            print(finding.render())
    errors = sum(f.level == "error" for f in findings)
    warnings = sum(f.level == "warning" for f in findings)
    status = "OK" if not failed else "FAIL"
    print(f"{status}: {len(skills)} skill(s), {errors} error(s), {warnings} warning(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
