from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibesensor.use_cases.updates.models import (
    UpdateRequest,
    UpdateTransport,
    UpdateValidationConfig,
)
from vibesensor.use_cases.updates.operation import UpdateOperation
from vibesensor.use_cases.updates.status import UpdateStateStore, UpdateStatusTracker
from vibesensor.use_cases.updates.transport_sessions import UpdateTransportSessions


class _Session:
    def __init__(self, transport: UpdateTransport) -> None:
        self.transport = transport
        self.prepare = AsyncMock(return_value=True)
        self.complete_success = AsyncMock(return_value=True)
        self.cleanup_after_update = AsyncMock()
        self.recover_interrupted_update = AsyncMock()


def _build_operation(
    tmp_path: Path,
    *,
    cancel_requested,
    release_workflow: AsyncMock | None = None,
) -> tuple[UpdateOperation, _Session, _Session, AsyncMock]:
    tracker = UpdateStatusTracker(state_store=UpdateStateStore(tmp_path / "state.json"))
    wifi = _Session(UpdateTransport.wifi)
    usb_internet = _Session(UpdateTransport.usb_internet)
    sessions = UpdateTransportSessions(wifi=wifi, usb_internet=usb_internet)
    release = release_workflow or AsyncMock()
    operation = UpdateOperation(
        tracker=tracker,
        commands=MagicMock(),
        transport_sessions=sessions,
        release_workflow=release,
        cancel_requested=cancel_requested,
        validation_config=UpdateValidationConfig(
            rollback_dir=tmp_path / "rollback",
            min_free_disk_bytes=1,
        ),
    )
    return operation, wifi, usb_internet, release


@pytest.mark.asyncio
async def test_execute_uses_transport_session_for_request(tmp_path: Path) -> None:
    operation, wifi, usb_internet, release = _build_operation(
        tmp_path,
        cancel_requested=lambda: False,
    )
    request = UpdateRequest(
        transport=UpdateTransport.usb_internet,
        ssid=None,
        password="",
    )

    with patch(
        "vibesensor.use_cases.updates.operation.validate_prerequisites",
        new=AsyncMock(return_value=True),
    ):
        await operation.execute(request)

    usb_internet.prepare.assert_awaited_once_with(request)
    wifi.prepare.assert_not_awaited()
    release.execute.assert_awaited_once_with(usb_internet)


@pytest.mark.asyncio
async def test_execute_stops_after_validation_failure(tmp_path: Path) -> None:
    operation, wifi, usb_internet, release = _build_operation(
        tmp_path,
        cancel_requested=lambda: False,
    )
    request = UpdateRequest(
        transport=UpdateTransport.wifi,
        ssid="TestNet",
        password="pass123",
    )

    with patch(
        "vibesensor.use_cases.updates.operation.validate_prerequisites",
        new=AsyncMock(return_value=False),
    ):
        await operation.execute(request)

    wifi.prepare.assert_not_awaited()
    usb_internet.prepare.assert_not_awaited()
    release.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_stops_when_transport_prepare_fails(tmp_path: Path) -> None:
    operation, wifi, _usb_internet, release = _build_operation(
        tmp_path,
        cancel_requested=lambda: False,
    )
    wifi.prepare.return_value = False
    request = UpdateRequest(
        transport=UpdateTransport.wifi,
        ssid="TestNet",
        password="pass123",
    )

    with patch(
        "vibesensor.use_cases.updates.operation.validate_prerequisites",
        new=AsyncMock(return_value=True),
    ):
        await operation.execute(request)

    wifi.prepare.assert_awaited_once_with(request)
    release.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_honors_cancellation_after_transport_prepare(tmp_path: Path) -> None:
    cancel_results = iter((False, True))
    operation, wifi, _usb_internet, release = _build_operation(
        tmp_path,
        cancel_requested=lambda: next(cancel_results),
    )
    request = UpdateRequest(
        transport=UpdateTransport.wifi,
        ssid="TestNet",
        password="pass123",
    )

    with patch(
        "vibesensor.use_cases.updates.operation.validate_prerequisites",
        new=AsyncMock(return_value=True),
    ):
        await operation.execute(request)

    wifi.prepare.assert_awaited_once_with(request)
    release.execute.assert_not_awaited()
