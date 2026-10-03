"""Installing a release into a new venv slot: the live slot stays untouched until activation."""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

import pytest
from test_support.update_status import build_update_status_harness
from test_support.venv_slots import add_slot, make_legacy_venv, simulate_slot_command

from vibesensor.common.exceptions import UpdateReleaseError
from vibesensor.updates.artifact_validation import wheel_artifact_problem
from vibesensor.updates.boot_check import SERVER_APP
from vibesensor.updates.firmware.firmware_refresh import (
    FirmwareRefresher,
    FirmwareRefreshResult,
)
from vibesensor.updates.runner import CommandExecutionResult
from vibesensor.updates.status.tracker import UpdateStatusTracker
from vibesensor.updates.venv_install import SMOKE_PORT, ReleaseVenvInstaller
from vibesensor.updates.venv_slots import VenvSlots

RUNNING = "2025.6.14"
NEW = "2025.6.15"
WHEELHOUSE = Path("/staging/wheelhouse")


class RecordingCommands:
    """Answers commands by substring and mimics venv/pip file effects.

    The installed-version probe reports *NEW*.
    """

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.responses: list[tuple[str, CommandExecutionResult]] = []

    def set_response(self, match: str, rc: int, stdout: str = "", stderr: str = "") -> None:
        self.responses.append((match, CommandExecutionResult(rc, stdout, stderr)))

    async def run(
        self,
        args: list[str],
        *,
        timeout: float,
        phase: str,
        sudo: bool = False,
    ) -> CommandExecutionResult:
        del timeout, phase, sudo
        self.calls.append(list(args))
        joined = " ".join(args)
        for match, response in self.responses:
            if match in joined:
                return response
        if "from vibesensor import __version__" in joined:
            return CommandExecutionResult(0, f"{NEW}\n", "")
        simulate_slot_command(args)
        return CommandExecutionResult(0, "", "")

    def joined(self) -> list[str]:
        return [" ".join(call) for call in self.calls]


def _build_wheel(path: Path, *, version: str = NEW, requires_dist: tuple[str, ...] = ()) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = ["Metadata-Version: 2.1", "Name: vibesensor", f"Version: {version}"]
    metadata.extend(f"Requires-Dist: {entry}" for entry in requires_dist)
    with zipfile.ZipFile(path, "w") as wheel_zip:
        wheel_zip.writestr("vibesensor/__init__.py", f"__version__ = '{version}'\n")
        wheel_zip.writestr(f"vibesensor-{version}.dist-info/METADATA", "\n".join(metadata) + "\n")
        wheel_zip.writestr(f"vibesensor-{version}.dist-info/WHEEL", "Wheel-Version: 1.0\n")
    return path


def _installer(
    tmp_path: Path,
) -> tuple[ReleaseVenvInstaller, VenvSlots, RecordingCommands, UpdateStatusTracker]:
    slots = VenvSlots(make_legacy_venv(tmp_path / ".venv"))
    tracker = build_update_status_harness(tmp_path / "update_status.json")
    commands = RecordingCommands()
    installer = ReleaseVenvInstaller(
        commands=commands,
        status=tracker,
        slots=slots,
        smoke_config=tmp_path / "config.yaml",
        health_url="http://127.0.0.1:80/api/health",
    )
    return installer, slots, commands, tracker


@pytest.fixture(autouse=True)
def _running_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("vibesensor.__version__", RUNNING)


@pytest.mark.asyncio
async def test_install_builds_and_smoke_tests_a_new_slot_beside_the_live_one(
    tmp_path: Path,
) -> None:
    installer, slots, commands, _tracker = _installer(tmp_path)
    wheel = _build_wheel(tmp_path / f"vibesensor-{NEW}-py3-none-any.whl")

    slot = await installer.install(wheel, WHEELHOUSE, NEW)

    assert slot == NEW
    # The pre-A/B venv became the active slot, untouched by the install.
    assert slots.active_slot() == RUNNING
    python = str(slots.slot_python(NEW))
    assert commands.calls == [
        [sys.executable, "-m", "venv", str(slots.slot_dir(NEW))],
        [
            python,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--find-links",
            str(WHEELHOUSE),
            f"{wheel}[esp]",
        ],
        [python, "-c", "from vibesensor import __version__; print(__version__)"],
        [
            python,
            "-m",
            "vibesensor.updates.releases.release_validation",
            "smoke-server",
            "--config",
            str(tmp_path / "config.yaml"),
            "--port",
            str(SMOKE_PORT),
            "--timeout",
            "90.0",
        ],
    ]
    new_bin = slots.slot_dir(NEW) / "bin"
    assert (new_bin / SERVER_APP).read_text() == f"#!{python}\n# installed\n"
    assert (new_bin / "vibesensor-server").read_text().startswith(f"#!{python} -IS\n")


