from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pytest

from vibesensor.shared.exceptions import UpdateReleaseError
from vibesensor.use_cases.updates.finalization import UpdateWorkflowFinalizer
from vibesensor.use_cases.updates.firmware import FirmwareRefreshResult
from vibesensor.use_cases.updates.firmware_refresh_execution import (
    RefreshFirmwareExecutionCoordinator,
)
from vibesensor.use_cases.updates.models import (
    UpdateExecutionOutcome,
    UpdateRequest,
    UpdateTransport,
)
from vibesensor.use_cases.updates.run_models import (
    PlannedUpdateRun,
    PreparedUpdateRun,
    RefreshFirmwarePlan,
)
from vibesensor.use_cases.updates.transport.coordinator import UpdateTransportCoordinator
from vibesensor.use_cases.updates.transport.lifecycles import UpdateTransportLifecycles
from vibesensor.use_cases.updates.workflow import UpdateWorkflow
from vibesensor.use_cases.updates.workflow_executor import UpdateWorkflowExecutor
from vibesensor.use_cases.updates.workflow_planner import UpdateWorkflowPlanner


def _request() -> UpdateRequest:
    return UpdateRequest(
        transport=UpdateTransport.wifi,
        ssid="TestNet",
        password="pass123",
    )


@dataclass(slots=True)
class _PreparedTransport:
    transport: UpdateTransport = UpdateTransport.wifi
    cleaned: bool = False

    async def complete_success(self) -> None:
        return None

    async def cleanup_after_update(self) -> None:
        self.cleaned = True


class _UnusedTransportLifecycle(_PreparedTransport):
    async def prepare(self, _request: UpdateRequest) -> _PreparedTransport:
        raise AssertionError("workflow finalizer should only clean the prepared transport")

    async def abort_preparation(self) -> None:
        raise AssertionError("workflow finalizer should not abort preparation")

    async def recover_interrupted_update(self, _status: object) -> None:
        raise AssertionError("workflow finalizer should not recover transport state")


@dataclass(slots=True)
class _RuntimeRefresher:
    refreshed: bool = False

    async def refresh(self) -> None:
        self.refreshed = True


@dataclass(slots=True)
class _FirmwareRefresher:
    result: FirmwareRefreshResult
    pinned_tags: list[str]

    async def refresh_esp_firmware(self, pinned_tag: str = "") -> FirmwareRefreshResult:
        self.pinned_tags.append(pinned_tag)
        return self.result


@dataclass(slots=True)
class _Completion:
    prepared_transport: object | None = None
    message: str | None = None

    async def complete_success(self, prepared_transport: object, *, message: str) -> None:
        self.prepared_transport = prepared_transport
        self.message = message


@dataclass(slots=True)
class _UpdateWorkflowHarness:
    workflow: UpdateWorkflow
    prepared_transport: _PreparedTransport
    runtime_refresher: _RuntimeRefresher
    firmware_refresher: _FirmwareRefresher
    completion: _Completion


class _StaticPreparation:
    def __init__(self, prepared_transport: _PreparedTransport) -> None:
        self._prepared_transport = prepared_transport

    async def prepare(self, _request: UpdateRequest) -> PreparedUpdateRun:
        return PreparedUpdateRun(prepared_transport=self._prepared_transport)


class _StaticReleasePlanner:
    def __init__(self, latest_tag: str) -> None:
        self._latest_tag = latest_tag

    async def plan(self, prepared: PreparedUpdateRun) -> PlannedUpdateRun:
        return PlannedUpdateRun(
            prepared=prepared,
            execution_plan=RefreshFirmwarePlan(latest_tag=self._latest_tag),
        )


class _UnexpectedServerReleaseExecution:
    async def execute(self, *_args: object, **_kwargs: object) -> UpdateExecutionOutcome:
        raise AssertionError("refresh-only workflow should not install a server release")


def _workflow_harness(
    tmp_path: Path,
    *,
    refresh_result: FirmwareRefreshResult,
) -> _UpdateWorkflowHarness:
    del tmp_path
    prepared_transport = _PreparedTransport()
    runtime_refresher = _RuntimeRefresher()
    firmware_refresher = _FirmwareRefresher(refresh_result, pinned_tags=[])
    completion = _Completion()
    planner = UpdateWorkflowPlanner(
        preparation=_StaticPreparation(prepared_transport),
        release_planner=_StaticReleasePlanner("server-v2026.4.3"),
    )
    executor = UpdateWorkflowExecutor(
        refresh_execution=RefreshFirmwareExecutionCoordinator(
            completion=completion,
            firmware_refresher=firmware_refresher,
        ),
        server_release_execution=_UnexpectedServerReleaseExecution(),
    )
    finalizer = UpdateWorkflowFinalizer(
        transport_coordinator=UpdateTransportCoordinator(
            lifecycles=UpdateTransportLifecycles(
                wifi=_UnusedTransportLifecycle(transport=UpdateTransport.wifi),
                usb_internet=_UnusedTransportLifecycle(transport=UpdateTransport.usb_internet),
            ),
            logger=logging.getLogger("vibesensor.tests.update_workflow"),
        ),
        runtime_details_refresher=runtime_refresher,
    )
    return _UpdateWorkflowHarness(
        workflow=UpdateWorkflow(
            planner=planner,
            workflow_executor=executor,
            finalizer=finalizer,
        ),
        prepared_transport=prepared_transport,
        runtime_refresher=runtime_refresher,
        firmware_refresher=firmware_refresher,
        completion=completion,
    )


@pytest.mark.asyncio
async def test_refresh_only_workflow_completes_and_finalizes_transport(tmp_path: Path) -> None:
    harness = _workflow_harness(tmp_path, refresh_result=FirmwareRefreshResult.success())

    await harness.workflow.run(request=_request())

    assert harness.firmware_refresher.pinned_tags == ["server-v2026.4.3"]
    assert harness.completion.prepared_transport is harness.prepared_transport
    assert harness.completion.message == "No server update needed; ESP firmware checked"
    assert harness.prepared_transport.cleaned is True
    assert harness.runtime_refresher.refreshed is True


@pytest.mark.asyncio
async def test_refresh_only_workflow_finalizes_transport_after_execution_failure(
    tmp_path: Path,
) -> None:
    harness = _workflow_harness(
        tmp_path,
        refresh_result=FirmwareRefreshResult.failure(
            message="ESP firmware cache refresh failed",
            detail="cache unavailable",
        ),
    )

    with pytest.raises(UpdateReleaseError, match="ESP firmware cache refresh failed"):
        await harness.workflow.run(request=_request())

    assert harness.firmware_refresher.pinned_tags == ["server-v2026.4.3"]
    assert harness.completion.prepared_transport is None
    assert harness.prepared_transport.cleaned is True
    assert harness.runtime_refresher.refreshed is True
