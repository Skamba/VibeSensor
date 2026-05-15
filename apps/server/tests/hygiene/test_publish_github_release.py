from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests._paths import REPO_ROOT

_PUBLISH_RELEASE = REPO_ROOT / "tools" / "publish_github_release.py"
pytestmark = pytest.mark.dev_tooling


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


def _option_value(command: list[str], option: str) -> str:
    assert option in command
    return command[command.index(option) + 1]


def test_existing_release_id_uses_repo_endpoint_without_repo_flag(monkeypatch) -> None:
    module = _load_publish_github_release_module()
    commands: list[list[str]] = []
    timeouts: list[float] = []

    def _fake_run(
        command: list[str],
        *,
        check: bool = True,
        capture_output: bool = False,
        context: str,
        timeout_s: float,
    ):
        commands.append(list(command))
        timeouts.append(timeout_s)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"id": 123}),
            stderr="",
        )

    monkeypatch.setattr(module, "_run", _fake_run)

    assert (
        module._existing_release_id(
            "owner/repo",
            "server-v2026.3.28",
            timeout_s=12.0,
        )
        == 123
    )
    command = commands[0]
    assert command[:2] == ["gh", "api"]
    assert "repos/owner/repo/releases/tags/server-v2026.3.28" in command
    assert "-R" not in command
    assert timeouts == [12.0]


def test_main_creates_or_updates_release_with_repo_endpoint_and_uploads_assets(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_publish_github_release_module()
    notes_file = tmp_path / "notes.md"
    notes_file.write_text("release notes\n", encoding="utf-8")
    asset_file = tmp_path / "artifact.zip"
    asset_file.write_text("artifact", encoding="utf-8")
    cases = (
        (None, "POST", "repos/owner/repo/releases"),
        (77, "PATCH", "repos/owner/repo/releases/77"),
    )

    for existing_release_id, method, endpoint in cases:
        commands: list[list[str]] = []
        release_payloads: list[dict[str, object]] = []
        monkeypatch.setattr(
            module,
            "_existing_release_id",
            lambda repo, tag, *, timeout_s, release_id=existing_release_id: release_id,
        )

        def _fake_run(
            command: list[str],
            *,
            check: bool = True,
            capture_output: bool = False,
            context: str,
            timeout_s: float,
            recorded_commands: list[list[str]] = commands,
            recorded_payloads: list[dict[str, object]] = release_payloads,
        ):
            recorded_commands.append(list(command))
            if "--input" in command:
                recorded_payloads.append(
                    json.loads(Path(_option_value(command, "--input")).read_text())
                )
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

        release_command, upload_command = commands
        assert release_command[:2] == ["gh", "api"]
        assert "-R" not in release_command
        assert endpoint in release_command
        assert _option_value(release_command, "--method") == method
        assert "--input" in release_command
        release_payload = release_payloads[0]
        assert release_payload["tag_name"] == "server-v2026.3.28"
        assert release_payload["target_commitish"] == "abc123"
        assert release_payload["name"] == "Release 2026.3.28"

        assert upload_command[:3] == ["gh", "release", "upload"]
        assert "server-v2026.3.28" in upload_command
        assert str(asset_file) in upload_command
        assert "--clobber" in upload_command
        assert _option_value(upload_command, "-R") == "owner/repo"


def test_run_reports_timeout_with_command_context(monkeypatch) -> None:
    module = _load_publish_github_release_module()

    def _timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            ["gh", "api", "repos/owner/repo/releases"],
            timeout=5,
            output="partial stdout",
            stderr="partial stderr",
        )

    monkeypatch.setattr(module.subprocess, "run", _timeout)

    with pytest.raises(SystemExit) as exc_info:
        module._run(
            ["gh", "api", "repos/owner/repo/releases"],
            capture_output=True,
            context="Create release 'server-v1' in owner/repo",
            timeout_s=5,
        )
    message = str(exc_info.value)

    assert "Create release 'server-v1' in owner/repo timed out after 5s" in message
    assert "command: gh api repos/owner/repo/releases" in message
    assert "stdout: partial stdout" in message
    assert "stderr: partial stderr" in message


def test_run_reports_nonzero_exit_with_output_excerpt(monkeypatch) -> None:
    module = _load_publish_github_release_module()

    def _failed(*args, **kwargs):
        return subprocess.CompletedProcess(
            ["gh", "release", "upload"],
            2,
            stdout="upload stdout",
            stderr="upload stderr",
        )

    monkeypatch.setattr(module.subprocess, "run", _failed)

    with pytest.raises(SystemExit) as exc_info:
        module._run(
            ["gh", "release", "upload"],
            capture_output=True,
            context="Upload 1 asset(s) to release 'server-v1' in owner/repo",
            timeout_s=30,
        )
    message = str(exc_info.value)

    assert "failed with exit code 2" in message
    assert "command: gh release upload" in message
    assert "stdout: upload stdout" in message
    assert "stderr: upload stderr" in message


def test_existing_release_id_reports_malformed_json(monkeypatch) -> None:
    module = _load_publish_github_release_module()

    def _fake_run(
        command: list[str],
        *,
        check: bool = True,
        capture_output: bool = False,
        context: str,
        timeout_s: float,
    ):
        return subprocess.CompletedProcess(command, 0, stdout="{not-json", stderr="")

    monkeypatch.setattr(module, "_run", _fake_run)

    with pytest.raises(SystemExit) as exc_info:
        module._existing_release_id("owner/repo", "server-v2026.3.28", timeout_s=10)
    message = str(exc_info.value)

    assert "Malformed GitHub release lookup JSON" in message
    assert "server-v2026.3.28" in message
    assert "owner/repo" in message
    assert "stdout: {not-json" in message