@pytest.mark.asyncio
async def test_activate_switches_to_the_installed_slot_with_a_pending_boot_check(
    tmp_path: Path,
) -> None:
    installer, slots, _commands, _tracker = _installer(tmp_path)
    await installer.install(_build_wheel(tmp_path / "vibesensor.whl"), WHEELHOUSE, NEW)

    installer.activate(NEW)

    assert slots.active_slot() == NEW
    pending = slots.pending_boot()
    assert pending is not None
    assert (pending.candidate, pending.previous) == (NEW, RUNNING)
    assert pending.health_url == "http://127.0.0.1:80/api/health"


@pytest.mark.asyncio
async def test_install_prunes_slots_older_than_the_active_one(tmp_path: Path) -> None:
    installer, slots, _commands, _tracker = _installer(tmp_path)
    slots.adopt(RUNNING)
    add_slot(slots, "2025.6.1")

    await installer.install(_build_wheel(tmp_path / "vibesensor.whl"), WHEELHOUSE, NEW)

    assert sorted(p.name for p in (slots.root / "slots").iterdir()) == [RUNNING, NEW]


@pytest.mark.parametrize(
    ("match", "rc", "stdout", "error"),
    [
        ("-m venv", 1, "", f"Could not create venv slot {NEW} (exit 1)"),
        ("pip install", 1, "", "Wheel install failed (exit 1)"),
        ("from vibesensor import", 0, "2025.6.13\n", "Installed version does not match"),
        ("smoke-server", 1, "", f"Version {NEW} failed its smoke test (exit 1)"),
    ],
)
@pytest.mark.asyncio
async def test_failed_install_removes_the_new_slot_and_keeps_the_live_one(
    tmp_path: Path,
    match: str,
    rc: int,
    stdout: str,
    error: str,
) -> None:
    installer, slots, commands, _tracker = _installer(tmp_path)
    commands.set_response(match, rc, stdout, "boom")

    with pytest.raises(UpdateReleaseError, match=re.escape(error)) as excinfo:
        await installer.install(_build_wheel(tmp_path / "vibesensor.whl"), WHEELHOUSE, NEW)

    assert excinfo.value.phase == "installing"
    assert slots.active_slot() == RUNNING
    assert not slots.slot_dir(NEW).exists()


@pytest.mark.asyncio
async def test_install_reports_a_missing_server_venv_as_an_update_failure(
    tmp_path: Path,
) -> None:
    installer = ReleaseVenvInstaller(
        commands=RecordingCommands(),
        status=build_update_status_harness(tmp_path / "update_status.json"),
        slots=VenvSlots(tmp_path / "missing" / ".venv"),
        smoke_config=tmp_path / "config.yaml",
        health_url="http://127.0.0.1:80/api/health",
    )

    with pytest.raises(UpdateReleaseError, match="Could not move") as excinfo:
        await installer.install(_build_wheel(tmp_path / "vibesensor.whl"), WHEELHOUSE, NEW)

    assert excinfo.value.phase == "installing"
    assert not (tmp_path / "missing").exists()


@pytest.mark.asyncio
async def test_install_rejects_the_active_version(tmp_path: Path) -> None:
    installer, _slots, commands, _tracker = _installer(tmp_path)

    with pytest.raises(UpdateReleaseError, match="already active"):
        await installer.install(
            _build_wheel(tmp_path / "v.whl", version=RUNNING), WHEELHOUSE, RUNNING
        )

    assert commands.calls == []


@pytest.mark.asyncio
async def test_install_rejects_a_corrupt_wheel_before_touching_slots(tmp_path: Path) -> None:
    installer, slots, commands, _tracker = _installer(tmp_path)
    broken = tmp_path / "broken.whl"
    broken.write_text("not a wheel", encoding="utf-8")

    with pytest.raises(UpdateReleaseError, match="Downloaded wheel is corrupt"):
        await installer.install(broken, WHEELHOUSE, NEW)

    assert commands.calls == []
    assert not slots.is_adopted()


def test_wheel_artifact_problem_flags_invalid_metadata(tmp_path: Path) -> None:
    wheel = _build_wheel(tmp_path / "v.whl", requires_dist=("not a valid requirement ;;;",))

    problem = wheel_artifact_problem(wheel)

    assert problem is not None
    assert problem[0] == "Downloaded wheel metadata is invalid"
    assert wheel_artifact_problem(_build_wheel(tmp_path / "ok.whl")) is None


@pytest.mark.asyncio
async def test_firmware_refresher_runs_the_cache_module_in_the_running_interpreter(
    tmp_path: Path,
) -> None:
    commands = RecordingCommands()
    refresher = FirmwareRefresher(
        commands=commands,
        status=build_update_status_harness(tmp_path / "update_status.json"),
        timeout_s=30,
    )

    result = await refresher.refresh_esp_firmware("server-v2025.6.15")

    assert commands.calls == [
        [
            sys.executable,
            "-m",
            "vibesensor.updates.firmware.firmware_cache",
            "--cache-dir",
            "/var/lib/vibesensor/firmware",
            "--tag",
            "server-v2025.6.15",
        ],
    ]
    assert result == FirmwareRefreshResult.success()
