from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from test_support.update_status import build_update_status_harness

from vibesensor.shared.exceptions import UpdateTransportError
from vibesensor.use_cases.updates.models import UpdateRequest, UpdateTransport
from vibesensor.use_cases.updates.transport_coordinator import UpdateTransportCoordinator
from vibesensor.use_cases.updates.transport_sessions import UpdateTransportSessions


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
class _RecordingSetupTransport:
    transport: UpdateTransport = UpdateTransport.wifi
    fail_prepare: bool = False
    calls: list[str] = field(default_factory=list)

    async def prepare(self, request: UpdateRequest) -> None:
        self.calls.append(f"prepare:{request.transport.value}")
        if self.fail_prepare:
            raise UpdateTransportError("setup failed")

    async def abort_preparation(self) -> None:
        self.calls.append("abort")

    async def complete_success(self, message: str) -> None:
        self.calls.append(f"success:{message}")

    async def cleanup_after_update(self) -> None:
        self.calls.append("cleanup")

    async def recover_interrupted_update(self) -> None:
        self.calls.append("recover")


@dataclass(slots=True)
class _RecordingValidatingTransport:
    transport: UpdateTransport = UpdateTransport.usb_internet
    fail_validate: bool = False
    calls: list[str] = field(default_factory=list)

    async def validate(self, request: UpdateRequest) -> None:
        self.calls.append(f"validate:{request.transport.value}")
        if self.fail_validate:
            raise UpdateTransportError("validation failed")

    async def complete_success(self, message: str) -> None:
        self.calls.append(f"success:{message}")


def _coordinator(
    tmp_path: Path,
    *,
    setup: _RecordingSetupTransport | None = None,
    validating: _RecordingValidatingTransport | None = None,
) -> tuple[UpdateTransportCoordinator, object]:
    status = build_update_status_harness(tmp_path / "state.json")
    return UpdateTransportCoordinator(
        sessions=UpdateTransportSessions(
            wifi=setup or _RecordingSetupTransport(),
            usb_internet=validating or _RecordingValidatingTransport(),
        ),
        status=status,
        logger=MagicMock(),
    ), status


@pytest.mark.asyncio
async def test_prepare_rolls_back_only_setup_transport_on_failure(tmp_path: Path) -> None:
    setup = _RecordingSetupTransport(fail_prepare=True)
    coordinator, _status = _coordinator(tmp_path, setup=setup)

    with pytest.raises(UpdateTransportError, match="setup failed"):
        await coordinator.prepare(_request(UpdateTransport.wifi))

    assert setup.calls == ["prepare:wifi", "abort"]


@pytest.mark.asyncio
async def test_prepare_validates_passive_transport_without_abort_path(tmp_path: Path) -> None:
    validating = _RecordingValidatingTransport(fail_validate=True)
    coordinator, _status = _coordinator(tmp_path, validating=validating)

    with pytest.raises(UpdateTransportError, match="validation failed"):
        await coordinator.prepare(_request(UpdateTransport.usb_internet))

    assert validating.calls == ["validate:usb_internet"]


@pytest.mark.asyncio
async def test_cleanup_and_recovery_skip_passive_transport(tmp_path: Path) -> None:
    validating = _RecordingValidatingTransport()
    coordinator, status = _coordinator(tmp_path, validating=validating)

    session = await coordinator.prepare(_request(UpdateTransport.usb_internet))
    await coordinator.cleanup_after_update(session)
    status.start_job(_request(UpdateTransport.usb_internet))
    await coordinator.recover_interrupted(
        status.status,
    )

    assert validating.calls == ["validate:usb_internet"]


@pytest.mark.asyncio
async def test_cleanup_and_recovery_run_for_setup_transport(tmp_path: Path) -> None:
    setup = _RecordingSetupTransport()
    coordinator, status = _coordinator(tmp_path, setup=setup)

    session = await coordinator.prepare(_request(UpdateTransport.wifi))
    await coordinator.cleanup_after_update(session)
    status.start_job(_request(UpdateTransport.wifi))
    await coordinator.recover_interrupted(status.status)

    assert setup.calls == ["prepare:wifi", "cleanup", "recover"]
