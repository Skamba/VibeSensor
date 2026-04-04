from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibesensor.shared.exceptions import UpdateCleanupError
from vibesensor.use_cases.updates.finalization import UpdateWorkflowFinalizer


@pytest.mark.asyncio
async def test_finalizer_cleans_up_transport_then_refreshes_runtime() -> None:
    transport_coordinator = MagicMock()
    transport_coordinator.cleanup_after_update = AsyncMock()
    runtime_details_refresher = MagicMock()
    runtime_details_refresher.refresh = AsyncMock()
    prepared_transport = MagicMock()
    finalizer = UpdateWorkflowFinalizer(
        transport_coordinator=transport_coordinator,
        runtime_details_refresher=runtime_details_refresher,
    )

    await finalizer.finalize(prepared_transport)

    transport_coordinator.cleanup_after_update.assert_awaited_once_with(prepared_transport)
    runtime_details_refresher.refresh.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_finalizer_adds_cleanup_note_to_prior_failure() -> None:
    transport_coordinator = MagicMock()
    transport_coordinator.cleanup_after_update = AsyncMock(
        side_effect=UpdateCleanupError("transport cleanup failed"),
    )
    runtime_details_refresher = MagicMock()
    runtime_details_refresher.refresh = AsyncMock()
    finalizer = UpdateWorkflowFinalizer(
        transport_coordinator=transport_coordinator,
        runtime_details_refresher=runtime_details_refresher,
    )
    workflow_error = RuntimeError("workflow bug")

    await finalizer.finalize(MagicMock(), prior_error=workflow_error)

    assert workflow_error.__notes__ == ["Cleanup also failed: transport cleanup failed"]
    runtime_details_refresher.refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_finalizer_raises_cleanup_error_when_cleanup_fails_after_cancellation() -> None:
    transport_coordinator = MagicMock()
    transport_coordinator.cleanup_after_update = AsyncMock(
        side_effect=UpdateCleanupError("transport cleanup failed"),
    )
    runtime_details_refresher = MagicMock()
    runtime_details_refresher.refresh = AsyncMock()
    finalizer = UpdateWorkflowFinalizer(
        transport_coordinator=transport_coordinator,
        runtime_details_refresher=runtime_details_refresher,
    )

    with pytest.raises(
        UpdateCleanupError,
        match="Cleanup failed after cancellation: transport cleanup failed",
    ):
        await finalizer.finalize(MagicMock(), prior_error=asyncio.CancelledError())
