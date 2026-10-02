"""One update job: the linear async flow for a single updater run.

``UpdateJob.run`` reads top to bottom:

1. validate prerequisites and prepare the requested transport (Wi-Fi or USB),
2. check the latest server release,
3. either refresh ESP firmware only, or stage, snapshot, install (with
   rollback on failure) a new server release,
4. complete transport success and schedule a backend restart,
5. always clean up the transport and refresh runtime details.

``UpdateJob.recover_interrupted`` repairs transport and rollback state after a
server restart interrupted a previous run. Task supervision (timeouts,
cancellation, terminal status) lives in ``manager.py``.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from vibesensor.shared.exceptions import UpdateCleanupError, UpdateError, UpdateReleaseError
from vibesensor.shared.structured_logging import log_extra
from vibesensor.use_cases.updates.firmware.firmware_refresh import FirmwareRefresher
from vibesensor.use_cases.updates.models import (
    UpdateJobStatus,
    UpdatePhase,
    UpdateRequest,
    UpdateState,
    UpdateTerminalState,
    UpdateValidationConfig,
)
from vibesensor.use_cases.updates.release_staging import ServerReleaseStager, StagedServerRelease
from vibesensor.use_cases.updates.releases.release_fetcher import (
    ReleaseInfo,
    ServerReleaseFetcher,
)
from vibesensor.use_cases.updates.releases.version_policy import select_update_release
from vibesensor.use_cases.updates.rollback import UpdateRollback
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status.runtime_details import collect_runtime_details
from vibesensor.use_cases.updates.status.tracker import UpdateStatusTracker
from vibesensor.use_cases.updates.transport.coordinator import UpdateTransportCoordinator
from vibesensor.use_cases.updates.transport.lifecycles import PreparedUpdateTransport
from vibesensor.use_cases.updates.validation import validate_prerequisites
from vibesensor.use_cases.updates.wheel_installation import WheelInstallExecutor

__all__ = ["UPDATE_RESTART_UNIT", "UPDATE_SERVICE_NAME", "UpdateJob"]

LOGGER = logging.getLogger(__name__)

UPDATE_RESTART_UNIT = "vibesensor-post-update-restart"
UPDATE_SERVICE_NAME = "vibesensor.service"

_CLEANUP_FAILED_TERMINAL_STATES = frozenset(
    {
        UpdateTerminalState.cleanup_failed,
        UpdateTerminalState.cancelled_cleanup_failed,
        UpdateTerminalState.timeout_cleanup_failed,
    }
)


def _current_server_version() -> str:
    from vibesensor import __version__ as current_version

    return current_version


class UpdateJob:
    """Run one update request end to end and recover interrupted runs."""

    __slots__ = (
        "_commands",
        "_firmware_refresher",
        "_release_fetcher",
        "_repo",
        "_rollback",
        "_stager",
        "_status",
        "_transport",
        "_validation_config",
        "_wheel_installer",
    )

    def __init__(
        self,
        *,
        status: UpdateStatusTracker,
        commands: UpdateCommandExecutor,
        transport: UpdateTransportCoordinator,
        release_fetcher: ServerReleaseFetcher,
        stager: ServerReleaseStager,
        firmware_refresher: FirmwareRefresher,
        wheel_installer: WheelInstallExecutor,
        rollback: UpdateRollback,
        validation_config: UpdateValidationConfig,
        repo: Path,
    ) -> None:
        self._status = status
        self._commands = commands
        self._transport = transport
        self._release_fetcher = release_fetcher
        self._stager = stager
        self._firmware_refresher = firmware_refresher
        self._wheel_installer = wheel_installer
        self._rollback = rollback
        self._validation_config = validation_config
        self._repo = repo

    # -- the update flow ---------------------------------------------------

    async def run(self, request: UpdateRequest) -> None:
        prepared_transport: PreparedUpdateTransport | None = None
        try:
            await validate_prerequisites(
                commands=self._commands,
                status=self._status,
                config=self._validation_config,
                request=request,
            )
            prepared_transport = await self._transport.prepare(request)

            current_version = _current_server_version()
            self._status.transition(UpdatePhase.checking)
            self._status.log("Checking for available updates...")
            latest_release = await self._find_latest_release()
            release = select_update_release(
                current_version=current_version,
                latest_release=latest_release,
            )
            if release is None:
                self._status.log(f"Already up-to-date (version={current_version})")
                await self._refresh_firmware_only(prepared_transport, latest_release.tag)
            else:
                self._status.log(f"Update available: {current_version} → {release.version}")
                await self._install_release(prepared_transport, release)
        finally:
            await self._finalize(prepared_transport, prior_error=sys.exc_info()[1])

    async def _find_latest_release(self) -> ReleaseInfo:
        try:
            return await asyncio.to_thread(self._release_fetcher.find_latest_release)
        except (OSError, ValueError) as exc:
            raise UpdateReleaseError(
                f"Failed to check for updates: {exc}",
                phase="checking",
            ) from exc

    async def _refresh_firmware_only(
        self,
        prepared_transport: PreparedUpdateTransport,
        latest_tag: str,
    ) -> None:
        refresh_result = await self._firmware_refresher.refresh_esp_firmware(
            pinned_tag=latest_tag,
        )
        if not refresh_result.succeeded:
            raise UpdateReleaseError(
                refresh_result.message,
                phase=refresh_result.phase,
                detail=refresh_result.detail,
                log_message="ESP firmware refresh failed; refresh-only update did not complete",
            )
        await self._complete_success(
            prepared_transport,
            message="No server update needed; ESP firmware checked",
        )

    async def _install_release(
        self,
        prepared_transport: PreparedUpdateTransport,
        release: ReleaseInfo,
    ) -> None:
        async with self._stager.stage(release) as staged_release:
            refresh_result = await self._firmware_refresher.refresh_esp_firmware(
                pinned_tag=staged_release.release.tag,
            )
            if not refresh_result.succeeded:
                self._status.add_issue(
                    refresh_result.phase,
                    refresh_result.message,
                    refresh_result.detail,
                )
                self._status.log(
                    "ESP firmware refresh failed; continuing with existing cache",
                )
            await self._deploy(staged_release)
        await self._complete_success(
            prepared_transport,
            message="Update completed successfully",
        )

    async def _deploy(self, staged_release: StagedServerRelease) -> None:
        """Snapshot, install, and roll back on a failed mutating install."""

        self._status.transition(UpdatePhase.installing)
        self._status.log("Installing update...")
        if not await self._rollback.snapshot_for_rollback():
            raise UpdateReleaseError(
                "Rollback snapshot could not be created",
                phase=UpdatePhase.installing.value,
                detail="Install aborted before mutating the live environment",
            )
        install_result = await self._wheel_installer.install_release(
            staged_release.wheel_path,
            str(staged_release.release.version),
        )
        if install_result.succeeded:
            return
        if not install_result.rollback_required:
            raise UpdateReleaseError("Update install failed")

        self._status.log("Attempting rollback...")
        rollback_succeeded = await self._rollback.rollback()
        if rollback_succeeded:
            raise UpdateReleaseError(
                "Update install failed; rollback restored the previous version",
            )
        raise UpdateReleaseError("Update install failed and rollback did not complete")

    async def _complete_success(
        self,
        prepared_transport: PreparedUpdateTransport,
        *,
        message: str,
    ) -> None:
        await prepared_transport.complete_success()
        self._status.mark_success(message)
        if not await self._schedule_restart():
            self._status.add_issue(
                "done",
                "Backend restart was not scheduled automatically",
                "Run 'sudo systemctl restart vibesensor.service' manually",
            )
            self._status.log("Automatic backend restart scheduling failed")

    async def _schedule_restart(self) -> bool:
        restart_attempts = [
            [
                "systemd-run",
                "--unit",
                UPDATE_RESTART_UNIT,
                "--on-active=2s",
                "systemctl",
                "restart",
                UPDATE_SERVICE_NAME,
            ],
            ["systemctl", "restart", UPDATE_SERVICE_NAME],
        ]
        for command in restart_attempts:
            result = await self._commands.run(
                command,
                phase="done",
                timeout=30,
                sudo=True,
            )
            if result.returncode == 0:
                self._status.log("Scheduled backend service restart")
                return True
        return False

    async def _finalize(
        self,
        prepared_transport: PreparedUpdateTransport | None,
        *,
        prior_error: BaseException | None = None,
    ) -> None:
        """Always clean up the transport and refresh runtime details after a run."""

        try:
            await self._transport.cleanup_after_update(prepared_transport)
            await self._refresh_runtime_details()
        except UpdateCleanupError as exc:
            if prior_error is None:
                raise
            if isinstance(prior_error, asyncio.CancelledError):
                raise UpdateCleanupError(f"Cleanup failed after cancellation: {exc}") from exc
            prior_error.add_note(f"Cleanup also failed: {exc}")

    async def _refresh_runtime_details(self) -> None:
        try:
            runtime_details = await asyncio.to_thread(collect_runtime_details, self._repo)
        except (OSError, UpdateError) as exc:
            LOGGER.exception(
                "update: runtime details refresh error",
                extra=log_extra(
                    event="update_runtime_refresh_error",
                    update_phase="cleanup",
                    repo_path=str(self._repo),
                ),
            )
            raise UpdateCleanupError(
                "Runtime details refresh failed",
                phase="cleanup",
                detail=str(exc),
            ) from exc
        self._status.set_runtime(runtime_details)

    # -- startup recovery --------------------------------------------------

    async def recover_interrupted(self) -> None:
        """Recover transport and rollback state after a server restart mid-update."""

        status = self._status.status
        if status.terminal_state in _CLEANUP_FAILED_TERMINAL_STATES:
            await self._transport.recover_interrupted(status)
            await self._verify_rollback_after_interruption(status)
            return
        if status.state != UpdateState.running or status.finished_at is not None:
            return
        self._status.mark_interrupted("Update interrupted by server restart")
        await self._transport.recover_interrupted(status)
        await self._verify_rollback_after_interruption(status)

    async def _verify_rollback_after_interruption(self, status: UpdateJobStatus) -> None:
        if status.phase is not UpdatePhase.installing:
            return
        await self._rollback.verify_interrupted_install()
