"""Guard explicit LF policies for high-value tracked text formats."""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path

from tests._paths import REPO_ROOT

_REQUIRED_LF_PATTERNS = (
    "*.sh",
    "*.service",
    "*.timer",
    "*.yml",
    "*.yaml",
    "*.py",
    "*.ts",
    "*.tsx",
    "*.js",
    "*.mjs",
    "*.cjs",
    "*.json",
    "*.jsonc",
    "*.css",
    "*.html",
    "*.md",
    "*.cpp",
    "*.h",
    "*.ini",
    "*.toml",
    "Dockerfile*",
    "Makefile",
)


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def _gitattributes() -> dict[str, set[str]]:
    attributes: dict[str, set[str]] = {}
    for line in (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        pattern, *tokens = stripped.split()
        attributes[pattern] = set(tokens)
    return attributes


def _matches(pattern: str, path: str) -> bool:
    return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(Path(path).name, pattern)


def test_high_value_text_patterns_have_explicit_lf_policy() -> None:
    attributes = _gitattributes()

    missing_or_weak = [
        pattern
        for pattern in _REQUIRED_LF_PATTERNS
        if not {"text", "eol=lf"}.issubset(attributes.get(pattern, set()))
    ]

    assert missing_or_weak == []
    assert {"text", "eol=lf"}.issubset(attributes["*.py"])
    assert {"text", "eol=lf"}.issubset(attributes["*.sh"])


def test_required_lf_patterns_cover_tracked_files() -> None:
    tracked_files = _tracked_files()

    stale_patterns = [
        pattern
        for pattern in _REQUIRED_LF_PATTERNS
        if not any(_matches(pattern, path) for path in tracked_files)
    ]

    assert stale_patterns == []
    assert "Makefile" in _REQUIRED_LF_PATTERNS
