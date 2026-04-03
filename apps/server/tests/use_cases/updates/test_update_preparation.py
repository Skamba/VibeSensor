from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibesensor.shared.exceptions import UpdatePreparationError, UpdateTransportError
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
from vibesensor.use_cases.updates.transport_lifecycle import UpdateTransportLifecycle


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
) -> tuple[UpdatePreparationCoordinator, UpdateStatusTracker, MagicMock]:
    tracker = UpdateStatusTracker(state_store=UpdateStateStore(tmp_path / "state.json"))
    transport_lifecycle = MagicMock(spec=UpdateTransportLifecycle)
    transport_lifecycle.prepare = AsyncMock()
    preparation = UpdatePreparationCoordinator(
        tracker=tracker,
        commands=MagicMock(),
        transport_lifecycle=transport_lifecycle,
        validation_config=UpdateValidationConfig(
            rollback_dir=tmp_path / "rollback",
            min_free_disk_bytes=1,
        ),
        current_version_provider=lambda: current_version,
    )
    return preparation, tracker, transport_lifecycle


@pytest.mark.asyncio
async def test_prepare_stops_after_validation_failure(tmp_path: Path) -> None:
    preparation, _tracker, transport_lifecycle = _build_preparation(tmp_path)

    with (
        patch(
            "vibesensor.use_cases.updates.preparation.validate_prerequisites",
            new=AsyncMock(side_effect=UpdatePreparationError("validation failed")),
        ),
        pytest.raises(UpdatePreparationError, match="validation failed"),
    ):
        await preparation.prepare(_wifi_request())

    transport_lifecycle.prepare.assert_not_awaited()


@pytest.mark.asyncio
async def test_prepare_stops_when_transport_cannot_prepare(tmp_path: Path) -> None:
    preparation, _tracker, transport_lifecycle = _build_preparation(tmp_path)
    request = _wifi_request()
    transport_lifecycle.prepare.side_effect = UpdateTransportError("transport failed")

    with (
        patch(
            "vibesensor.use_cases.updates.preparation.validate_prerequisites",
            new=AsyncMock(return_value=None),
        ),
        pytest.raises(UpdateTransportError, match="transport failed"),
    ):
        await preparation.prepare(request)

    transport_lifecycle.prepare.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_prepare_returns_canonical_prepared_session(tmp_path: Path) -> None:
    preparation, _tracker, transport_lifecycle = _build_preparation(
        tmp_path,
        current_version="2026.4.9",
    )
    request = _wifi_request()
    transport_lifecycle.prepare.return_value = None

    with patch(
        "vibesensor.use_cases.updates.preparation.validate_prerequisites",
        new=AsyncMock(return_value=None),
    ):
        prepared = await preparation.prepare(request)

    assert isinstance(prepared, PreparedUpdateSession)
    assert prepared.current_version == "2026.4.9"
