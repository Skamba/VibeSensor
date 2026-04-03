"""Wheel installation and verification for updater-managed server packages."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from vibesensor.use_cases.updates.artifact_validation import (
    WheelArtifactValidator,
    read_wheel_metadata,
    wheel_dependency_issues,
)
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusController, UpdateStatusRecorder
from vibesensor.use_cases.updates.venv_paths import reinstall_python_executable

_TARGET_ENV_SNAPSHOT_SCRIPT = "\n".join(
    [
        "import importlib.metadata as metadata",
        "import json",
        "import sys",
        "from packaging.markers import default_environment",
        "from packaging.utils import canonicalize_name",
        "payload = json.loads(sys.argv[1])",
        "distribution_names = [",
        "    canonicalize_name(str(name))",
        "    for name in payload.get('distribution_names', [])",
        "]",
        "installed_versions = {}",
        "for distribution_name in distribution_names:",
        "    try:",
        "        installed_versions[distribution_name] = metadata.version(distribution_name)",
        "    except metadata.PackageNotFoundError:",
        "        installed_versions[distribution_name] = ''",
        "marker_environment = default_environment()",
        "print(json.dumps({",
        "    'python_full_version': marker_environment.get('python_full_version', ''),",
        "    'marker_environment': marker_environment,",
        "    'installed_versions': installed_versions,",
        "}))",
    ],
)


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
        "_status_controller",
        "_status_recorder",
        "_wheel_validator",
    )

    def __init__(
        self,
        *,
        commands: UpdateCommandExecutor,
        status_controller: UpdateStatusController,
        status_recorder: UpdateStatusRecorder,
        repo: Path,
        reinstall_timeout_s: float,
        wheel_validator: WheelArtifactValidator,
    ) -> None:
        self._commands = commands
        self._status_controller = status_controller
        self._status_recorder = status_recorder
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

        rc, _, stderr = await self._commands.run(
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
        if rc != 0:
            self._status_recorder.add_issue(
                "installing",
                f"Wheel install failed (exit {rc})",
                stderr,
            )
            self._status_controller.mark_failed()
            return WheelInstallResult(succeeded=False, rollback_required=True)

        installed_version = await self._verify_installed_version(
            failure_message_prefix="Post-install verification failed",
            fatal=True,
        )
        if installed_version is None:
            return WheelInstallResult(succeeded=False, rollback_required=True)

        self._status_recorder.log(f"Installed vibesensor {expected_version}")
        self._status_recorder.log(f"Verified installed version: {installed_version}")
        return WheelInstallResult(succeeded=True)

    async def install_rollback_wheel(self, wheel_path: Path, *, expected_version: str) -> bool:
        """Install a previously captured rollback wheel without recursive fallback."""

        venv_python = reinstall_python_executable(self._repo)
        rc, _, stderr = await self._commands.run(
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
        if rc != 0:
            self._status_recorder.add_issue(
                "installing",
                f"Rollback install failed (exit {rc})",
                stderr,
            )
            return False

        rolled_back_version = await self._verify_installed_version(
            failure_message_prefix="Post-rollback verification failed",
            fatal=False,
        )
        if rolled_back_version is None:
            return False

        if expected_version and rolled_back_version != expected_version:
            self._status_recorder.add_issue(
                "installing",
                "Rolled-back version label mismatch",
                (
                    "wheel filename version="
                    f"{expected_version} but import reports version="
                    f"{rolled_back_version}; "
                    "possible wheel naming issue or pip normalisation difference"
                ),
            )
            self._status_recorder.log(
                "WARNING: rolled-back version mismatch "
                f"(wheel={expected_version}, import={rolled_back_version})",
            )
        self._status_recorder.log(
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

        rc, stdout, stderr = await self._commands.run(
            [
                venv_python,
                "-c",
                _TARGET_ENV_SNAPSHOT_SCRIPT,
                json.dumps({"distribution_names": requirement_names}),
            ],
            phase="installing",
            timeout=30,
            sudo=False,
        )
        if rc != 0:
            self._status_recorder.add_issue(
                "installing",
                f"Could not validate wheel dependency compatibility (exit {rc})",
                stderr or stdout,
            )
            self._status_controller.mark_failed()
            return False
        try:
            snapshot = json.loads(stdout or "{}")
        except json.JSONDecodeError:
            self._status_recorder.add_issue(
                "installing",
                "Could not parse wheel dependency compatibility results",
                stdout or stderr,
            )
            self._status_controller.mark_failed()
            return False

        marker_environment_raw = snapshot.get("marker_environment", {})
        installed_versions_raw = snapshot.get("installed_versions", {})
        if not isinstance(marker_environment_raw, dict) or not isinstance(
            installed_versions_raw,
            dict,
        ):
            self._status_recorder.add_issue(
                "installing",
                "Could not parse wheel dependency compatibility results",
                stdout or stderr,
            )
            self._status_controller.mark_failed()
            return False
        issues = wheel_dependency_issues(
            metadata,
            python_full_version=str(snapshot.get("python_full_version") or ""),
            marker_environment={
                str(key): str(value)
                for key, value in marker_environment_raw.items()
                if isinstance(key, str)
            },
            installed_versions={
                str(key): str(value)
                for key, value in installed_versions_raw.items()
                if isinstance(key, str)
            },
        )
        if issues:
            self._status_recorder.add_issue(
                "installing",
                "Downloaded wheel is incompatible with the current environment",
                "; ".join(issues),
            )
            self._status_controller.mark_failed()
            return False
        self._status_recorder.log(
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
        rc, stdout, stderr = await self._commands.run(
            [venv_python, "-c", "from vibesensor import __version__; print(__version__)"],
            phase="installing",
            timeout=30,
            sudo=False,
        )
        if rc == 0:
            return stdout.strip()
        message = f"{failure_message_prefix} (exit {rc})"
        if fatal:
            self._status_recorder.add_issue("installing", message, stderr)
            self._status_controller.mark_failed()
        else:
            self._status_recorder.add_issue("installing", message, stderr)
        return None
