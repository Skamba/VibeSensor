from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from test_support.update_status import UpdateStatusHarness, build_update_status_harness

from vibesensor.shared.exceptions import UpdatePreparationError, UpdateTransportError
from vibesensor.use_cases.updates.models import (
    UpdateRequest,
    UpdateTransport,
    UpdateValidationConfig,
)
from vibesensor.use_cases.updates.preparation import UpdatePreparationCoordinator
from vibesensor.use_cases.updates.run_models import PreparedUpdateRun
from vibesensor.use_cases.updates.transport_coordinator import UpdateTransportCoordinator
from vibesensor.use_cases.updates.transport_sessions import UpdateTransportSessions


def _wifi_request(ssid: str = "TestNet", password: str = "pass123") -> UpdateRequest:
    return UpdateRequest(
        transport=UpdateTransport.wifi,
        ssid=ssid,
        password=password,
    )


def _build_preparation(
    tmp_path: Path,
    *,
    current_version: str = "2026.4.3",
) -> tuple[UpdatePreparationCoordinator, UpdateStatusHarness, AsyncMock]:
    status = build_update_status_harness(tmp_path / "state.json")
    transport_session = AsyncMock()
    transport_coordinator = UpdateTransportCoordinator(
        sessions=MagicMock(
            spec=UpdateTransportSessions,
            for_request=MagicMock(return_value=transport_session),
        ),
        status=status.tracker,
        logger=MagicMock(),
    )
    preparation = UpdatePreparationCoordinator(
        status=status.tracker,
        commands=MagicMock(),
        transport_coordinator=transport_coordinator,
        validation_config=UpdateValidationConfig(
            rollback_dir=tmp_path / "rollback",
            min_free_disk_bytes=1,
        ),
        current_version_provider=lambda: current_version,
    )
    return preparation, status, transport_session


@pytest.mark.asyncio
async def test_prepare_stops_after_validation_failure(tmp_path: Path) -> None:
    preparation, _tracker, transport_session = _build_preparation(tmp_path)

    with (
        patch(
            "vibesensor.use_cases.updates.preparation.validate_prerequisites",
            new=AsyncMock(side_effect=UpdatePreparationError("validation failed")),
        ),
        pytest.raises(UpdatePreparationError, match="validation failed"),
    ):
        await preparation.prepare(_wifi_request())

    transport_session.prepare.assert_not_awaited()


@pytest.mark.asyncio
async def test_prepare_stops_when_transport_cannot_prepare(tmp_path: Path) -> None:
    preparation, _tracker, transport_session = _build_preparation(tmp_path)
    request = _wifi_request()
    transport_session.prepare.side_effect = UpdateTransportError("transport failed")

    with (
        patch(
            "vibesensor.use_cases.updates.preparation.validate_prerequisites",
            new=AsyncMock(return_value=None),
        ),
        pytest.raises(UpdateTransportError, match="transport failed"),
    ):
        await preparation.prepare(request)

    transport_session.prepare.assert_awaited_once_with(request)
    transport_session.abort_preparation.assert_awaited_once()


@pytest.mark.asyncio
async def test_prepare_returns_canonical_prepared_run(tmp_path: Path) -> None:
    preparation, _tracker, transport_session = _build_preparation(
        tmp_path,
        current_version="2026.4.9",
    )
    request = _wifi_request()
    transport_session.prepare.return_value = None

    with patch(
        "vibesensor.use_cases.updates.preparation.validate_prerequisites",
        new=AsyncMock(return_value=None),
    ):
        prepared = await preparation.prepare(request)

    assert isinstance(prepared, PreparedUpdateRun)
    assert prepared.current_version == "2026.4.9"
    assert prepared.transport_session is transport_session
