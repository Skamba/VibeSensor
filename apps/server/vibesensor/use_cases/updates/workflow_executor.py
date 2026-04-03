"""Release-execution boundary for update workflows."""

from __future__ import annotations

from collections.abc import Callable

from vibesensor.use_cases.updates.firmware import FirmwareRefresher
from vibesensor.use_cases.updates.release_deployment import UpdateReleaseDeployer
from vibesensor.use_cases.updates.release_planner import (
    InstallServerReleasePlan,
    RefreshFirmwarePlan,
    ReleaseExecutionPlan,
)
from vibesensor.use_cases.updates.release_staging import ServerReleaseStager
from vibesensor.use_cases.updates.success_finalizer import UpdateSuccessFinalizer
from vibesensor.use_cases.updates.transport_sessions import UpdateTransportSession

__all__ = ["UpdateWorkflowExecutor"]


class UpdateWorkflowExecutor:
    """Execute a prepared release plan while delegating side effects to focused collaborators."""

    __slots__ = (
        "_cancel_requested",
        "_deployer",
        "_firmware_refresher",
        "_finalizer",
        "_stager",
    )

    def __init__(
        self,
        *,
        stager: ServerReleaseStager,
        deployer: UpdateReleaseDeployer,
        firmware_refresher: FirmwareRefresher,
        finalizer: UpdateSuccessFinalizer,
        cancel_requested: Callable[[], bool],
    ) -> None:
        self._stager = stager
        self._deployer = deployer
        self._firmware_refresher = firmware_refresher
        self._finalizer = finalizer
        self._cancel_requested = cancel_requested

    async def execute(
        self,
        plan: ReleaseExecutionPlan,
        *,
        transport_session: UpdateTransportSession,
    ) -> bool:
        if isinstance(plan, RefreshFirmwarePlan):
            return await self._execute_refresh_only(plan, transport_session=transport_session)
        return await self._execute_install(plan, transport_session=transport_session)

    async def _execute_refresh_only(
        self,
        plan: RefreshFirmwarePlan,
        *,
        transport_session: UpdateTransportSession,
    ) -> bool:
        await self._firmware_refresher.refresh_esp_firmware(pinned_tag=plan.latest_tag)
        if self._cancelled():
            return False
        return await self._finalizer.complete(
            transport_session,
            message="No server update needed; ESP firmware checked",
        )

    async def _execute_install(
        self,
        plan: InstallServerReleasePlan,
        *,
        transport_session: UpdateTransportSession,
    ) -> bool:
        async with self._stager.stage(plan.release) as staged_release:
            if staged_release is None or self._cancelled():
                return False
            if not await self._deployer.deploy(staged_release):
                return False
        if self._cancelled():
            return False
        return await self._finalizer.complete(
            transport_session,
            message="Update completed successfully",
        )

    def _cancelled(self) -> bool:
        return self._cancel_requested()
