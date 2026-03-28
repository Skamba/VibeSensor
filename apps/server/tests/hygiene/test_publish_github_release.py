from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from tests._paths import REPO_ROOT

_PUBLISH_RELEASE = REPO_ROOT / "tools" / "publish_github_release.py"


def _load_publish_github_release_module():
    spec = importlib.util.spec_from_file_location(
        "publish_github_release_local_for_tests",
        _PUBLISH_RELEASE,
    )
    assert spec is not None and spec.loader is not None, f"Unable to load {_PUBLISH_RELEASE}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_existing_release_id_uses_repo_endpoint_without_repo_flag(monkeypatch) -> None:
    module = _load_publish_github_release_module()
    commands: list[list[str]] = []

    def _fake_run(command: list[str], *, check: bool = True, capture_output: bool = False):
        commands.append(list(command))
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"id": 123}),
            stderr="",
        )

    monkeypatch.setattr(module, "_run", _fake_run)

    assert module._existing_release_id("owner/repo", "server-v2026.3.28") == 123
    assert commands == [["gh", "api", "repos/owner/repo/releases/tags/server-v2026.3.28"]]


def test_main_creates_release_without_repo_flag_and_uploads_with_repo_flag(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_publish_github_release_module()
    commands: list[list[str]] = []
    notes_file = tmp_path / "notes.md"
    notes_file.write_text("release notes\n", encoding="utf-8")
    asset_file = tmp_path / "artifact.zip"
    asset_file.write_text("artifact", encoding="utf-8")

    monkeypatch.setattr(module, "_existing_release_id", lambda repo, tag: None)

    def _fake_run(command: list[str], *, check: bool = True, capture_output: bool = False):
        commands.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(module, "_run", _fake_run)

    module.main(
        [
            "--repo",
            "owner/repo",
            "--tag",
            "server-v2026.3.28",
            "--target",
            "abc123",
            "--title",
            "Release 2026.3.28",
            "--notes-file",
            str(notes_file),
            "--asset",
            str(asset_file),
        ]
    )

    create_command, upload_command = commands
    assert create_command[:2] == ["gh", "api"]
    assert "-R" not in create_command
    assert "repos/owner/repo/releases" in create_command
    assert "--method" in create_command
    assert create_command[create_command.index("--method") + 1] == "POST"

    assert upload_command[:3] == ["gh", "release", "upload"]
    assert upload_command[-2:] == ["-R", "owner/repo"]
    assert str(asset_file) in upload_command


def test_main_updates_existing_release_without_repo_flag(monkeypatch, tmp_path: Path) -> None:
    module = _load_publish_github_release_module()
    commands: list[list[str]] = []
    notes_file = tmp_path / "notes.md"
    notes_file.write_text("release notes\n", encoding="utf-8")
    asset_file = tmp_path / "artifact.zip"
    asset_file.write_text("artifact", encoding="utf-8")

    monkeypatch.setattr(module, "_existing_release_id", lambda repo, tag: 77)

    def _fake_run(command: list[str], *, check: bool = True, capture_output: bool = False):
        commands.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(module, "_run", _fake_run)

    module.main(
        [
            "--repo",
            "owner/repo",
            "--tag",
            "server-v2026.3.28",
            "--target",
            "abc123",
            "--title",
            "Release 2026.3.28",
            "--notes-file",
            str(notes_file),
            "--asset",
            str(asset_file),
        ]
    )

    update_command, upload_command = commands
    assert update_command[:2] == ["gh", "api"]
    assert "-R" not in update_command
    assert "repos/owner/repo/releases/77" in update_command
    assert "--method" in update_command
    assert update_command[update_command.index("--method") + 1] == "PATCH"

    assert upload_command[:3] == ["gh", "release", "upload"]
    assert upload_command[-2:] == ["-R", "owner/repo"]
