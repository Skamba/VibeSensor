from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

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


def _planner() -> tuple[UpdateWorkflowPlanner, MagicMock, MagicMock, PreparedUpdateRun]:
    prepared = PreparedUpdateRun(prepared_transport=object())
    planning_result = MagicMock(spec=PlannedUpdateRun)
    preparation = MagicMock()
    preparation.prepare = AsyncMock(return_value=prepared)
    release_planner = MagicMock()
    release_planner.plan = AsyncMock(return_value=planning_result)
    return (
        UpdateWorkflowPlanner(
            preparation=preparation,
            release_planner=release_planner,
        ),
        preparation,
        release_planner,
        prepared,
    )


@pytest.mark.asyncio
async def test_plan_prepares_transport_before_release_planning() -> None:
    planner, preparation, release_planner, prepared = _planner()
    request = _request()
    observed: list[PreparedUpdateRun] = []

    result = await planner.plan(request, on_prepared=observed.append)

    assert result is release_planner.plan.return_value
    assert observed == [prepared]
    preparation.prepare.assert_awaited_once_with(request)
    release_planner.plan.assert_awaited_once_with(prepared)


@pytest.mark.asyncio
async def test_plan_stops_before_release_planning_when_preparation_fails() -> None:
    planner, preparation, release_planner, _prepared = _planner()
    preparation.prepare.side_effect = UpdatePreparationError("validation failed")

    with pytest.raises(UpdatePreparationError, match="validation failed"):
        await planner.plan(_request())

    release_planner.plan.assert_not_awaited()
