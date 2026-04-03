from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibesensor.use_cases.updates.coordinator import UpdateCoordinator
from vibesensor.use_cases.updates.models import (
    UpdatePhase,
    UpdateRequest,
    UpdateTransport,
    UpdateValidationConfig,
)
from vibesensor.use_cases.updates.status import UpdateStateStore, UpdateStatusTracker
from vibesensor.use_cases.updates.transport_sessions import UpdateTransportSessions


class _Session:
    def __init__(self, transport: UpdateTransport) -> None:
        self.transport = transport
        self.prepare = AsyncMock(return_value=True)
        self.complete_success = AsyncMock(return_value=True)
        self.cleanup_after_update = AsyncMock()
        self.recover_interrupted_update = AsyncMock()


def _build_coordinator(
    tmp_path: Path,
    *,
    cancel_requested=lambda: False,
) -> tuple[
    UpdateCoordinator,
    UpdateStatusTracker,
    _Session,
    _Session,
    MagicMock,
    MagicMock,
    MagicMock,
    MagicMock,
    MagicMock,
]:
    tracker = UpdateStatusTracker(state_store=UpdateStateStore(tmp_path / "state.json"))
    wifi = _Session(UpdateTransport.wifi)
    usb_internet = _Session(UpdateTransport.usb_internet)
    wifi.prepare.side_effect = lambda _request: _wifi_prepare(tracker)
    usb_internet.prepare.side_effect = lambda _request: _transition_and_continue(
        tracker,
        UpdatePhase.connecting_usb_internet,
    )
    sessions = UpdateTransportSessions(wifi=wifi, usb_internet=usb_internet)
    resolver = MagicMock()
    resolver.resolve = AsyncMock()
    stager = MagicMock()
    deployer = MagicMock()
    deployer.deploy = AsyncMock(return_value=True)
    firmware_refresher = MagicMock()
    firmware_refresher.refresh_esp_firmware = AsyncMock()
    restart_scheduler = MagicMock()
    restart_scheduler.schedule = AsyncMock(return_value=True)
    coordinator = UpdateCoordinator(
        tracker=tracker,
        commands=MagicMock(),
        transport_sessions=sessions,
        resolver=resolver,
        stager=stager,
        deployer=deployer,
        firmware_refresher=firmware_refresher,
        restart_scheduler=restart_scheduler,
        cancel_requested=cancel_requested,
        validation_config=UpdateValidationConfig(
            rollback_dir=tmp_path / "rollback",
            min_free_disk_bytes=1,
        ),
    )
    return (
        coordinator,
        tracker,
        wifi,
        usb_internet,
        resolver,
        stager,
        deployer,
        firmware_refresher,
        restart_scheduler,
    )


def _wifi_request(ssid: str = "TestNet", password: str = "pass123") -> UpdateRequest:
    return UpdateRequest(
        transport=UpdateTransport.wifi,
        ssid=ssid,
        password=password,
    )


def _start_job(tracker: UpdateStatusTracker, request: UpdateRequest) -> None:
    tracker.start_job(request)


def _transition_and_continue(tracker: UpdateStatusTracker, phase: UpdatePhase) -> bool:
    tracker.transition(phase)
    return True


def _wifi_prepare(tracker: UpdateStatusTracker) -> bool:
    tracker.transition(UpdatePhase.stopping_hotspot)
    tracker.transition(UpdatePhase.connecting_wifi)
    return True


