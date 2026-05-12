from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from test_support.update_status import build_update_status_harness

from vibesensor.shared.exceptions import UpdateTransportError
from vibesensor.use_cases.updates.models import UpdateRequest, UpdateState, UpdateTransport
from vibesensor.use_cases.updates.transport.coordinator import UpdateTransportCoordinator
from vibesensor.use_cases.updates.transport.lifecycles import UpdateTransportLifecycles


def _request(transport: UpdateTransport) -> UpdateRequest:
    if transport is UpdateTransport.wifi:
        return UpdateRequest(
            transport=transport,
            ssid="TestNet",
            password="pass123",
        )
    return UpdateRequest(
        transport=transport,
        ssid=None,
        password="",
    )


@dataclass(slots=True)
class _RecordingTransportLifecycle:
    transport: UpdateTransport
    fail_prepare: bool = False
    prepared_requests: list[UpdateTransport] = field(default_factory=list)
    aborted: bool = False
    cleanup_count: int = 0
    recovered_state: UpdateState | None = None

    async def prepare(self, request: UpdateRequest) -> _RecordingTransportLifecycle:
        self.prepared_requests.append(request.transport)
        if self.fail_prepare:
            raise UpdateTransportError(f"{request.transport.value} prepare failed")
        return self

    async def abort_preparation(self) -> None:
        self.aborted = True

    async def complete_success(self) -> None:
        return None

    async def cleanup_after_update(self) -> None:
        self.cleanup_count += 1

    async def recover_interrupted_update(self, status: object) -> None:
        self.recovered_state = getattr(status, "state", None)


def _coordinator(
    tmp_path: Path,
    *,
    wifi: _RecordingTransportLifecycle | None = None,
    usb_internet: _RecordingTransportLifecycle | None = None,
) -> tuple[UpdateTransportCoordinator, object]:
    status = build_update_status_harness(tmp_path / "state.json")
    return UpdateTransportCoordinator(
        lifecycles=UpdateTransportLifecycles(
            wifi=wifi or _RecordingTransportLifecycle(transport=UpdateTransport.wifi),
            usb_internet=usb_internet
            or _RecordingTransportLifecycle(transport=UpdateTransport.usb_internet),
        ),
        logger=MagicMock(),
    ), status


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", [UpdateTransport.wifi, UpdateTransport.usb_internet])
async def test_prepare_aborts_selected_transport_on_failure(
    tmp_path: Path,
    transport: UpdateTransport,
) -> None:
    wifi = _RecordingTransportLifecycle(
        transport=UpdateTransport.wifi,
        fail_prepare=transport is UpdateTransport.wifi,
    )
    usb_internet = _RecordingTransportLifecycle(
        transport=UpdateTransport.usb_internet,
        fail_prepare=transport is UpdateTransport.usb_internet,
    )
    coordinator, _status = _coordinator(tmp_path, wifi=wifi, usb_internet=usb_internet)
    selected = wifi if transport is UpdateTransport.wifi else usb_internet
    unselected = usb_internet if transport is UpdateTransport.wifi else wifi

    with pytest.raises(UpdateTransportError, match=f"{transport.value} prepare failed"):
        await coordinator.prepare(_request(transport))

    assert selected.prepared_requests == [transport]
    assert selected.aborted is True
    assert unselected.prepared_requests == []
    assert unselected.aborted is False


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", [UpdateTransport.wifi, UpdateTransport.usb_internet])
async def test_cleanup_and_recovery_use_selected_transport_lifecycle(
    tmp_path: Path,
    transport: UpdateTransport,
) -> None:
    wifi = _RecordingTransportLifecycle(transport=UpdateTransport.wifi)
    usb_internet = _RecordingTransportLifecycle(transport=UpdateTransport.usb_internet)
    coordinator, status = _coordinator(tmp_path, wifi=wifi, usb_internet=usb_internet)
    selected = wifi if transport is UpdateTransport.wifi else usb_internet
    unselected = usb_internet if transport is UpdateTransport.wifi else wifi

    prepared_transport = await coordinator.prepare(_request(transport))
    await coordinator.cleanup_after_update(prepared_transport)
    status.start_job(_request(transport))
    await coordinator.recover_interrupted(status.status)

    assert prepared_transport is selected
    assert selected.cleanup_count == 1
    assert selected.recovered_state is UpdateState.running
    assert unselected.cleanup_count == 0
    assert unselected.recovered_state is None
