#!/usr/bin/env python3
"""Docs misuse / wrapper hack detector (R0/R1 compliance).

Checks:
1. No docs files contain large code blocks (>30 lines) that look like
   executable logic rather than examples.
2. No source files read/execute docs content at runtime.

Exit 0 if clean, 1 if violations found.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

LARGE_BLOCK_THRESHOLD = 30  # lines
EXCLUDED_DIRS = {
    ".git",
    "node_modules",
    ".pio",
    "dist",
    "__pycache__",
    ".cache",
    "artifacts",
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
}


def _walk_files(repo_root: Path) -> list[str]:
    files: list[str] = []
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(repo_root)
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        files.append(rel.as_posix())
    return files


def _tracked_files(repo_root: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "--cached"],
            capture_output=True,
            text=True,
            check=True,
        )
        tracked = [line for line in result.stdout.splitlines() if line]
        if tracked:
            return tracked
    except (OSError, subprocess.CalledProcessError):
        pass
    return _walk_files(repo_root)


def _check_large_code_blocks(docs_files: list[str]) -> list[str]:
    """Flag docs files with code blocks exceeding threshold."""
    issues: list[str] = []
    fence_re = re.compile(r"^```")
    for path in docs_files:
        try:
            with open(path) as fh:
                lines = fh.readlines()
        except (OSError, UnicodeDecodeError):
            continue
        in_block = False
        block_start = 0
        block_lines = 0
        for i, line in enumerate(lines, 1):
            if fence_re.match(line):
                if in_block:
                    if block_lines > LARGE_BLOCK_THRESHOLD:
                        issues.append(
                            f"{path}:{block_start}-{i}: code block "
                            f"({block_lines} lines) exceeds {LARGE_BLOCK_THRESHOLD}-line threshold"
                        )
                    in_block = False
                    block_lines = 0
                else:
                    in_block = True
                    block_start = i
                    block_lines = 0
            elif in_block:
                block_lines += 1
    return issues


def _check_runtime_docs_reading(source_files: list[str]) -> list[str]:
    """Flag source files that open/read/exec docs content."""
    issues: list[str] = []
    patterns = [
        re.compile(r"""open\s*\(\s*['"].*docs/"""),
        re.compile(r"""Path\s*\(\s*['"].*docs/"""),
        re.compile(r"""exec\s*\(.*docs"""),
        re.compile(r"""subprocess.*docs/"""),
    ]
    source_exts = {".py", ".ts", ".js", ".sh"}
    for path in source_files:
        import os

        _, ext = os.path.splitext(path)
        if ext not in source_exts:
            continue
        if "docs/" in path or "tools/dev/" in path:
            continue
        try:
            with open(path) as fh:
                content = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        for pat in patterns:
            match = pat.search(content)
            if match:
                issues.append(f"{path}: runtime docs access: {match.group()}")
    return issues


def _check_markdown_links(markdown_files: list[str], repo_root: Path) -> list[str]:
    """Flag broken local markdown links."""
    issues: list[str] = []
    link_re = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
    ignored_prefixes = ("http://", "https://", "mailto:", "tel:", "data:", "javascript:")
    for path in markdown_files:
        md_path = repo_root / path
        try:
            content = md_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in link_re.finditer(content):
            target = match.group(1).strip()
            if not target or target.startswith("#") or target.startswith(ignored_prefixes):
                continue
            target = target.strip("<>").split("#", 1)[0].strip()
            if not target:
                continue
            target_path = (repo_root / target.lstrip("/")) if target.startswith("/") else (md_path.parent / target)
            if not target_path.exists():
                issues.append(f"{path}: broken link target: {target}")
    return issues


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    all_files = _tracked_files(repo_root)
    markdown_files = [f for f in all_files if f.endswith(".md")]
    docs_files = [f for f in markdown_files if f.startswith("docs/")]
    source_files = [
        f
        for f in all_files
        if not any(
            d in f.split("/") for d in EXCLUDED_DIRS
        )
    ]

    issues: list[str] = []
    issues.extend(_check_large_code_blocks(docs_files))
    issues.extend(_check_runtime_docs_reading(source_files))
    issues.extend(_check_markdown_links(markdown_files, repo_root))

    if issues:
        print(f"❌ {len(issues)} docs issue(s):")
        for issue in issues:
            print(f"   {issue}")
        return 1

    print("✅ No docs misuse, runtime docs access, or broken local markdown links detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
