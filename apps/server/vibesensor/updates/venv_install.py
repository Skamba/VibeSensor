"""Install a release into a new A/B venv slot, smoke-test it, and activate it.

The live slot is never modified: a release is installed into ``slots/<version>``,
checked there, and only then made active with one symlink flip. The boot check
(:mod:`vibesensor.updates.boot_check`) confirms or reverts it after the restart.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path

import msgspec
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from vibesensor.common.exceptions import UpdateReleaseError
from vibesensor.updates.artifact_validation import (
    read_wheel_metadata,
    versions_match,
    wheel_artifact_problem,
    wheel_dependency_issues,
)
from vibesensor.updates.boot_check import HEALTH_DEADLINE_S
from vibesensor.updates.models import UpdatePhase
from vibesensor.updates.runner import CommandExecutionResult, UpdateCommandExecutor
from vibesensor.updates.status.tracker import UpdateStatusTracker
from vibesensor.updates.venv_slots import VenvSlots

__all__ = ["ReleaseVenvInstaller"]

PIP_TIMEOUT_S = 180.0
SMOKE_PORT = 18082
SMOKE_TIMEOUT_S = 90.0
_INSTALLING = UpdatePhase.installing.value


class _TargetEnvironmentSnapshotRequest(msgspec.Struct, kw_only=True, frozen=True):
    """Typed request passed to the target-environment snapshot subprocess."""

    distribution_names: list[str]


class _TargetEnvironmentSnapshotResponse(msgspec.Struct, kw_only=True, frozen=True):
    """Typed response returned by the target-environment snapshot subprocess."""

    python_full_version: str
    marker_environment: dict[str, str]
    installed_versions: dict[str, str]


_TARGET_ENV_SNAPSHOT_SCRIPT = "\n".join(
    [
        "import importlib.metadata as metadata",
        "import msgspec",
        "import sys",
        "from packaging.markers import default_environment",
        "from packaging.utils import canonicalize_name",
        "class TargetEnvironmentSnapshotRequest(msgspec.Struct, kw_only=True, frozen=True):",
        "    distribution_names: list[str]",
        "class TargetEnvironmentSnapshotResponse(msgspec.Struct, kw_only=True, frozen=True):",
        "    python_full_version: str",
        "    marker_environment: dict[str, str]",
        "    installed_versions: dict[str, str]",
        "payload = msgspec.json.decode(sys.argv[1], type=TargetEnvironmentSnapshotRequest)",
        "distribution_names = [",
        "    canonicalize_name(str(name))",
        "    for name in payload.distribution_names",
        "]",
        "installed_versions = {}",
        "for distribution_name in distribution_names:",
        "    try:",
        "        installed_versions[distribution_name] = metadata.version(distribution_name)",
        "    except metadata.PackageNotFoundError:",
        "        installed_versions[distribution_name] = ''",
        "marker_environment = default_environment()",
        "response = TargetEnvironmentSnapshotResponse(",
        "    python_full_version=marker_environment.get('python_full_version', ''),",
        "    marker_environment={",
        "        str(key): str(value) for key, value in marker_environment.items()",
        "    },",
        "    installed_versions=installed_versions,",
        ")",
        "sys.stdout.buffer.write(msgspec.json.encode(response))",
        "sys.stdout.buffer.write(b'\\n')",
    ],
)


def _target_environment_snapshot_request_json(distribution_names: Sequence[str]) -> str:
    """Encode the target-environment snapshot request as one JSON CLI argument."""

    return msgspec.json.encode(
        _TargetEnvironmentSnapshotRequest(distribution_names=list(distribution_names))
    ).decode("utf-8")


def _target_environment_snapshot_response_from_json(
    raw: bytes | str,
) -> _TargetEnvironmentSnapshotResponse:
    """Decode one target-environment snapshot response from subprocess stdout."""

    return msgspec.json.decode(raw, type=_TargetEnvironmentSnapshotResponse)


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

    async def install(self, wheel_path: Path, version: str) -> str:
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
        self._status.log(f"Creating venv slot {version} from {active}")
        try:
            try:
                await asyncio.to_thread(self._slots.clone_slot, active, version)
            except OSError as exc:
                raise _slot_error(f"Could not create venv slot {version}", exc) from exc
            python = str(self._slots.slot_python(version))
            await self._check_dependencies(wheel_path, python)
            await self._run(
                [python, "-m", "pip", "install", "--force-reinstall", "--no-deps", str(wheel_path)],
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
        result = await self._commands.run(args, phase=_INSTALLING, timeout=timeout, sudo=False)
        if result.returncode != 0:
            raise UpdateReleaseError(
                f"{failure} (exit {result.returncode})",
                phase=_INSTALLING,
                detail=result.stderr or result.stdout,
            )
        return result

    async def _check_dependencies(self, wheel_path: Path, python: str) -> None:
        """Refuse a wheel whose dependencies the cloned slot does not satisfy."""
        metadata = read_wheel_metadata(wheel_path)
        requirement_names = sorted(
            {canonicalize_name(Requirement(raw).name) for raw in metadata.requires_dist},
        )
        if not metadata.requires_python and not requirement_names:
            return
        result = await self._run(
            [
                python,
                "-c",
                _TARGET_ENV_SNAPSHOT_SCRIPT,
                _target_environment_snapshot_request_json(requirement_names),
            ],
            failure="Could not validate wheel dependency compatibility",
        )
        try:
            snapshot = _target_environment_snapshot_response_from_json(result.stdout)
        except (msgspec.DecodeError, msgspec.ValidationError) as exc:
            raise UpdateReleaseError(
                "Could not parse wheel dependency compatibility results",
                phase=_INSTALLING,
                detail=result.stdout or result.stderr,
            ) from exc
        issues = wheel_dependency_issues(
            metadata,
            python_full_version=snapshot.python_full_version,
            marker_environment=snapshot.marker_environment,
            installed_versions=snapshot.installed_versions,
        )
        if issues:
            raise UpdateReleaseError(
                "Downloaded wheel is incompatible with the current environment",
                phase=_INSTALLING,
                detail="; ".join(issues),
            )
        self._status.log("Validated wheel dependency compatibility against the new slot")


def _slot_error(message: str, exc: OSError) -> UpdateReleaseError:
    return UpdateReleaseError(message, phase=_INSTALLING, detail=str(exc))
