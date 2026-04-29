"""Guard Docker build contexts against local server runtime data."""

from __future__ import annotations

from tests._paths import REPO_ROOT


def _ignore_patterns(path: str) -> set[str]:
    return {
        line.strip()
        for line in (REPO_ROOT / path).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def test_dockerignore_mirrors_server_runtime_data_gitignore_patterns() -> None:
    gitignore_patterns = _ignore_patterns(".gitignore")
    dockerignore_patterns = _ignore_patterns(".dockerignore")
    server_runtime_patterns = {
        pattern
        for pattern in gitignore_patterns
        if pattern.startswith("apps/server/data/") or pattern == "apps/server/wifi-secrets.env"
    }

    assert server_runtime_patterns
    assert server_runtime_patterns <= dockerignore_patterns
