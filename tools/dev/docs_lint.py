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

LARGE_BLOCK_THRESHOLD = 30  # lines


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.splitlines()


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


def main() -> int:
    all_files = _tracked_files()
    docs_files = [f for f in all_files if f.startswith("docs/") and f.endswith(".md")]
    source_files = [
        f
        for f in all_files
        if not any(
            d in f.split("/")
            for d in ("node_modules", ".pio", "dist", "__pycache__", ".cache", "artifacts")
        )
    ]

    issues: list[str] = []
    issues.extend(_check_large_code_blocks(docs_files))
    issues.extend(_check_runtime_docs_reading(source_files))

    if issues:
        print(f"❌ {len(issues)} docs misuse / R0-R1 issue(s):")
        for issue in issues:
            print(f"   {issue}")
        return 1

    print("✅ No docs misuse or R0/R1 violations detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
