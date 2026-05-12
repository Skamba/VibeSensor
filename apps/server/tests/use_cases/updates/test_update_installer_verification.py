from __future__ import annotations

import json
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from test_support.update_status import build_update_status_harness

from vibesensor.use_cases.updates.artifact_validation import (
    WheelArtifactValidator,
    read_wheel_metadata,
    sha256_file,
    wheel_dependency_issues,
)
from vibesensor.use_cases.updates.firmware import FirmwareRefresher, FirmwareRefreshResult
from vibesensor.use_cases.updates.installer import UpdateInstaller, UpdateInstallerConfig
from vibesensor.use_cases.updates.rollback_snapshot import RollbackSnapshotStore
from vibesensor.use_cases.updates.rollback_verification import RollbackDeploymentVerifier
from vibesensor.use_cases.updates.runner import CommandExecutionResult
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.wheel_installation import WheelInstallResult


class RecordingCommands:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []
        self.responses: list[tuple[str, CommandExecutionResult]] = []
        self.default_response = CommandExecutionResult(returncode=0, stdout="", stderr="")
        self.local_wheel_version: str = ""

    def set_response(self, match_substr: str, rc: int, stdout: str = "", stderr: str = "") -> None:
        self.responses.append(
            (
                match_substr,
                CommandExecutionResult(returncode=rc, stdout=stdout, stderr=stderr),
            ),
        )

    async def run(
        self,
        args: list[str],
        *,
        timeout: float,
        phase: str,
        sudo: bool = False,
        env: dict[str, str] | None = None,
    ) -> CommandExecutionResult:
        del timeout, sudo, env
        self.calls.append((list(args), phase))
        joined = " ".join(args)
        for match_substr, response in self.responses:
            if match_substr in joined:
                return response
        if "pip" in args and "wheel" in args and "-w" in args and self.local_wheel_version:
            wheel_dir = Path(args[args.index("-w") + 1])
            _build_fake_wheel(
                wheel_dir / f"vibesensor-{self.local_wheel_version}-py3-none-any.whl",
                version=self.local_wheel_version,
            )
        if "pip" in args and "download" in args and "-d" in args:
            download_dir = Path(args[args.index("-d") + 1])
            version = next(
                (arg.split("==", 1)[1] for arg in args if arg.startswith("vibesensor==")),
                "",
            )
            if version:
                _build_fake_wheel(
                    download_dir / f"vibesensor-{version}-py3-none-any.whl",
                    version=version,
                )
        return self.default_response


def _build_fake_wheel(
    path: Path,
    *,
    version: str,
    name: str = "vibesensor",
    requires_python: str = "",
    requires_dist: tuple[str, ...] = (),
) -> None:
    dist_info = f"vibesensor-{version}.dist-info"
    metadata_lines = [
        "Metadata-Version: 2.1",
        f"Name: {name}",
        f"Version: {version}",
    ]
    if requires_python:
        metadata_lines.append(f"Requires-Python: {requires_python}")
    metadata_lines.extend(f"Requires-Dist: {entry}" for entry in requires_dist)
    with zipfile.ZipFile(path, "w") as wheel_zip:
        wheel_zip.writestr("vibesensor/__init__.py", f"__version__ = '{version}'\n")
        wheel_zip.writestr(
            f"{dist_info}/METADATA",
            "\n".join(metadata_lines) + "\n",
        )
        wheel_zip.writestr(f"{dist_info}/WHEEL", "Wheel-Version: 1.0\nTag: py3-none-any\n")


