from __future__ import annotations

import asyncio

import pytest

from vibesensor.shared.exceptions import UpdateCleanupError
from vibesensor.use_cases.updates.finalization import UpdateWorkflowFinalizer


class RecordingTransportCoordinator:
    def __init__(self, *, cleanup_error: UpdateCleanupError | None = None) -> None:
        self.cleanup_error = cleanup_error
        self.cleaned_transports: list[object | None] = []

    async def cleanup_after_update(self, prepared_transport: object | None) -> None:
        self.cleaned_transports.append(prepared_transport)
        if self.cleanup_error is not None:
            raise self.cleanup_error


class RecordingRuntimeDetailsRefresher:
    def __init__(self) -> None:
        self.refreshed = False

    async def refresh(self) -> None:
        self.refreshed = True


@pytest.mark.asyncio
async def test_finalizer_cleans_up_transport_then_refreshes_runtime() -> None:
    transport_coordinator = RecordingTransportCoordinator()
    runtime_details_refresher = RecordingRuntimeDetailsRefresher()
    prepared_transport = object()
    finalizer = UpdateWorkflowFinalizer(
        transport_coordinator=transport_coordinator,
        runtime_details_refresher=runtime_details_refresher,
    )

    await finalizer.finalize(prepared_transport)

    assert transport_coordinator.cleaned_transports == [prepared_transport]
    assert runtime_details_refresher.refreshed is True


@pytest.mark.asyncio
async def test_finalizer_adds_cleanup_note_to_prior_failure() -> None:
    transport_coordinator = RecordingTransportCoordinator(
        cleanup_error=UpdateCleanupError("transport cleanup failed"),
    )
    runtime_details_refresher = RecordingRuntimeDetailsRefresher()
    finalizer = UpdateWorkflowFinalizer(
        transport_coordinator=transport_coordinator,
        runtime_details_refresher=runtime_details_refresher,
    )
    workflow_error = RuntimeError("workflow bug")

    await finalizer.finalize(object(), prior_error=workflow_error)

    assert workflow_error.__notes__ == ["Cleanup also failed: transport cleanup failed"]
    assert runtime_details_refresher.refreshed is False


@pytest.mark.asyncio
async def test_finalizer_raises_cleanup_error_when_cleanup_fails_after_cancellation() -> None:
    transport_coordinator = RecordingTransportCoordinator(
        cleanup_error=UpdateCleanupError("transport cleanup failed"),
    )
    runtime_details_refresher = RecordingRuntimeDetailsRefresher()
    finalizer = UpdateWorkflowFinalizer(
        transport_coordinator=transport_coordinator,
        runtime_details_refresher=runtime_details_refresher,
    )

    with pytest.raises(
        UpdateCleanupError,
        match="Cleanup failed after cancellation: transport cleanup failed",
    ):
        await finalizer.finalize(object(), prior_error=asyncio.CancelledError())
