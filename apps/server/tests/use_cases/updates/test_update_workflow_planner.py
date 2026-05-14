from __future__ import annotations

import pytest

from vibesensor.shared.exceptions import UpdatePreparationError
from vibesensor.use_cases.updates.models import UpdateRequest, UpdateTransport
from vibesensor.use_cases.updates.run_models import PlannedUpdateRun, PreparedUpdateRun
from vibesensor.use_cases.updates.workflow_planner import UpdateWorkflowPlanner


def _request() -> UpdateRequest:
    return UpdateRequest(
        transport=UpdateTransport.wifi,
        ssid="TestNet",
        password="pass123",
    )


class RecordingPreparation:
    def __init__(self, prepared: PreparedUpdateRun) -> None:
        self.prepared = prepared
        self.requests: list[UpdateRequest] = []
        self.error: UpdatePreparationError | None = None

    async def prepare(self, request: UpdateRequest) -> PreparedUpdateRun:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.prepared


class RecordingReleasePlanner:
    def __init__(self, result: PlannedUpdateRun) -> None:
        self.result = result
        self.prepared_runs: list[PreparedUpdateRun] = []

    async def plan(self, prepared: PreparedUpdateRun) -> PlannedUpdateRun:
        self.prepared_runs.append(prepared)
        return self.result


def _planner() -> tuple[
    UpdateWorkflowPlanner,
    RecordingPreparation,
    RecordingReleasePlanner,
    PreparedUpdateRun,
    PlannedUpdateRun,
]:
    prepared = PreparedUpdateRun(prepared_transport=object())
    planning_result = PlannedUpdateRun(prepared=prepared, execution_plan=object())
    preparation = RecordingPreparation(prepared)
    release_planner = RecordingReleasePlanner(planning_result)
    return (
        UpdateWorkflowPlanner(
            preparation=preparation,
            release_planner=release_planner,
        ),
        preparation,
        release_planner,
        prepared,
        planning_result,
    )


@pytest.mark.asyncio
async def test_plan_prepares_transport_before_release_planning() -> None:
    planner, preparation, release_planner, prepared, planning_result = _planner()
    request = _request()
    observed: list[PreparedUpdateRun] = []

    result = await planner.plan(request, on_prepared=observed.append)

    assert result is planning_result
    assert observed == [prepared]
    assert preparation.requests == [request]
    assert release_planner.prepared_runs == [prepared]


@pytest.mark.asyncio
async def test_plan_stops_before_release_planning_when_preparation_fails() -> None:
    planner, preparation, release_planner, _prepared, _planning_result = _planner()
    preparation.error = UpdatePreparationError("validation failed")

    with pytest.raises(UpdatePreparationError, match="validation failed"):
        await planner.plan(_request())

    assert release_planner.prepared_runs == []