def _make_installer(
    tmp_path: Path,
) -> tuple[UpdateInstaller, RecordingCommands, UpdateStatusTracker]:
    repo = tmp_path / "repo"
    server_dir = repo / "apps" / "server"
    (server_dir / ".venv" / "bin").mkdir(parents=True)
    (server_dir / "pyproject.toml").write_text(
        "\n".join(
            (
                "[build-system]",
                "requires = ['setuptools', 'wheel']",
                "build-backend = 'setuptools.build_meta'",
                "",
            )
        ),
        encoding="utf-8",
    )
    config_path = server_dir / "config.pi.yaml"
    config_path.write_text("server:\n  host: 127.0.0.1\n  port: 80\n", encoding="utf-8")
    python_path = repo / "apps" / "server" / ".venv" / "bin" / "python3"
    python_path.write_text("#!/bin/sh\n", encoding="utf-8")
    python_path.chmod(0o755)
    (repo / "apps" / "server" / ".venv" / "pyvenv.cfg").write_text("home = /tmp\n")
    tracker = build_update_status_harness(tmp_path / "update_status.json")
    commands = RecordingCommands()
    installer = UpdateInstaller(
        commands=commands,
        status=tracker,
        config=UpdateInstallerConfig(
            repo=repo,
            rollback_dir=tmp_path / "rollback",
            reinstall_timeout_s=30,
            smoke_config_path=config_path,
        ),
    )
    return installer, commands, tracker


@pytest.mark.asyncio
async def test_snapshot_for_rollback_writes_checksum_metadata(tmp_path: Path) -> None:
    installer, commands, _tracker = _make_installer(tmp_path)
    commands.local_wheel_version = "2025.6.14"
    rollback_dir = tmp_path / "rollback"

    with patch("vibesensor.__version__", "2025.6.14"):
        assert await installer.snapshot_for_rollback() is True

    metadata = json.loads((rollback_dir / "rollback_snapshot.json").read_text(encoding="utf-8"))
    assert metadata["version"] == "2025.6.14"
    assert len(metadata["sha256"]) == 64
    assert metadata["config_path"].endswith("config.pi.yaml")
    assert metadata["repo_path"] == str(installer._config.repo)
    assert "assets_verified" in metadata
    assert "has_packaged_static" in metadata
    assert (rollback_dir / "rollback_snapshot.whl").is_file()


@pytest.mark.asyncio
async def test_snapshot_for_rollback_falls_back_to_package_index_download(
    tmp_path: Path,
) -> None:
    installer, commands, tracker = _make_installer(tmp_path)
    commands.set_response("pip wheel", 1, "", "local build failed")

    with patch("vibesensor.__version__", "2025.6.14"):
        assert await installer.snapshot_for_rollback() is True

    calls = [" ".join(call[0]) for call in commands.calls]
    assert any("pip wheel" in call for call in calls)
    assert any("pip download" in call for call in calls)
    assert any("Local rollback wheel build failed" in line for line in tracker.status.log_tail)


@pytest.mark.asyncio
async def test_snapshot_for_rollback_fails_when_metadata_write_fails(tmp_path: Path) -> None:
    installer, commands, tracker = _make_installer(tmp_path)
    commands.local_wheel_version = "2025.6.14"
    rollback_dir = tmp_path / "rollback"
    rollback_dir.mkdir()

    with (
        patch("vibesensor.__version__", "2025.6.14"),
        patch.object(RollbackSnapshotStore, "write_metadata", side_effect=OSError("disk full")),
    ):
        assert await installer.snapshot_for_rollback() is False

    assert not (rollback_dir / "rollback_snapshot.json").exists()
    assert not (rollback_dir / "rollback_snapshot.whl").exists()
    assert any(
        issue.message == "Rollback metadata could not be written" for issue in tracker.status.issues
    )


@pytest.mark.asyncio
async def test_snapshot_for_rollback_preserves_previous_snapshot_when_metadata_write_fails(
    tmp_path: Path,
) -> None:
    installer, commands, tracker = _make_installer(tmp_path)
    commands.local_wheel_version = "2025.6.14"
    rollback_dir = tmp_path / "rollback"
    rollback_dir.mkdir()
    previous_wheel = rollback_dir / "rollback_snapshot.whl"
    _build_fake_wheel(previous_wheel, version="2025.6.13")
    (rollback_dir / "rollback_snapshot.json").write_text(
        json.dumps(
            {
                "version": "2025.6.13",
                "sha256": sha256_file(previous_wheel),
            },
        )
        + "\n",
        encoding="utf-8",
    )

    with (
        patch("vibesensor.__version__", "2025.6.14"),
        patch.object(RollbackSnapshotStore, "write_metadata", side_effect=OSError("disk full")),
    ):
        assert await installer.snapshot_for_rollback() is False

    assert read_wheel_metadata(previous_wheel).version == "2025.6.13"
    metadata = json.loads((rollback_dir / "rollback_snapshot.json").read_text(encoding="utf-8"))
    assert metadata["version"] == "2025.6.13"
    assert any(
        issue.message == "Rollback metadata could not be written" for issue in tracker.status.issues
    )


