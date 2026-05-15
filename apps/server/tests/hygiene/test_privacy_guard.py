"""Guard the local privacy hook implementation."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tests._paths import REPO_ROOT

_GUARD = REPO_ROOT / "tools" / "privacy" / "privacy_guard.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run(["git", *args], repo)


def _init_repo(repo: Path) -> None:
    _git(repo, "init").check_returncode()
    _git(repo, "config", "user.email", "dev@example.invalid").check_returncode()
    _git(repo, "config", "user.name", "Dev").check_returncode()
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md").check_returncode()
    _git(repo, "commit", "-m", "base").check_returncode()


def _github_token() -> str:
    return "ghp_" + ("A" * 36)


def test_privacy_guard_check_staged_blocks_staged_tokens(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "leak.txt").write_text(f"token={_github_token()}\n", encoding="utf-8")
    _git(tmp_path, "add", "leak.txt").check_returncode()

    result = _run([sys.executable, str(_GUARD), "check-staged"], tmp_path)

    assert result.returncode == 1
    assert "leak.txt:1" in result.stderr
    assert "GitHub token" in result.stderr


def test_privacy_guard_check_range_blocks_sensitive_paths(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / ".secrets.act").write_text("TOKEN=placeholder\n", encoding="utf-8")
    _git(tmp_path, "add", "-f", ".secrets.act").check_returncode()
    _git(tmp_path, "commit", "-m", "add secret file").check_returncode()

    result = _run([sys.executable, str(_GUARD), "check-range", "HEAD~1..HEAD"], tmp_path)

    assert result.returncode == 1
    assert ".secrets.act" in result.stderr
    assert "sensitive local-only file" in result.stderr


def test_privacy_guard_allows_documented_placeholders(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "example.env").write_text(
        "\n".join(
            [
                "API_TOKEN=${GITHUB_TOKEN}",
                'WIFI_PASSWORD="example-password"',
                'CLIENT_SECRET="<client-secret>"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    _git(tmp_path, "add", "example.env").check_returncode()

    result = _run([sys.executable, str(_GUARD), "check-staged"], tmp_path)

    assert result.returncode == 0
    assert result.stderr == ""


def test_hooks_run_privacy_guard_with_repo_python_fallbacks() -> None:
    for hook_name in ("pre-commit", "pre-push"):
        hook_text = (REPO_ROOT / ".githooks" / hook_name).read_text(encoding="utf-8")
        assert "tools/privacy/privacy_guard.py" in hook_text
        assert ".venv/bin/python" in hook_text
        assert "python3" in hook_text
        assert '"${python_bin}" "${guard_script}"' in hook_text
        assert "Skipping privacy guard" not in hook_text
