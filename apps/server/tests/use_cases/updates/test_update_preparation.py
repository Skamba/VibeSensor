from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from test_support.update_status import build_update_status_harness

from vibesensor.shared.exceptions import UpdatePreparationError, UpdateTransportError
from vibesensor.use_cases.updates.models import (
    UpdateRequest,
    UpdateTransport,
    UpdateValidationConfig,
)
from vibesensor.use_cases.updates.preparation import UpdatePreparationCoordinator
from vibesensor.use_cases.updates.run_models import PreparedUpdateRun
from vibesensor.use_cases.updates.status import UpdateStatusTracker


def _wifi_request(ssid: str = "TestNet", password: str = "pass123") -> UpdateRequest:
    return UpdateRequest(
        transport=UpdateTransport.wifi,
        ssid=ssid,
        password=password,
    )


class RecordingTransportCoordinator:
    def __init__(self, prepared_transport: object) -> None:
        self.prepared_transport = prepared_transport
        self.requests: list[UpdateRequest] = []
        self.error: UpdateTransportError | None = None

    async def prepare(self, request: UpdateRequest) -> object:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.prepared_transport


def _build_preparation(
    tmp_path: Path,
) -> tuple[
    UpdatePreparationCoordinator,
    UpdateStatusTracker,
    object,
    RecordingTransportCoordinator,
]:
    status = build_update_status_harness(tmp_path / "state.json")
    prepared_transport = object()
    transport_coordinator = RecordingTransportCoordinator(prepared_transport)
    preparation = UpdatePreparationCoordinator(
        status=status,
        commands=MagicMock(),
        transport_coordinator=transport_coordinator,
        validation_config=UpdateValidationConfig(
            rollback_dir=tmp_path / "rollback",
            min_free_disk_bytes=1,
        ),
    )
    return preparation, status, prepared_transport, transport_coordinator


@pytest.mark.asyncio
async def test_prepare_stops_after_validation_failure(tmp_path: Path) -> None:
    preparation, _tracker, _prepared_transport, transport_coordinator = _build_preparation(tmp_path)

    with (
        patch(
            "vibesensor.use_cases.updates.preparation.validate_prerequisites",
            new=AsyncMock(side_effect=UpdatePreparationError("validation failed")),
        ),
        pytest.raises(UpdatePreparationError, match="validation failed"),
    ):
        await preparation.prepare(_wifi_request())

    assert transport_coordinator.requests == []


@pytest.mark.asyncio
async def test_prepare_stops_when_transport_cannot_prepare(tmp_path: Path) -> None:
    preparation, _tracker, _prepared_transport, transport_coordinator = _build_preparation(tmp_path)
    request = _wifi_request()
    transport_coordinator.error = UpdateTransportError("transport failed")

    with (
        patch(
            "vibesensor.use_cases.updates.preparation.validate_prerequisites",
            new=AsyncMock(return_value=None),
        ),
        pytest.raises(UpdateTransportError, match="transport failed"),
    ):
        await preparation.prepare(request)

    assert transport_coordinator.requests == [request]


@pytest.mark.asyncio
async def test_prepare_returns_canonical_prepared_run(tmp_path: Path) -> None:
    preparation, _tracker, prepared_transport, transport_coordinator = _build_preparation(tmp_path)
    request = _wifi_request()

    with patch(
        "vibesensor.use_cases.updates.preparation.validate_prerequisites",
        new=AsyncMock(return_value=None),
    ):
        prepared = await preparation.prepare(request)

    assert isinstance(prepared, PreparedUpdateRun)
    assert transport_coordinator.requests == [request]
    assert prepared.prepared_transport is prepared_transport