@pytest.mark.asyncio
async def test_install_release_rejects_corrupt_downloaded_wheel(tmp_path: Path) -> None:
    installer, commands, tracker = _make_installer(tmp_path)
    broken_wheel = tmp_path / "broken.whl"
    broken_wheel.write_text("not a wheel", encoding="utf-8")

    result = await installer.install_release(broken_wheel, "2025.6.15")

    assert result == WheelInstallResult(succeeded=False, rollback_required=False)
    assert tracker.status.state.value == "failed"
    assert not commands.calls
    assert any(issue.message == "Downloaded wheel is corrupt" for issue in tracker.status.issues)


@pytest.mark.asyncio
async def test_rollback_rejects_checksum_mismatch(tmp_path: Path) -> None:
    installer, commands, tracker = _make_installer(tmp_path)
    rollback_dir = tmp_path / "rollback"
    rollback_dir.mkdir()
    wheel_path = rollback_dir / "rollback_snapshot.whl"
    _build_fake_wheel(wheel_path, version="2025.6.14")
    (rollback_dir / "rollback_snapshot.json").write_text(
        json.dumps(
            {
                "version": "2025.6.14",
                "sha256": "0" * 64,
            },
        )
        + "\n",
        encoding="utf-8",
    )

    assert await installer.rollback() is False
    assert not commands.calls
    assert any(
        issue.message == "Rollback snapshot wheel checksum mismatch"
        for issue in tracker.status.issues
    )


@pytest.mark.asyncio
async def test_rollback_without_metadata_fails_explicitly(tmp_path: Path) -> None:
    installer, commands, tracker = _make_installer(tmp_path)
    rollback_dir = tmp_path / "rollback"
    rollback_dir.mkdir()
    wheel_path = rollback_dir / "rollback_snapshot.whl"
    _build_fake_wheel(wheel_path, version="2025.6.14")

    assert await installer.rollback() is False
    assert not commands.calls
    assert any(
        issue.message == "Rollback snapshot metadata is missing" for issue in tracker.status.issues
    )


@pytest.mark.asyncio
async def test_rollback_missing_snapshot_wheel_fails(tmp_path: Path) -> None:
    installer, commands, tracker = _make_installer(tmp_path)
    rollback_dir = tmp_path / "rollback"
    rollback_dir.mkdir()
    (rollback_dir / "rollback_snapshot.json").write_text(
        json.dumps(
            {
                "version": "2025.6.14",
                "sha256": "1" * 64,
            },
        )
        + "\n",
        encoding="utf-8",
    )

    assert await installer.rollback() is False
    assert not commands.calls
    assert any(
        issue.message == "Rollback snapshot wheel is missing" for issue in tracker.status.issues
    )


@pytest.mark.asyncio
async def test_rollback_invalid_snapshot_wheel_fails(tmp_path: Path) -> None:
    installer, commands, tracker = _make_installer(tmp_path)
    rollback_dir = tmp_path / "rollback"
    rollback_dir.mkdir()
    snapshot_wheel = rollback_dir / "rollback_snapshot.whl"
    snapshot_wheel.write_text("not a wheel", encoding="utf-8")
    (rollback_dir / "rollback_snapshot.json").write_text(
        json.dumps(
            {
                "version": "2025.6.14",
                "sha256": "0" * 64,
            },
        )
        + "\n",
        encoding="utf-8",
    )

    assert await installer.rollback() is False
    assert not commands.calls
    assert any(
        issue.message == "Rollback snapshot wheel is corrupt" for issue in tracker.status.issues
    )


