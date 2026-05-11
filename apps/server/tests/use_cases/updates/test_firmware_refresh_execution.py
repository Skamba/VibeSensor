from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from vibesensor.shared.exceptions import UpdateReleaseError
from vibesensor.use_cases.updates.firmware import FirmwareRefreshResult
from vibesensor.use_cases.updates.firmware_refresh_execution import (
    RefreshFirmwareExecutionCoordinator,
)
from vibesensor.use_cases.updates.models import UpdateExecutionOutcome, UpdatePhase
from vibesensor.use_cases.updates.run_models import (
    PlannedUpdateRun,
    PreparedUpdateRun,
    RefreshFirmwarePlan,
)


def _coordinator() -> tuple[
    RefreshFirmwareExecutionCoordinator,
    MagicMock,
    MagicMock,
]:
    completion = MagicMock()
    completion.complete_success = AsyncMock()
    firmware_refresher = MagicMock()
    firmware_refresher.refresh_esp_firmware = AsyncMock(
        return_value=FirmwareRefreshResult.success(),
    )
    return (
        RefreshFirmwareExecutionCoordinator(
            completion=completion,
            firmware_refresher=firmware_refresher,
        ),
        completion,
        firmware_refresher,
    )


def _refresh_workflow(prepared_transport: object) -> tuple[PlannedUpdateRun, RefreshFirmwarePlan]:
    plan = RefreshFirmwarePlan(
        latest_tag="server-v2026.4.3",
    )
    return (
        PlannedUpdateRun(
            prepared=PreparedUpdateRun(
                prepared_transport=prepared_transport,
            ),
            execution_plan=plan,
        ),
        plan,
    )


@pytest.mark.asyncio
async def test_execute_refresh_plan_refreshes_firmware_then_completes_success() -> None:
    coordinator, completion, firmware_refresher = _coordinator()
    prepared_transport = MagicMock()
    workflow, plan = _refresh_workflow(prepared_transport)

    completed = await coordinator.execute(workflow, plan)

    assert completed == UpdateExecutionOutcome.refresh_only
    firmware_refresher.refresh_esp_firmware.assert_awaited_once_with(
        pinned_tag="server-v2026.4.3",
    )
    completion.complete_success.assert_awaited_once_with(
        prepared_transport,
        message="No server update needed; ESP firmware checked",
    )


@pytest.mark.asyncio
async def test_execute_refresh_plan_fails_when_firmware_refresh_fails() -> None:
    coordinator, completion, firmware_refresher = _coordinator()
    workflow, plan = _refresh_workflow(MagicMock())
    firmware_refresher.refresh_esp_firmware.return_value = FirmwareRefreshResult.failure(
        message="ESP firmware cache refresh failed (exit 1)",
        detail="cache unavailable",
    )

    with pytest.raises(UpdateReleaseError, match="ESP firmware cache refresh failed") as excinfo:
        await coordinator.execute(workflow, plan)

    assert excinfo.value.phase == UpdatePhase.downloading.value
    assert excinfo.value.detail == "cache unavailable"
    assert (
        excinfo.value.log_message
        == "ESP firmware refresh failed; refresh-only update did not complete"
    )
    completion.complete_success.assert_not_awaited()