@pytest.mark.asyncio
async def test_execute_stops_after_validation_failure(tmp_path: Path) -> None:
    coordinator, tracker, wifi, usb_internet, resolver, _stager, deployer, *_ = _build_coordinator(
        tmp_path,
    )
    request = _wifi_request()
    _start_job(tracker, request)

    with patch(
        "vibesensor.use_cases.updates.coordinator.validate_prerequisites",
        new=AsyncMock(return_value=False),
    ):
        await coordinator.execute(request)

    wifi.prepare.assert_not_awaited()
    usb_internet.prepare.assert_not_awaited()
    resolver.resolve.assert_not_awaited()
    deployer.deploy.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_uses_transport_session_and_honors_post_prepare_cancellation(
    tmp_path: Path,
) -> None:
    cancel_results = iter((False, True))
    (
        coordinator,
        _tracker,
        wifi,
        usb_internet,
        resolver,
        _stager,
        deployer,
        *_,
    ) = _build_coordinator(
        tmp_path,
        cancel_requested=lambda: next(cancel_results),
    )
    request = UpdateRequest(
        transport=UpdateTransport.usb_internet,
        ssid=None,
        password="",
    )
    _start_job(_tracker, request)

    with patch(
        "vibesensor.use_cases.updates.coordinator.validate_prerequisites",
        new=AsyncMock(return_value=True),
    ):
        await coordinator.execute(request)

    usb_internet.prepare.assert_awaited_once_with(request)
    wifi.prepare.assert_not_awaited()
    resolver.resolve.assert_not_awaited()
    deployer.deploy.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_marks_success_through_transport_when_already_up_to_date(
    tmp_path: Path,
) -> None:
    (
        coordinator,
        _tracker,
        _wifi,
        usb_internet,
        resolver,
        _stager,
        deployer,
        firmware_refresher,
        restart_scheduler,
    ) = _build_coordinator(tmp_path)
    request = UpdateRequest(
        transport=UpdateTransport.usb_internet,
        ssid=None,
        password="",
    )
    _start_job(_tracker, request)
    resolver.resolve.return_value = SimpleNamespace(
        failed=False,
        release=None,
        latest_tag="server-v2026.4.3",
    )

    with (
        patch(
            "vibesensor.use_cases.updates.coordinator.validate_prerequisites",
            new=AsyncMock(return_value=True),
        ),
        patch("vibesensor.__version__", "2026.4.3"),
    ):
        await coordinator.execute(request)

    firmware_refresher.refresh_esp_firmware.assert_awaited_once_with(
        pinned_tag="server-v2026.4.3",
    )
    usb_internet.complete_success.assert_awaited_once_with(
        "No server update needed; ESP firmware checked",
    )
    deployer.deploy.assert_not_awaited()
    restart_scheduler.schedule.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_downloads_and_installs_before_transport_success(tmp_path: Path) -> None:
    (
        coordinator,
        _tracker,
        wifi,
        _usb_internet,
        resolver,
        stager,
        deployer,
        _firmware_refresher,
        restart_scheduler,
    ) = _build_coordinator(tmp_path)
    request = _wifi_request()
    _start_job(_tracker, request)
    release = SimpleNamespace(tag="server-v2026.4.4", version="2026.4.4", sha256="")
    staged_release = SimpleNamespace(release=release, wheel_path=tmp_path / "release.whl")
    resolver.resolve.return_value = SimpleNamespace(
        failed=False,
        release=release,
        latest_tag="server-v2026.4.4",
    )

    @asynccontextmanager
    async def stage(_release: object):
        yield staged_release

    stager.stage.side_effect = stage

    with (
        patch(
            "vibesensor.use_cases.updates.coordinator.validate_prerequisites",
            new=AsyncMock(return_value=True),
        ),
        patch("vibesensor.__version__", "2026.4.3"),
    ):
        await coordinator.execute(request)

    wifi.prepare.assert_awaited_once()
    deployer.deploy.assert_awaited_once_with(staged_release)
    wifi.complete_success.assert_awaited_once_with("Update completed successfully")
    restart_scheduler.schedule.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_execute_skips_restart_when_transport_finalize_fails(tmp_path: Path) -> None:
    (
        coordinator,
        tracker,
        wifi,
        _usb_internet,
        resolver,
        stager,
        deployer,
        _firmware_refresher,
        restart_scheduler,
    ) = _build_coordinator(tmp_path)
    request = _wifi_request()
    _start_job(tracker, request)
    release = SimpleNamespace(tag="server-v2026.4.4", version="2026.4.4", sha256="")
    staged_release = SimpleNamespace(release=release, wheel_path=tmp_path / "release.whl")
    resolver.resolve.return_value = SimpleNamespace(
        failed=False,
        release=release,
        latest_tag="server-v2026.4.4",
    )
    wifi.complete_success.return_value = False

    @asynccontextmanager
    async def stage(_release: object):
        yield staged_release

    stager.stage.side_effect = stage

    with (
        patch(
            "vibesensor.use_cases.updates.coordinator.validate_prerequisites",
            new=AsyncMock(return_value=True),
        ),
        patch("vibesensor.__version__", "2026.4.3"),
    ):
        await coordinator.execute(request)

    deployer.deploy.assert_awaited_once_with(staged_release)
    wifi.complete_success.assert_awaited_once_with("Update completed successfully")
    restart_scheduler.schedule.assert_not_awaited()
    assert tracker.status.issues == []
