"""Canonical end-to-end update coordination boundary."""

from __future__ import annotations

from collections.abc import Callable

from vibesensor.use_cases.updates.firmware import FirmwareRefresher
from vibesensor.use_cases.updates.models import UpdatePhase, UpdateRequest, UpdateValidationConfig
from vibesensor.use_cases.updates.release_deployment import UpdateReleaseDeployer
from vibesensor.use_cases.updates.release_resolution import ServerReleaseResolver
from vibesensor.use_cases.updates.release_staging import ServerReleaseStager
from vibesensor.use_cases.updates.restart_scheduler import UpdateRestartScheduler
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.transport_sessions import (
    UpdateTransportSession,
    UpdateTransportSessions,
)
from vibesensor.use_cases.updates.validation import validate_prerequisites


class UpdateCoordinator:
    """Own validation, transport preparation, release work, and success finalization."""

    __slots__ = (
        "_cancel_requested",
        "_commands",
        "_deployer",
        "_firmware_refresher",
        "_resolver",
        "_restart_scheduler",
        "_stager",
        "_tracker",
        "_transport_sessions",
        "_validation_config",
    )

    def __init__(
        self,
        *,
        tracker: UpdateStatusTracker,
        commands: UpdateCommandExecutor,
        transport_sessions: UpdateTransportSessions,
        resolver: ServerReleaseResolver,
        stager: ServerReleaseStager,
        deployer: UpdateReleaseDeployer,
        firmware_refresher: FirmwareRefresher,
        restart_scheduler: UpdateRestartScheduler,
        cancel_requested: Callable[[], bool],
        validation_config: UpdateValidationConfig,
    ) -> None:
        self._tracker = tracker
        self._commands = commands
        self._transport_sessions = transport_sessions
        self._resolver = resolver
        self._stager = stager
        self._deployer = deployer
        self._firmware_refresher = firmware_refresher
        self._restart_scheduler = restart_scheduler
        self._cancel_requested = cancel_requested
        self._validation_config = validation_config

    async def execute(self, request: UpdateRequest) -> None:
        if not await self._validate(request):
            return
        transport_session = await self._prepare_transport(request)
        if transport_session is None or self._cancelled():
            return

        self._tracker.transition(UpdatePhase.checking)
        self._tracker.log("Checking for available updates...")
        from vibesensor import __version__ as current_version

        resolution = await self._resolver.resolve(current_version)
        if resolution.failed:
            return
        if resolution.release is None:
            await self._complete_current_version(
                transport_session,
                current_version=current_version,
                latest_tag=resolution.latest_tag,
            )
            return

        self._tracker.log(
            f"Update available: {current_version} → {resolution.release.version}",
        )
        if self._cancelled():
            return

        async with self._stager.stage(resolution.release) as staged_release:
            if staged_release is None or self._cancelled():
                return
            if not await self._deployer.deploy(staged_release):
                return

        if self._cancelled():
            return
        await self._finalize_success(transport_session)

    async def _validate(self, request: UpdateRequest) -> bool:
        if not await validate_prerequisites(
            commands=self._commands,
            tracker=self._tracker,
            config=self._validation_config,
            request=request,
        ):
            return False
        return not self._cancelled()

    async def _prepare_transport(
        self,
        request: UpdateRequest,
    ) -> UpdateTransportSession | None:
        transport_session = self._transport_sessions.for_request(request)
        if not await transport_session.prepare(request):
            return None
        return transport_session

    async def _complete_current_version(
        self,
        transport_session: UpdateTransportSession,
        *,
        current_version: str,
        latest_tag: str,
    ) -> None:
        self._tracker.log(f"Already up-to-date (version={current_version})")
        await self._firmware_refresher.refresh_esp_firmware(pinned_tag=latest_tag)
        if self._cancelled():
            return
        await transport_session.complete_success("No server update needed; ESP firmware checked")

    async def _finalize_success(self, transport_session: UpdateTransportSession) -> None:
        if not await transport_session.complete_success("Update completed successfully"):
            return
        if await self._restart_scheduler.schedule():
            return
        self._tracker.add_issue(
            "done",
            "Backend restart was not scheduled automatically",
            "Run 'sudo systemctl restart vibesensor.service' manually",
        )
        self._tracker.log("Automatic backend restart scheduling failed")

    def _cancelled(self) -> bool:
        return self._cancel_requested()
