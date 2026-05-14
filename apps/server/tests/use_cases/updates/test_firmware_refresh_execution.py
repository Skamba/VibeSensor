from __future__ import annotations

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


class RecordingCompletion:
    def __init__(self) -> None:
        self.successes: list[tuple[object, str]] = []

    async def complete_success(self, prepared_transport: object, *, message: str) -> None:
        self.successes.append((prepared_transport, message))


class RecordingFirmwareRefresher:
    def __init__(self, result: FirmwareRefreshResult) -> None:
        self.result = result
        self.pinned_tags: list[str] = []

    async def refresh_esp_firmware(self, pinned_tag: str = "") -> FirmwareRefreshResult:
        self.pinned_tags.append(pinned_tag)
        return self.result


def _coordinator() -> tuple[
    RefreshFirmwareExecutionCoordinator,
    RecordingCompletion,
    RecordingFirmwareRefresher,
]:
    completion = RecordingCompletion()
    firmware_refresher = RecordingFirmwareRefresher(FirmwareRefreshResult.success())
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
    prepared_transport = object()
    workflow, plan = _refresh_workflow(prepared_transport)

    completed = await coordinator.execute(workflow, plan)

    assert completed == UpdateExecutionOutcome.refresh_only
    assert firmware_refresher.pinned_tags == ["server-v2026.4.3"]
    assert completion.successes == [
        (prepared_transport, "No server update needed; ESP firmware checked"),
    ]


@pytest.mark.asyncio
async def test_execute_refresh_plan_fails_when_firmware_refresh_fails() -> None:
    coordinator, completion, firmware_refresher = _coordinator()
    workflow, plan = _refresh_workflow(object())
    firmware_refresher.result = FirmwareRefreshResult.failure(
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
    assert completion.successes == []
