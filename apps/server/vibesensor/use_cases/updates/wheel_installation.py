"""Wheel installation and verification for updater-managed server packages."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import msgspec
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from vibesensor.use_cases.updates.artifact_validation import (
    WheelArtifactValidator,
    read_wheel_metadata,
    wheel_dependency_issues,
)
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.venv_paths import reinstall_python_executable


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


@dataclass(frozen=True, slots=True)
class WheelInstallResult:
    succeeded: bool
    rollback_required: bool = False


class WheelInstallExecutor:
    """Install and verify server wheels after updater policy chooses an action."""

    __slots__ = (
        "_commands",
        "_reinstall_timeout_s",
        "_repo",
        "_status",
        "_wheel_validator",
    )

    def __init__(
        self,
        *,
        commands: UpdateCommandExecutor,
        status: UpdateStatusTracker,
        repo: Path,
        reinstall_timeout_s: float,
        wheel_validator: WheelArtifactValidator,
    ) -> None:
        self._commands = commands
        self._status = status
        self._repo = repo
        self._reinstall_timeout_s = reinstall_timeout_s
        self._wheel_validator = wheel_validator

    async def install_release(self, wheel_path: Path, expected_version: str) -> WheelInstallResult:
        """Install a newly downloaded release wheel and report rollback policy needs."""

        if not self._wheel_validator.validate_wheel(
            wheel_path,
            phase="installing",
            context="Downloaded wheel",
            fatal=True,
        ):
            return WheelInstallResult(succeeded=False)

        venv_python = reinstall_python_executable(self._repo)
        if not await self._validate_dependency_compatibility(wheel_path, venv_python=venv_python):
            return WheelInstallResult(succeeded=False)

        install_result = await self._commands.run(
            [
                venv_python,
                "-m",
                "pip",
                "install",
                "--force-reinstall",
                "--no-deps",
                str(wheel_path),
            ],
            phase="installing",
            timeout=self._reinstall_timeout_s,
            sudo=False,
        )
        if install_result.returncode != 0:
            self._status.add_issue(
                "installing",
                f"Wheel install failed (exit {install_result.returncode})",
                install_result.stderr,
            )
            self._status.mark_failed()
            return WheelInstallResult(succeeded=False, rollback_required=True)

        installed_version = await self._verify_installed_version(
            failure_message_prefix="Post-install verification failed",
            fatal=True,
        )
        if installed_version is None:
            return WheelInstallResult(succeeded=False, rollback_required=True)

        self._status.log(f"Installed vibesensor {expected_version}")
        self._status.log(f"Verified installed version: {installed_version}")
        return WheelInstallResult(succeeded=True)

    async def install_rollback_wheel(self, wheel_path: Path, *, expected_version: str) -> bool:
        """Install a previously captured rollback wheel without recursive fallback."""

        venv_python = reinstall_python_executable(self._repo)
        rollback_result = await self._commands.run(
            [
                venv_python,
                "-m",
                "pip",
                "install",
                "--force-reinstall",
                "--no-deps",
                str(wheel_path),
            ],
            phase="installing",
            timeout=self._reinstall_timeout_s,
            sudo=False,
        )
        if rollback_result.returncode != 0:
            self._status.add_issue(
                "installing",
                f"Rollback install failed (exit {rollback_result.returncode})",
                rollback_result.stderr,
            )
            return False

        rolled_back_version = await self._verify_installed_version(
            failure_message_prefix="Post-rollback verification failed",
            fatal=False,
        )
        if rolled_back_version is None:
            return False

        if expected_version and rolled_back_version != expected_version:
            self._status.add_issue(
                "installing",
                "Rolled-back version label mismatch",
                (
                    "wheel filename version="
                    f"{expected_version} but import reports version="
                    f"{rolled_back_version}; "
                    "possible wheel naming issue or pip normalisation difference"
                ),
            )
            self._status.log(
                "WARNING: rolled-back version mismatch "
                f"(wheel={expected_version}, import={rolled_back_version})",
            )
        self._status.log(
            f"Rolled back to {wheel_path.name} (verified version={rolled_back_version})",
        )
        return True

    async def _validate_dependency_compatibility(
        self,
        wheel_path: Path,
        *,
        venv_python: str,
    ) -> bool:
        metadata = read_wheel_metadata(wheel_path)
        requirement_names = sorted(
            {
                canonicalize_name(Requirement(raw_requirement).name)
                for raw_requirement in metadata.requires_dist
            },
        )
        if not metadata.requires_python and not requirement_names:
            return True

        dependency_check = await self._commands.run(
            [
                venv_python,
                "-c",
                _TARGET_ENV_SNAPSHOT_SCRIPT,
                _target_environment_snapshot_request_json(requirement_names),
            ],
            phase="installing",
            timeout=30,
            sudo=False,
        )
        if dependency_check.returncode != 0:
            self._status.add_issue(
                "installing",
                (
                    "Could not validate wheel dependency compatibility "
                    f"(exit {dependency_check.returncode})"
                ),
                dependency_check.stderr or dependency_check.stdout,
            )
            self._status.mark_failed()
            return False
        try:
            snapshot = _target_environment_snapshot_response_from_json(dependency_check.stdout)
        except (msgspec.DecodeError, msgspec.ValidationError):
            self._status.add_issue(
                "installing",
                "Could not parse wheel dependency compatibility results",
                dependency_check.stdout or dependency_check.stderr,
            )
            self._status.mark_failed()
            return False
        issues = wheel_dependency_issues(
            metadata,
            python_full_version=snapshot.python_full_version,
            marker_environment=snapshot.marker_environment,
            installed_versions=snapshot.installed_versions,
        )
        if issues:
            self._status.add_issue(
                "installing",
                "Downloaded wheel is incompatible with the current environment",
                "; ".join(issues),
            )
            self._status.mark_failed()
            return False
        self._status.log(
            "Validated wheel dependency compatibility against target environment",
        )
        return True

    async def _verify_installed_version(
        self,
        *,
        failure_message_prefix: str,
        fatal: bool,
    ) -> str | None:
        venv_python = reinstall_python_executable(self._repo)
        version_check = await self._commands.run(
            [venv_python, "-c", "from vibesensor import __version__; print(__version__)"],
            phase="installing",
            timeout=30,
            sudo=False,
        )
        if version_check.returncode == 0:
            return version_check.stdout.strip()
        message = f"{failure_message_prefix} (exit {version_check.returncode})"
        if fatal:
            self._status.add_issue("installing", message, version_check.stderr)
            self._status.mark_failed()
        else:
            self._status.add_issue("installing", message, version_check.stderr)
        return None
