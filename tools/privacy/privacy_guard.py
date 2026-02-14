from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

ALLOWED_EMAIL_RE = re.compile(r"(^.+@users\.noreply\.github\.com$)|(^noreply@github\.com$)")
PERSONAL_EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+-]+@(gmail\.com|outlook\.com|hotmail\.com|yahoo\.com)",
    re.IGNORECASE,
)

SENSITIVE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("GitHub token", re.compile(r"\b(ghp|gho)_[A-Za-z0-9]{20,}\b")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("OpenAI key-like token", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("Windows local user path", re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+")),
    ("Linux home path", re.compile(r"/home/[^/\s]+")),
    ("macOS home path", re.compile(r"/Users/[^/\s]+")),
]


def run_git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout


def check_local_git_email() -> list[str]:
    issues: list[str] = []
    try:
        email = run_git(["config", "--get", "user.email"]).strip()
    except subprocess.CalledProcessError:
        return ["git user.email is not set"]
    if not ALLOWED_EMAIL_RE.search(email):
        issues.append(
            f"git user.email '{email}' is not allowed; use a GitHub no-reply address."
        )
    return issues


def check_commit_range(commit_range: str) -> list[str]:
    issues: list[str] = []
    try:
        rows = run_git(["log", "--format=%H|%ae|%ce", commit_range]).splitlines()
    except subprocess.CalledProcessError:
        if ".." in commit_range:
            fallback = commit_range.rsplit("..", 1)[1]
            try:
                rows = run_git(["log", "--format=%H|%ae|%ce", fallback]).splitlines()
            except subprocess.CalledProcessError:
                return [f"invalid commit range: {commit_range}"]
        else:
            return [f"invalid commit range: {commit_range}"]

    for row in rows:
        if not row.strip():
            continue
        commit, author_email, committer_email = row.split("|", 2)
        if not ALLOWED_EMAIL_RE.search(author_email):
            issues.append(f"{commit}: disallowed author email: {author_email}")
        if not ALLOWED_EMAIL_RE.search(committer_email):
            issues.append(f"{commit}: disallowed committer email: {committer_email}")
    return issues


def check_text_blob(label: str, text: str) -> list[str]:
    if label.endswith("tools/privacy/privacy_guard.py"):
        return []
    issues: list[str] = []
    if PERSONAL_EMAIL_RE.search(text):
        issues.append(f"{label}: contains personal email domain")
    for name, pattern in SENSITIVE_PATTERNS:
        if pattern.search(text):
            issues.append(f"{label}: contains {name}")
    return issues


def iter_staged_files() -> list[str]:
    out = run_git(["diff", "--cached", "--name-only", "-z"])
    if not out:
        return []
    return [p for p in out.split("\x00") if p]


def check_staged() -> list[str]:
    issues = check_local_git_email()
    for path in iter_staged_files():
        try:
            blob = run_git(["show", f":{path}"])
        except subprocess.CalledProcessError:
            continue
        issues.extend(check_text_blob(f"staged:{path}", blob))
    return issues


def check_tree() -> list[str]:
    issues: list[str] = []
    out = run_git(["ls-files", "-z"])
    for raw_path in [p for p in out.split("\x00") if p]:
        full_path = REPO_ROOT / raw_path
        try:
            text = full_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        issues.extend(check_text_blob(raw_path, text))
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Privacy guard for commits and tree contents")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check-staged")

    p_range = sub.add_parser("check-range")
    p_range.add_argument("commit_range")

    sub.add_parser("check-tree")

    args = parser.parse_args()
    issues: list[str] = []

    if args.cmd == "check-staged":
        issues = check_staged()
    elif args.cmd == "check-range":
        issues = check_commit_range(args.commit_range)
    elif args.cmd == "check-tree":
        issues = check_tree()

    if issues:
        print("Privacy guard failed:", file=sys.stderr)
        for issue in issues:
            print(f"- {issue}", file=sys.stderr)
        return 1
    print("Privacy guard passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
