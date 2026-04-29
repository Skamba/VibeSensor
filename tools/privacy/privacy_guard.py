#!/usr/bin/env python3
"""Fail git hooks on high-confidence secret leaks."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_ZERO_SHA = "0" * 40
_SENSITIVE_PATH_PATTERNS = (
    re.compile(r"(^|/)\.secrets\.[^/]+$"),
    re.compile(r"(^|/)wifi-secrets\.env$"),
    re.compile(r"(^|/)vibesensor_network\.local\.h$"),
)
_TOKEN_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,}\b"), "GitHub token"),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "AWS access key"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"), "Slack token"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
)
_QUOTED_SECRET_ASSIGNMENT = re.compile(
    r"""(?ix)
    \b(?P<key>[A-Z0-9_-]*
        (?:PASSWORD|PASSWD|SECRET|TOKEN|API[_-]?KEY|PRIVATE[_-]?KEY|PSK|CLIENT[_-]?SECRET)
        [A-Z0-9_-]*)\b
    \s*[:=]\s*
    (?P<quote>['"])(?P<value>[^'"]+)(?P=quote)
    """
)
_ENV_SECRET_ASSIGNMENT = re.compile(
    r"""(?ix)
    ^
    (?P<key>[A-Z0-9_]*
        (?:PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|PRIVATE_KEY|PSK|CLIENT_SECRET)
        [A-Z0-9_]*)=(?P<value>[^\s#]+)
    """
)
_PLACEHOLDER_VALUES = {
    "***",
    "changeme",
    "dummy",
    "example",
    "example-password",
    "password",
    "placeholder",
    "redacted",
    "secret",
    "secret-passphrase",
    "secret123",
    "test",
    "test-password",
}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int | None
    message: str

    def format(self) -> str:
        location = self.path if self.line is None else f"{self.path}:{self.line}"
        return f"{location}: {self.message}"


def _run_git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def _repo_root() -> Path:
    result = _run_git(["rev-parse", "--show-toplevel"], cwd=Path.cwd())
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or "not inside a git repository")
    return Path(result.stdout.strip())


def _changed_paths(args: list[str], *, repo_root: Path) -> list[str]:
    result = _run_git(
        [*args, "-z", "--diff-filter=ACMR", "--name-only", "--"], cwd=repo_root
    )
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip())
    return [path for path in result.stdout.split("\0") if path]


def _diff(args: list[str], *, repo_root: Path) -> str:
    result = _run_git([*args, "--no-ext-diff", "--unified=0", "--"], cwd=repo_root)
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip())
    return result.stdout


def _is_sensitive_path(path: str) -> bool:
    return any(pattern.search(path) for pattern in _SENSITIVE_PATH_PATTERNS)


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().strip("'\"").lower()
    return (
        normalized in _PLACEHOLDER_VALUES
        or normalized.startswith("${")
        or normalized.startswith("$")
        or (normalized.startswith("<") and normalized.endswith(">"))
    )


def _looks_like_real_secret(value: str) -> bool:
    stripped = value.strip().strip("'\"")
    if _is_placeholder(stripped) or len(stripped) < 12:
        return False
    classes = sum(
        bool(pattern.search(stripped))
        for pattern in (
            re.compile(r"[a-z]"),
            re.compile(r"[A-Z]"),
            re.compile(r"\d"),
            re.compile(r"[^A-Za-z0-9]"),
        )
    )
    return classes >= 2


def _assignment_findings(path: str, line_number: int, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for match in _QUOTED_SECRET_ASSIGNMENT.finditer(text):
        if _looks_like_real_secret(match.group("value")):
            findings.append(
                Finding(
                    path,
                    line_number,
                    f"possible hard-coded secret in `{match.group('key')}`",
                )
            )
    env_match = _ENV_SECRET_ASSIGNMENT.search(text)
    if env_match and _looks_like_real_secret(env_match.group("value")):
        findings.append(
            Finding(
                path,
                line_number,
                f"possible hard-coded secret in `{env_match.group('key')}`",
            )
        )
    return findings


def _content_findings(path: str, line_number: int, text: str) -> list[Finding]:
    findings = [
        Finding(path, line_number, f"possible {label}")
        for pattern, label in _TOKEN_PATTERNS
        if pattern.search(text)
    ]
    findings.extend(_assignment_findings(path, line_number, text))
    return findings


def _scan_added_lines(diff_text: str) -> list[Finding]:
    findings: list[Finding] = []
    current_path = ""
    current_line: int | None = None
    for raw_line in diff_text.splitlines():
        if raw_line.startswith("+++ b/"):
            current_path = raw_line.removeprefix("+++ b/")
            current_line = None
            continue
        if raw_line.startswith("@@ "):
            match = re.search(r"\+(\d+)", raw_line)
            current_line = int(match.group(1)) if match else None
            continue
        if not current_path or current_line is None:
            continue
        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            findings.extend(_content_findings(current_path, current_line, raw_line[1:]))
            current_line += 1
        elif raw_line.startswith(" "):
            current_line += 1
    return findings


def _path_findings(paths: list[str]) -> list[Finding]:
    return [
        Finding(path, None, "sensitive local-only file must not be committed")
        for path in paths
        if _is_sensitive_path(path)
    ]


def _check(paths_args: list[str], diff_args: list[str], *, repo_root: Path) -> int:
    findings = _path_findings(_changed_paths(paths_args, repo_root=repo_root))
    findings.extend(_scan_added_lines(_diff(diff_args, repo_root=repo_root)))
    if not findings:
        return 0

    print(
        "[vibesensor privacy guard] Possible secret material detected:", file=sys.stderr
    )
    for finding in findings:
        print(f"  - {finding.format()}", file=sys.stderr)
    print(
        "[vibesensor privacy guard] Remove the secret or replace it with a documented placeholder.",
        file=sys.stderr,
    )
    return 1


def check_staged(repo_root: Path) -> int:
    return _check(["diff", "--cached"], ["diff", "--cached"], repo_root=repo_root)


def check_range(commit_range: str, repo_root: Path) -> int:
    if commit_range == _ZERO_SHA:
        return 0
    return _check(["diff", commit_range], ["diff", commit_range], repo_root=repo_root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check-staged", help="scan staged additions")
    range_parser = subparsers.add_parser(
        "check-range", help="scan additions in a commit range"
    )
    range_parser.add_argument("commit_range")
    args = parser.parse_args(argv)

    repo_root = _repo_root()
    if args.command == "check-staged":
        return check_staged(repo_root)
    if args.command == "check-range":
        return check_range(args.commit_range, repo_root)
    parser.error(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
