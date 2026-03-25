from __future__ import annotations

import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from vibesensor.use_cases.updates.artifact_validation import (
    WheelArtifactValidator,
    read_wheel_metadata,
    wheel_dependency_issues,
)
from vibesensor.use_cases.updates.firmware.firmware_refresh import FirmwareRefresher
from vibesensor.use_cases.updates.installer import UpdateInstaller, UpdateInstallerConfig
from vibesensor.use_cases.updates.rollback_snapshot import RollbackSnapshotStore
from vibesensor.use_cases.updates.status import UpdateStateStore, UpdateStatusTracker


class RecordingCommands:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []
        self.responses: list[tuple[str, tuple[int, str, str]]] = []
        self.default_response: tuple[int, str, str] = (0, "", "")

    def set_response(self, match_substr: str, rc: int, stdout: str = "", stderr: str = "") -> None:
        self.responses.append((match_substr, (rc, stdout, stderr)))

    async def run(
        self,
        args: list[str],
        *,
        timeout: float,
        phase: str,
        sudo: bool = False,
        env: dict[str, str] | None = None,
    ) -> tuple[int, str, str]:
        del timeout, sudo, env
        self.calls.append((list(args), phase))
        joined = " ".join(args)
        for match_substr, response in self.responses:
            if match_substr in joined:
                return response
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
    (repo / "apps" / "server" / ".venv" / "bin").mkdir(parents=True)
    python_path = repo / "apps" / "server" / ".venv" / "bin" / "python3"
    python_path.write_text("#!/bin/sh\n", encoding="utf-8")
    python_path.chmod(0o755)
    (repo / "apps" / "server" / ".venv" / "pyvenv.cfg").write_text("home = /tmp\n")
    tracker = UpdateStatusTracker(state_store=UpdateStateStore(tmp_path / "update_status.json"))
    commands = RecordingCommands()
    installer = UpdateInstaller(
        commands=commands,
        tracker=tracker,
        config=UpdateInstallerConfig(
            repo=repo,
            rollback_dir=tmp_path / "rollback",
            reinstall_timeout_s=30,
            firmware_refresh_timeout_s=30,
        ),
    )
    return installer, commands, tracker


@pytest.mark.asyncio
async def test_snapshot_for_rollback_writes_checksum_metadata(tmp_path: Path) -> None:
    installer, commands, _tracker = _make_installer(tmp_path)
    rollback_dir = tmp_path / "rollback"
    rollback_dir.mkdir()
    wheel_path = rollback_dir / "vibesensor-2025.6.14-py3-none-any.whl"
    _build_fake_wheel(wheel_path, version="2025.6.14")

    with patch("vibesensor.__version__", "2025.6.14"):
        assert await installer.snapshot_for_rollback() is True

    metadata = json.loads((rollback_dir / "rollback_snapshot.json").read_text(encoding="utf-8"))
    assert metadata["version"] == "2025.6.14"
    assert metadata["wheel_name"] == wheel_path.name
    assert len(metadata["sha256"]) == 64
    assert any("pip download" in " ".join(call[0]) for call in commands.calls)


@pytest.mark.asyncio
async def test_snapshot_for_rollback_keeps_latest_previous_wheel_as_secondary_fallback(
    tmp_path: Path,
) -> None:
    installer, _commands, _tracker = _make_installer(tmp_path)
    rollback_dir = tmp_path / "rollback"
    rollback_dir.mkdir()
    _build_fake_wheel(rollback_dir / "vibesensor-2025.6.12-py3-none-any.whl", version="2025.6.12")
    _build_fake_wheel(rollback_dir / "vibesensor-2025.6.13-py3-none-any.whl", version="2025.6.13")

    with patch("vibesensor.__version__", "2025.6.14"):
        assert await installer.snapshot_for_rollback() is True

    wheels = sorted(path.name for path in rollback_dir.glob("vibesensor-*.whl"))
    assert wheels == [
        "vibesensor-2025.6.13-py3-none-any.whl",
        "vibesensor-2025.6.14-py3-none-any.whl",
    ]


@pytest.mark.asyncio
async def test_snapshot_for_rollback_fails_when_metadata_write_fails(tmp_path: Path) -> None:
    installer, _commands, tracker = _make_installer(tmp_path)
    rollback_dir = tmp_path / "rollback"
    rollback_dir.mkdir()
    wheel_path = rollback_dir / "vibesensor-2025.6.14-py3-none-any.whl"
    _build_fake_wheel(wheel_path, version="2025.6.14")

    with (
        patch("vibesensor.__version__", "2025.6.14"),
        patch.object(RollbackSnapshotStore, "write_metadata", side_effect=OSError("disk full")),
    ):
        assert await installer.snapshot_for_rollback() is False

    assert not (rollback_dir / "rollback_snapshot.json").exists()
    assert any(
        issue.message == "Rollback metadata could not be written" for issue in tracker.status.issues
    )


@pytest.mark.asyncio
async def test_install_release_rejects_corrupt_downloaded_wheel(tmp_path: Path) -> None:
    installer, commands, tracker = _make_installer(tmp_path)
    broken_wheel = tmp_path / "broken.whl"
    broken_wheel.write_text("not a wheel", encoding="utf-8")

    assert await installer.install_release(broken_wheel, "2025.6.15") is False
    assert tracker.status.state.value == "failed"
    assert not commands.calls
    assert any(issue.message == "Downloaded wheel is corrupt" for issue in tracker.status.issues)


