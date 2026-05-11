"""Execution boundary for refresh-only update plans."""

from __future__ import annotations

from vibesensor.shared.exceptions import UpdateReleaseError
from vibesensor.use_cases.updates.completion import UpdateCompletionCoordinator
from vibesensor.use_cases.updates.firmware import FirmwareRefresher
from vibesensor.use_cases.updates.models import UpdateExecutionOutcome
from vibesensor.use_cases.updates.run_models import PlannedUpdateRun, RefreshFirmwarePlan

__all__ = ["RefreshFirmwareExecutionCoordinator"]


class RefreshFirmwareExecutionCoordinator:
    """Execute the no-server-update path by refreshing firmware and finalizing success."""

    __slots__ = ("_completion", "_firmware_refresher")

    def __init__(
        self,
        *,
        completion: UpdateCompletionCoordinator,
        firmware_refresher: FirmwareRefresher,
    ) -> None:
        self._completion = completion
        self._firmware_refresher = firmware_refresher

    async def execute(
        self,
        workflow: PlannedUpdateRun,
        plan: RefreshFirmwarePlan,
    ) -> UpdateExecutionOutcome:
        refresh_result = await self._firmware_refresher.refresh_esp_firmware(
            pinned_tag=plan.latest_tag,
        )
        if not refresh_result.succeeded:
            raise UpdateReleaseError(
                refresh_result.message,
                phase=refresh_result.phase,
                detail=refresh_result.detail,
                log_message="ESP firmware refresh failed; refresh-only update did not complete",
            )
        await self._completion.complete_success(
            workflow.prepared.prepared_transport,
            message="No server update needed; ESP firmware checked",
        )
        return UpdateExecutionOutcome.refresh_only
