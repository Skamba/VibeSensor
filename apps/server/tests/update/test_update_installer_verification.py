from __future__ import annotations

import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from vibesensor.update.installer import UpdateInstaller, UpdateInstallerConfig
from vibesensor.update.state_store import UpdateStateStore
from vibesensor.update.status import UpdateStatusTracker


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


def _build_fake_wheel(path: Path, *, version: str) -> None:
    dist_info = f"vibesensor-{version}.dist-info"
    with zipfile.ZipFile(path, "w") as wheel_zip:
        wheel_zip.writestr("vibesensor/__init__.py", f"__version__ = '{version}'\n")
        wheel_zip.writestr(
            f"{dist_info}/METADATA",
            f"Metadata-Version: 2.1\nName: vibesensor\nVersion: {version}\n",
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
async def test_snapshot_for_rollback_fails_when_metadata_write_fails(tmp_path: Path) -> None:
    installer, _commands, tracker = _make_installer(tmp_path)
    rollback_dir = tmp_path / "rollback"
    rollback_dir.mkdir()
    wheel_path = rollback_dir / "vibesensor-2025.6.14-py3-none-any.whl"
    _build_fake_wheel(wheel_path, version="2025.6.14")

    with (
        patch("vibesensor.__version__", "2025.6.14"),
        patch.object(UpdateInstaller, "_write_rollback_metadata", side_effect=OSError("disk full")),
    ):
        assert await installer.snapshot_for_rollback() is False

    assert not (rollback_dir / "rollback_snapshot.json").exists()
    assert any("Rollback metadata could not be written" == issue.message for issue in tracker.status.issues)


@pytest.mark.asyncio
async def test_install_release_rejects_corrupt_downloaded_wheel(tmp_path: Path) -> None:
    installer, commands, tracker = _make_installer(tmp_path)
    broken_wheel = tmp_path / "broken.whl"
    broken_wheel.write_text("not a wheel", encoding="utf-8")

    assert await installer.install_release(broken_wheel, "2025.6.15") is False
    assert tracker.status.state.value == "failed"
    assert not commands.calls
    assert any("Downloaded wheel is corrupt" == issue.message for issue in tracker.status.issues)


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
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert await installer.rollback() is False
    assert not commands.calls
    assert any(
        "Rollback wheel checksum mismatch" == issue.message for issue in tracker.status.issues
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
