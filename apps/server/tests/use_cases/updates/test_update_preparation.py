from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibesensor.use_cases.updates.models import (
    UpdateRequest,
    UpdateTransport,
    UpdateValidationConfig,
)
from vibesensor.use_cases.updates.preparation import (
    PreparedUpdateSession,
    UpdatePreparationCoordinator,
)
from vibesensor.use_cases.updates.status import UpdateStateStore, UpdateStatusTracker


def _wifi_request(ssid: str = "TestNet", password: str = "pass123") -> UpdateRequest:
    return UpdateRequest(
        transport=UpdateTransport.wifi,
        ssid=ssid,
        password=password,
    )


def _build_preparation(
    tmp_path: Path,
    *,
    cancel_requested=lambda: False,
    current_version: str = "2026.4.3",
) -> tuple[UpdatePreparationCoordinator, UpdateStatusTracker, MagicMock]:
    tracker = UpdateStatusTracker(state_store=UpdateStateStore(tmp_path / "state.json"))
    transport_controller = MagicMock()
    transport_controller.prepare = AsyncMock()
    preparation = UpdatePreparationCoordinator(
        tracker=tracker,
        commands=MagicMock(),
        transport_controller=transport_controller,
        validation_config=UpdateValidationConfig(
            rollback_dir=tmp_path / "rollback",
            min_free_disk_bytes=1,
        ),
        current_version_provider=lambda: current_version,
        cancel_requested=cancel_requested,
    )
    return preparation, tracker, transport_controller


@pytest.mark.asyncio
async def test_prepare_stops_after_validation_failure(tmp_path: Path) -> None:
    preparation, _tracker, transport_controller = _build_preparation(tmp_path)

    with patch(
        "vibesensor.use_cases.updates.preparation.validate_prerequisites",
        new=AsyncMock(return_value=False),
    ):
        prepared = await preparation.prepare(_wifi_request())

    assert prepared is None
    transport_controller.prepare.assert_not_awaited()


@pytest.mark.asyncio
async def test_prepare_stops_when_transport_cannot_prepare(tmp_path: Path) -> None:
    preparation, _tracker, transport_controller = _build_preparation(tmp_path)
    request = _wifi_request()
    transport_controller.prepare.return_value = None

    with patch(
        "vibesensor.use_cases.updates.preparation.validate_prerequisites",
        new=AsyncMock(return_value=True),
    ):
        prepared = await preparation.prepare(request)

    assert prepared is None
    transport_controller.prepare.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_prepare_honors_cancellation_after_transport_prepare(tmp_path: Path) -> None:
    cancel_results = iter((False, True))
    preparation, _tracker, transport_controller = _build_preparation(
        tmp_path,
        cancel_requested=lambda: next(cancel_results),
    )
    request = _wifi_request()
    transport_session = object()
    transport_controller.prepare.return_value = transport_session

    with patch(
        "vibesensor.use_cases.updates.preparation.validate_prerequisites",
        new=AsyncMock(return_value=True),
    ):
        prepared = await preparation.prepare(request)

    assert prepared is None
    transport_controller.prepare.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_prepare_returns_canonical_prepared_session(tmp_path: Path) -> None:
    preparation, _tracker, transport_controller = _build_preparation(
        tmp_path,
        current_version="2026.4.9",
    )
    request = _wifi_request()
    transport_session = object()
    transport_controller.prepare.return_value = transport_session

    with patch(
        "vibesensor.use_cases.updates.preparation.validate_prerequisites",
        new=AsyncMock(return_value=True),
    ):
        prepared = await preparation.prepare(request)

    assert isinstance(prepared, PreparedUpdateSession)
    assert prepared.request == request
    assert prepared.current_version == "2026.4.9"
    assert prepared.transport_session is transport_session
