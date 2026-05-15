"""Guard Pi app-artifact version stamping and derivation."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests._paths import REPO_ROOT

_APP_ARTIFACTS_SCRIPT = REPO_ROOT / "infra/pi-image/pi-gen/lib/app_artifacts.sh"


def _run_git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def _init_git_repo(repo: Path) -> str:
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test User"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
        text=True,
    )
    (repo / "README.md").write_text("test\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repo), "add", "README.md"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "init"],
        check=True,
        capture_output=True,
        text=True,
    )
    return _run_git(repo, "rev-parse", "--short=12", "HEAD")


def _run_app_artifacts_function(repo: Path, command: str) -> str:
    proc = subprocess.run(
        [
            "bash",
            "-lc",
            (f'set -euo pipefail; source "{_APP_ARTIFACTS_SCRIPT}"; REPO_ROOT="{repo}"; {command}'),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def test_compute_app_build_version_prefers_release_tag_at_head(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    subprocess.run(
        ["git", "-C", str(repo), "tag", "server-v2026.3.29"],
        check=True,
        capture_output=True,
        text=True,
    )

    version = _run_app_artifacts_function(repo, "compute_app_build_version")

    assert version == "2026.3.29"
    assert not version.startswith("server-v")


def test_compute_app_build_version_falls_back_to_git_sha(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git_sha = _init_git_repo(repo)

    version = _run_app_artifacts_function(repo, "compute_app_build_version")

    assert version == f"0.0.0.dev0+g{git_sha}"
    assert len(git_sha) == 12


def test_build_app_artifacts_stamps_version_before_building_wheel() -> None:
    script_text = _APP_ARTIFACTS_SCRIPT.read_text(encoding="utf-8")

    stamp_call = (
        'stamp_app_version_file "${build_root}/apps/server/vibesensor/_version.py" "${app_version}"'
    )
    build_call = "./.build-venv/bin/python -m build --wheel apps/server"

    assert stamp_call in script_text
    assert script_text.index(stamp_call) < script_text.index(build_call)
    assert 'echo "version=${app_version}"' in script_text
    assert (
        'git_sha="$(git -C "${REPO_ROOT}" rev-parse --short=12 HEAD 2>/dev/null || true)"'
        in script_text
    )
