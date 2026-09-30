"""Low-level install, rollback, and snapshot primitives for updater workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vibesensor.use_cases.updates.artifact_validation import WheelArtifactValidator
from vibesensor.use_cases.updates.rollback import UpdateRollback
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.wheel_installation import WheelInstallExecutor, WheelInstallResult


@dataclass(frozen=True, slots=True)
class UpdateInstallerConfig:
    repo: Path
    rollback_dir: Path
    reinstall_timeout_s: float
    smoke_config_path: Path | None = None


class UpdateInstaller:
    """Expose install-time primitives without embedding rollback policy decisions."""

    __slots__ = ("_config", "_rollback", "_wheel_install_executor")

    def __init__(
        self,
        *,
        commands: UpdateCommandExecutor,
        status: UpdateStatusTracker,
        config: UpdateInstallerConfig,
    ) -> None:
        self._config = config
        wheel_validator = WheelArtifactValidator(
            status=status,
        )
        self._wheel_install_executor = WheelInstallExecutor(
            commands=commands,
            status=status,
            repo=config.repo,
            reinstall_timeout_s=config.reinstall_timeout_s,
            wheel_validator=wheel_validator,
        )
        self._rollback = UpdateRollback(
            commands=commands,
            status=status,
            repo=config.repo,
            rollback_dir=config.rollback_dir,
            config_path=config.smoke_config_path,
            wheel_validator=wheel_validator,
            wheel_install_executor=self._wheel_install_executor,
        )

    async def snapshot_for_rollback(self) -> bool:
        return await self._rollback.snapshot_for_rollback()

    async def install_release(
        self,
        wheel_path: Path,
        expected_version: str,
    ) -> WheelInstallResult:
        return await self._wheel_install_executor.install_release(
            wheel_path,
            expected_version,
        )

    async def rollback(self) -> bool:
        return await self._rollback.rollback()