@pytest.mark.asyncio
async def test_rollback_rejects_checksum_mismatch(tmp_path: Path) -> None:
    installer, commands, tracker = _make_installer(tmp_path)
    rollback_dir = tmp_path / "rollback"
    rollback_dir.mkdir()
    wheel_path = rollback_dir / "vibesensor-2025.6.14-py3-none-any.whl"
    _build_fake_wheel(wheel_path, version="2025.6.14")
    (rollback_dir / "rollback_snapshot.json").write_text(
        json.dumps(
            {
                "version": "2025.6.14",
                "wheel_name": wheel_path.name,
                "sha256": "0" * 64,
            },
        )
        + "\n",
        encoding="utf-8",
    )

    assert await installer.rollback() is False
    assert not commands.calls
    assert any(
        issue.message == "Rollback wheel checksum mismatch" for issue in tracker.status.issues
    )


@pytest.mark.asyncio
async def test_rollback_without_metadata_uses_valid_newest_wheel(tmp_path: Path) -> None:
    installer, commands, tracker = _make_installer(tmp_path)
    rollback_dir = tmp_path / "rollback"
    rollback_dir.mkdir()
    wheel_path = rollback_dir / "vibesensor-2025.6.14-py3-none-any.whl"
    _build_fake_wheel(wheel_path, version="2025.6.14")
    commands.set_response("from vibesensor import __version__", 0, "2025.6.14\n", "")

    assert await installer.rollback() is True
    assert any(
        "pip install --force-reinstall --no-deps" in " ".join(call[0]) for call in commands.calls
    )
    assert tracker.status.issues == []
    assert any(
        "Rollback metadata missing; falling back to newest rollback wheel without checksum pin"
        in line
        for line in tracker.status.log_tail
    )


@pytest.mark.asyncio
async def test_rollback_missing_primary_wheel_uses_secondary_fallback(tmp_path: Path) -> None:
    installer, commands, tracker = _make_installer(tmp_path)
    rollback_dir = tmp_path / "rollback"
    rollback_dir.mkdir()
    older_wheel = rollback_dir / "vibesensor-2025.6.13-py3-none-any.whl"
    _build_fake_wheel(older_wheel, version="2025.6.13")
    (rollback_dir / "rollback_snapshot.json").write_text(
        json.dumps(
            {
                "version": "2025.6.14",
                "wheel_name": "vibesensor-2025.6.14-py3-none-any.whl",
                "sha256": "1" * 64,
            },
        )
        + "\n",
        encoding="utf-8",
    )
    commands.set_response("from vibesensor import __version__", 0, "2025.6.13\n", "")

    assert await installer.rollback() is True
    assert any(str(older_wheel) in " ".join(call[0]) for call in commands.calls)
    assert any("Using fallback rollback wheel" in line for line in tracker.status.log_tail)


@pytest.mark.asyncio
async def test_rollback_invalid_primary_wheel_uses_secondary_fallback(tmp_path: Path) -> None:
    installer, commands, tracker = _make_installer(tmp_path)
    rollback_dir = tmp_path / "rollback"
    rollback_dir.mkdir()
    newer_wheel = rollback_dir / "vibesensor-2025.6.14-py3-none-any.whl"
    older_wheel = rollback_dir / "vibesensor-2025.6.13-py3-none-any.whl"
    _build_fake_wheel(newer_wheel, version="2025.6.14")
    _build_fake_wheel(older_wheel, version="2025.6.13")
    (rollback_dir / "rollback_snapshot.json").write_text(
        json.dumps(
            {
                "version": "2025.6.14",
                "wheel_name": newer_wheel.name,
                "sha256": "0" * 64,
            },
        )
        + "\n",
        encoding="utf-8",
    )
    commands.set_response("from vibesensor import __version__", 0, "2025.6.13\n", "")

    assert await installer.rollback() is True
    assert any(str(older_wheel) in " ".join(call[0]) for call in commands.calls)
    assert any(
        "Primary rollback snapshot could not be used; trying older rollback wheel" in line
        for line in tracker.status.log_tail
    )


def test_wheel_validator_rejects_corrupt_wheel_without_installer(tmp_path: Path) -> None:
    tracker = UpdateStatusTracker(state_store=UpdateStateStore(tmp_path / "update_status.json"))
    validator = WheelArtifactValidator(tracker)
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
    tracker = UpdateStatusTracker(state_store=UpdateStateStore(tmp_path / "update_status.json"))
    validator = WheelArtifactValidator(tracker)
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
        python_full_version="3.14.3",
        marker_environment={
            "python_full_version": "3.14.3",
            "python_version": "3.14",
            "sys_platform": "linux",
        },
        installed_versions={"packaging": "24.2"},
    )

    assert "Python 3.14.3 does not satisfy wheel Requires-Python >=3.15" in issues
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
            '{"python_full_version":"3.14.3","marker_environment":{"python_full_version":"3.14.3",'
            '"python_version":"3.14","sys_platform":"linux"},"installed_versions":{"missingdep":""}}\n'
        ),
        "",
    )

    assert await installer.install_release(wheel_path, "2025.6.15") is False
    assert tracker.status.state.value == "failed"
    assert any(
        issue.message == "Downloaded wheel is incompatible with the current environment"
        for issue in tracker.status.issues
    )
    assert not any(
        "pip install --force-reinstall --no-deps" in " ".join(call[0]) for call in commands.calls
    )


@pytest.mark.asyncio
async def test_firmware_refresher_uses_module_fallback_without_installer(tmp_path: Path) -> None:
    installer, commands, tracker = _make_installer(tmp_path)
    refresher = FirmwareRefresher(
        commands=commands,
        tracker=tracker,
        repo=installer._config.repo,
        timeout_s=30,
    )

    await refresher.refresh_esp_firmware("server-v2025.6.15")

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