@pytest.mark.asyncio
async def test_rollback_verifies_deployment_after_reinstall(tmp_path: Path) -> None:
    installer, commands, tracker = _make_installer(tmp_path)
    rollback_dir = tmp_path / "rollback"
    rollback_dir.mkdir()
    wheel_path = rollback_dir / "rollback_snapshot.whl"
    _build_fake_wheel(wheel_path, version="2025.6.14")
    (rollback_dir / "rollback_snapshot.json").write_text(
        json.dumps(
            {
                "version": "2025.6.14",
                "sha256": sha256_file(wheel_path),
                "config_path": str(installer._config.smoke_config_path),
            },
        )
        + "\n",
        encoding="utf-8",
    )
    commands.set_response("__version__", 0, "2025.6.14\n", "")
    verify = AsyncMock(return_value=True)

    with patch.object(RollbackDeploymentVerifier, "verify", verify):
        assert await installer.rollback() is True

    verify.assert_awaited_once()
    assert any("Rolled back to rollback_snapshot.whl" in line for line in tracker.status.log_tail)


@pytest.mark.asyncio
async def test_rollback_fails_when_deployment_verification_fails(tmp_path: Path) -> None:
    installer, commands, _tracker = _make_installer(tmp_path)
    rollback_dir = tmp_path / "rollback"
    rollback_dir.mkdir()
    wheel_path = rollback_dir / "rollback_snapshot.whl"
    _build_fake_wheel(wheel_path, version="2025.6.14")
    (rollback_dir / "rollback_snapshot.json").write_text(
        json.dumps(
            {
                "version": "2025.6.14",
                "sha256": sha256_file(wheel_path),
                "config_path": str(installer._config.smoke_config_path),
            },
        )
        + "\n",
        encoding="utf-8",
    )
    commands.set_response("__version__", 0, "2025.6.14\n", "")

    with patch.object(
        RollbackDeploymentVerifier,
        "verify",
        AsyncMock(return_value=False),
    ):
        assert await installer.rollback() is False


def test_wheel_validator_rejects_corrupt_wheel_without_installer(tmp_path: Path) -> None:
    tracker = build_update_status_harness(tmp_path / "update_status.json")
    validator = WheelArtifactValidator(
        status=tracker,
    )
    broken_wheel = tmp_path / "broken.whl"
    broken_wheel.write_text("not a wheel", encoding="utf-8")

    ok = validator.validate_wheel(
        broken_wheel,
        phase="installing",
        context="Downloaded wheel",
        fatal=False,
    )

    assert not ok
    assert any(issue.message == "Downloaded wheel is corrupt" for issue in tracker.status.issues)


def test_wheel_validator_rejects_invalid_metadata_requirement(tmp_path: Path) -> None:
    tracker = build_update_status_harness(tmp_path / "update_status.json")
    validator = WheelArtifactValidator(
        status=tracker,
    )
    wheel_path = tmp_path / "broken-metadata.whl"
    _build_fake_wheel(
        wheel_path,
        version="2025.6.15",
        requires_dist=("not a valid requirement ;;;",),
    )

    ok = validator.validate_wheel(
        wheel_path,
        phase="installing",
        context="Downloaded wheel",
        fatal=False,
    )

    assert not ok
    assert any(
        issue.message == "Downloaded wheel metadata is invalid" for issue in tracker.status.issues
    )


def test_wheel_dependency_issues_report_python_and_dependency_mismatches(tmp_path: Path) -> None:
    wheel_path = tmp_path / "vibesensor-2025.6.15-py3-none-any.whl"
    _build_fake_wheel(
        wheel_path,
        version="2025.6.15",
        requires_python=">=3.15",
        requires_dist=(
            "packaging>=99",
            "missingdep>=1",
            "colorama>=0.4; sys_platform == 'win32'",
        ),
    )

    issues = wheel_dependency_issues(
        read_wheel_metadata(wheel_path),
        python_full_version="3.13.5",
        marker_environment={
            "python_full_version": "3.13.5",
            "python_version": "3.13",
            "sys_platform": "linux",
        },
        installed_versions={"packaging": "24.2"},
    )

    assert "Python 3.13.5 does not satisfy wheel Requires-Python >=3.15" in issues
    assert "Dependency packaging==24.2 does not satisfy >=99" in issues
    assert "Missing dependency: missingdep>=1" in issues
    assert all("colorama" not in issue for issue in issues)


