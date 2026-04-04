from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from test_support.update_status import build_update_status_harness

from vibesensor.shared.exceptions import UpdateTransportError
from vibesensor.use_cases.updates.models import UpdateRequest, UpdateTransport
from vibesensor.use_cases.updates.transport_coordinator import UpdateTransportCoordinator
from vibesensor.use_cases.updates.transport_lifecycles import UpdateTransportLifecycles


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
    calls: list[str] = field(default_factory=list)

    async def prepare(self, request: UpdateRequest) -> _RecordingTransportLifecycle:
        self.calls.append(f"prepare:{request.transport.value}")
        if self.fail_prepare:
            raise UpdateTransportError(f"{request.transport.value} prepare failed")
        return self

    async def abort_preparation(self) -> None:
        self.calls.append("abort")

    async def complete_success(self, message: str) -> None:
        self.calls.append(f"success:{message}")

    async def cleanup_after_update(self) -> None:
        self.calls.append("cleanup")

    async def recover_interrupted_update(self, status: object) -> None:
        state = getattr(status, "state", None)
        self.calls.append(f"recover:{getattr(state, 'value', state)}")


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
        status=status,
        logger=MagicMock(),
    ), status


@pytest.mark.asyncio
async def test_prepare_rolls_back_wifi_transport_on_failure(tmp_path: Path) -> None:
    wifi = _RecordingTransportLifecycle(
        transport=UpdateTransport.wifi,
        fail_prepare=True,
    )
    coordinator, _status = _coordinator(tmp_path, wifi=wifi)

    with pytest.raises(UpdateTransportError, match="wifi prepare failed"):
        await coordinator.prepare(_request(UpdateTransport.wifi))

    assert wifi.calls == ["prepare:wifi", "abort"]


@pytest.mark.asyncio
async def test_prepare_uses_abort_hook_for_usb_transport_failures(tmp_path: Path) -> None:
    usb_internet = _RecordingTransportLifecycle(
        transport=UpdateTransport.usb_internet,
        fail_prepare=True,
    )
    coordinator, _status = _coordinator(tmp_path, usb_internet=usb_internet)

    with pytest.raises(UpdateTransportError, match="usb_internet prepare failed"):
        await coordinator.prepare(_request(UpdateTransport.usb_internet))

    assert usb_internet.calls == ["prepare:usb_internet", "abort"]


@pytest.mark.asyncio
async def test_cleanup_and_recovery_use_explicit_usb_transport_hooks(tmp_path: Path) -> None:
    usb_internet = _RecordingTransportLifecycle(transport=UpdateTransport.usb_internet)
    coordinator, status = _coordinator(tmp_path, usb_internet=usb_internet)

    prepared_transport = await coordinator.prepare(_request(UpdateTransport.usb_internet))
    await coordinator.cleanup_after_update(prepared_transport)
    status.start_job(_request(UpdateTransport.usb_internet))
    await coordinator.recover_interrupted(status.status)

    assert usb_internet.calls == ["prepare:usb_internet", "cleanup", "recover:running"]


@pytest.mark.asyncio
async def test_cleanup_and_recovery_use_explicit_wifi_transport_hooks(tmp_path: Path) -> None:
    wifi = _RecordingTransportLifecycle(transport=UpdateTransport.wifi)
    coordinator, status = _coordinator(tmp_path, wifi=wifi)

    prepared_transport = await coordinator.prepare(_request(UpdateTransport.wifi))
    await coordinator.cleanup_after_update(prepared_transport)
    status.start_job(_request(UpdateTransport.wifi))
    await coordinator.recover_interrupted(status.status)

    assert wifi.calls == ["prepare:wifi", "cleanup", "recover:running"]
