"""Install a release into a new A/B venv slot, smoke-test it, and activate it.

The live slot is never modified: a release is installed into a fresh venv at
``slots/<version>`` from the release's own dependency wheelhouse (offline,
``--no-index``), checked there, and only then made active with one symlink
flip. The boot check (:mod:`vibesensor.updates.boot_check`) confirms or
reverts it after the restart.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from vibesensor.common.exceptions import UpdateReleaseError
from vibesensor.updates.artifact_validation import versions_match, wheel_artifact_problem
from vibesensor.updates.boot_check import HEALTH_DEADLINE_S
from vibesensor.updates.models import UpdatePhase
from vibesensor.updates.runner import CommandExecutionResult, UpdateCommandExecutor
from vibesensor.updates.status.tracker import UpdateStatusTracker
from vibesensor.updates.venv_slots import VenvSlots

__all__ = ["ReleaseVenvInstaller"]

VENV_TIMEOUT_S = 120.0
PIP_TIMEOUT_S = 420.0
SMOKE_PORT = 18082
SMOKE_TIMEOUT_S = 90.0
_INSTALLING = UpdatePhase.installing.value


class ReleaseVenvInstaller:
    """Own the install -> smoke -> activate steps for one release."""

    __slots__ = ("_commands", "_health_url", "_slots", "_smoke_config", "_status")

    def __init__(
        self,
        *,
        commands: UpdateCommandExecutor,
        status: UpdateStatusTracker,
        slots: VenvSlots,
        smoke_config: Path,
        health_url: str,
    ) -> None:
        self._commands = commands
        self._status = status
        self._slots = slots
        self._smoke_config = smoke_config
        self._health_url = health_url

    async def install(self, wheel_path: Path, wheelhouse_dir: Path, version: str) -> str:
        """Build slot *version* next to the live one and smoke-test it; return its name."""
        problem = wheel_artifact_problem(wheel_path)
        if problem is not None:
            raise UpdateReleaseError(problem[0], phase=_INSTALLING, detail=problem[1])
        active = await self._active_slot()
        if version == active:
            raise UpdateReleaseError(f"Version {version} is already active", phase=_INSTALLING)
        try:
            await asyncio.to_thread(self._slots.prune, active)
        except OSError as exc:
            raise _slot_error("Could not remove old venv slots", exc) from exc
        self._status.log(f"Creating venv slot {version}")
        try:
            # The running interpreter may itself be a venv; venv builds on its base Python.
            await self._run(
                [sys.executable, "-m", "venv", str(self._slots.slot_dir(version))],
                failure=f"Could not create venv slot {version}",
                timeout=VENV_TIMEOUT_S,
            )
            python = str(self._slots.slot_python(version))
            self._status.log("Installing the release and its dependencies from the wheelhouse")
            await self._run(
                [
                    python,
                    "-m",
                    "pip",
                    "install",
                    "--no-index",
                    "--find-links",
                    str(wheelhouse_dir),
                    f"{wheel_path}[esp]",
                ],
                failure="Wheel install failed",
                timeout=PIP_TIMEOUT_S,
            )
            installed = await self._run(
                [python, "-c", "from vibesensor import __version__; print(__version__)"],
                failure="Installed version check failed",
            )
            if not versions_match(installed.stdout.strip(), version):
                raise UpdateReleaseError(
                    "Installed version does not match the release",
                    phase=_INSTALLING,
                    detail=f"expected {version}, slot reports {installed.stdout.strip()!r}",
                )
            try:
                await asyncio.to_thread(self._slots.install_launcher, version)
            except OSError as exc:
                raise _slot_error("Could not install the boot-check launcher", exc) from exc
            self._status.log(f"Smoke-testing {version} in an isolated server...")
            await self._run(
                [
                    python,
                    "-m",
                    "vibesensor.updates.releases.release_validation",
                    "smoke-server",
                    "--config",
                    str(self._smoke_config),
                    "--port",
                    str(SMOKE_PORT),
                    "--timeout",
                    str(SMOKE_TIMEOUT_S),
                ],
                failure=f"Version {version} failed its smoke test",
                timeout=SMOKE_TIMEOUT_S + 30,
            )
        except BaseException:
            self._status.log(f"Removing incomplete venv slot {version}")
            self._slots.remove_slot(version)
            raise
        self._status.log(f"Venv slot {version} installed and smoke-tested")
        return version

    def activate(self, slot: str) -> None:
        """Arm the boot check and switch the active slot to *slot*."""
        try:
            self._slots.activate(slot, health_url=self._health_url)
        except OSError as exc:
            raise _slot_error(f"Could not switch to venv slot {slot}", exc) from exc
        self._status.log(
            f"Switched to {slot}; it reverts automatically unless healthy "
            f"within {HEALTH_DEADLINE_S:.0f} s of restarting",
        )

    async def _active_slot(self) -> str:
        if not self._slots.is_adopted():
            from vibesensor import __version__ as running_version

            self._status.log(f"Moving the existing venv into slot {running_version} (one-time)")
            try:
                await asyncio.to_thread(self._slots.adopt, running_version)
            except OSError as exc:
                raise _slot_error(f"Could not move {self._slots.root} into a slot", exc) from exc
        active = self._slots.active_slot()
        if active is None:
            raise UpdateReleaseError("No active venv slot", phase=_INSTALLING)
        return active

    async def _run(
        self,
        args: list[str],
        *,
        failure: str,
        timeout: float = 30.0,
    ) -> CommandExecutionResult:
        result = await self._commands.run(args, phase=_INSTALLING, timeout=timeout)
        if result.returncode != 0:
            raise UpdateReleaseError(
                f"{failure} (exit {result.returncode})",
                phase=_INSTALLING,
                detail=result.stderr or result.stdout,
            )
        return result


def _slot_error(message: str, exc: OSError) -> UpdateReleaseError:
    return UpdateReleaseError(message, phase=_INSTALLING, detail=str(exc))