@pytest.mark.asyncio
async def test_install_release_rejects_incompatible_environment_before_pip_install(
    tmp_path: Path,
) -> None:
    installer, commands, tracker = _make_installer(tmp_path)
    wheel_path = tmp_path / "vibesensor-2025.6.15-py3-none-any.whl"
    _build_fake_wheel(
        wheel_path,
        version="2025.6.15",
        requires_dist=("missingdep>=1",),
    )
    commands.set_response(
        "missingdep",
        0,
        (
            '{"python_full_version":"3.13.5","marker_environment":{"python_full_version":"3.13.5",'
            '"python_version":"3.13","sys_platform":"linux"},"installed_versions":{"missingdep":""}}\n'
        ),
        "",
    )

    result = await installer.install_release(wheel_path, "2025.6.15")

    assert result == WheelInstallResult(succeeded=False, rollback_required=False)
    assert tracker.status.state.value == "failed"
    assert any(
        issue.message == "Downloaded wheel is incompatible with the current environment"
        for issue in tracker.status.issues
    )
    assert not any(
        "pip install --force-reinstall --no-deps" in " ".join(call[0]) for call in commands.calls
    )


@pytest.mark.asyncio
async def test_install_release_reports_malformed_dependency_snapshot_stdout(
    tmp_path: Path,
) -> None:
    installer, commands, tracker = _make_installer(tmp_path)
    wheel_path = tmp_path / "vibesensor-2025.6.15-py3-none-any.whl"
    _build_fake_wheel(
        wheel_path,
        version="2025.6.15",
        requires_dist=("missingdep>=1",),
    )
    commands.set_response("missingdep", 0, "{not-json", "")

    result = await installer.install_release(wheel_path, "2025.6.15")

    assert result == WheelInstallResult(succeeded=False, rollback_required=False)
    assert tracker.status.state.value == "failed"
    assert any(
        issue.message == "Could not parse wheel dependency compatibility results"
        and "{not-json" in issue.detail
        for issue in tracker.status.issues
    )
    assert not any(
        "pip install --force-reinstall --no-deps" in " ".join(call[0]) for call in commands.calls
    )


@pytest.mark.asyncio
async def test_wheel_install_executor_only_requests_rollback_after_mutating_failure(
    tmp_path: Path,
) -> None:
    installer, commands, _tracker = _make_installer(tmp_path)
    wheel_path = tmp_path / "vibesensor-2025.6.15-py3-none-any.whl"
    _build_fake_wheel(
        wheel_path,
        version="2025.6.15",
        requires_dist=("missingdep>=1",),
    )
    commands.set_response(
        "missingdep",
        0,
        (
            '{"python_full_version":"3.13.5","marker_environment":{"python_full_version":"3.13.5",'
            '"python_version":"3.13","sys_platform":"linux"},"installed_versions":{"missingdep":""}}\n'
        ),
        "",
    )

    compatibility_result = await installer._wheel_install_executor.install_release(
        wheel_path,
        "2025.6.15",
    )

    assert compatibility_result == WheelInstallResult(succeeded=False, rollback_required=False)

    second_installer, second_commands, _second_tracker = _make_installer(tmp_path / "second")
    second_wheel = tmp_path / "second" / "vibesensor-2025.6.15-py3-none-any.whl"
    _build_fake_wheel(second_wheel, version="2025.6.15")
    second_commands.set_response("pip install --force-reinstall --no-deps", 1, "", "install failed")

    install_result = await second_installer._wheel_install_executor.install_release(
        second_wheel,
        "2025.6.15",
    )

    assert install_result == WheelInstallResult(succeeded=False, rollback_required=True)


@pytest.mark.asyncio
async def test_firmware_refresher_uses_module_fallback_without_installer(tmp_path: Path) -> None:
    installer, commands, tracker = _make_installer(tmp_path)
    refresher = FirmwareRefresher(
        commands=commands,
        status=tracker,
        repo=installer._config.repo,
        timeout_s=30,
    )

    result = await refresher.refresh_esp_firmware("server-v2025.6.15")

    assert any(
        call[0][:3]
        == [
            str(installer._config.repo / "apps" / "server" / ".venv" / "bin" / "python3"),
            "-m",
            "vibesensor.use_cases.updates.firmware.firmware_cache",
        ]
        and call[0][-2:] == ["--tag", "server-v2025.6.15"]
        for call in commands.calls
    )
    assert result == FirmwareRefreshResult.success()
