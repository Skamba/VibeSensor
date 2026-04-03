from __future__ import annotations

from unittest.mock import patch

import pytest
from _update_manager_test_helpers import setup_update_env

from vibesensor.use_cases.updates.models import (
    UpdatePhase,
    UpdateRequest,
    UpdateState,
    UpdateTransport,
)


def _wifi_request(ssid: str = "TestNet", password: str = "pass123") -> UpdateRequest:
    return UpdateRequest(
        transport=UpdateTransport.wifi,
        ssid=ssid,
        password=password,
    )


@pytest.mark.asyncio
async def test_prepare_start_marks_job_running_and_tracks_secret(tmp_path) -> None:
    manager, _runner, _repo = setup_update_env(tmp_path)
    request = _wifi_request()

    manager._lifecycle.prepare_start(request)

    assert manager.status.state == UpdateState.running
    assert manager.status.phase == UpdatePhase.validating
    assert manager.status.ssid == "TestNet"


def test_handle_timeout_marks_failed_and_logs(tmp_path) -> None:
    manager, _runner, _repo = setup_update_env(tmp_path)
    manager._tracker.start_job(_wifi_request("TestNet", ""))

    manager._lifecycle.handle_timeout(12.5)

    assert manager.status.state == UpdateState.failed
    assert any(issue.message == "Update timed out after 12.5s" for issue in manager.status.issues)
    assert "Update timed out after 12.5s" in manager.status.log_tail[-1]


def test_handle_unexpected_marks_failed_and_logs_exception(tmp_path, caplog) -> None:
    manager, _runner, _repo = setup_update_env(tmp_path)
    manager._tracker.start_job(_wifi_request("TestNet", ""))

    with caplog.at_level("ERROR"):
        manager._lifecycle.handle_unexpected(RuntimeError("boom"))

    assert manager.status.state == UpdateState.failed
    assert any(issue.message == "Unexpected error: boom" for issue in manager.status.issues)
    assert any(record.message == "update: unexpected error" for record in caplog.records)


@pytest.mark.asyncio
async def test_cleanup_records_hotspot_restore_failure(tmp_path) -> None:
    manager, runner, _repo = setup_update_env(tmp_path)
    manager.status.state = UpdateState.running
    manager.status.phase = UpdatePhase.installing
    runner.default_response = (1, "", "nmcli failed")

    with (
        patch("vibesensor.use_cases.updates.wifi.wifi_config.HOTSPOT_RESTORE_RETRIES", 1),
        patch("vibesensor.use_cases.updates.wifi.wifi_config.HOTSPOT_RESTORE_DELAY_S", 0),
    ):
        await manager._lifecycle.cleanup_after_update()

    assert any(
        issue.message == "Failed to restore hotspot during cleanup"
        for issue in manager.status.issues
    )


@pytest.mark.asyncio
async def test_cleanup_re_raises_runtime_details_bug_after_finishing_cleanup(tmp_path) -> None:
    manager, _runner, _repo = setup_update_env(tmp_path)
    manager.status.state = UpdateState.running
    manager.status.phase = UpdatePhase.installing

    with patch(
        "vibesensor.use_cases.updates.job_lifecycle.collect_runtime_details",
        side_effect=TypeError("runtime bug"),
    ):
        with pytest.raises(TypeError, match="runtime bug"):
            await manager._lifecycle.cleanup_after_update()

    assert manager.status.finished_at is not None
    assert manager.status.state == UpdateState.failed


@pytest.mark.asyncio
async def test_cleanup_re_raises_wifi_diagnostics_bug_after_finishing_cleanup(tmp_path) -> None:
    manager, _runner, _repo = setup_update_env(tmp_path)
    manager.status.state = UpdateState.running
    manager.status.phase = UpdatePhase.installing

    with patch(
        "vibesensor.use_cases.updates.wifi.wifi_orchestrator.parse_wifi_diagnostics",
        side_effect=TypeError("diagnostics bug"),
    ):
        with pytest.raises(TypeError, match="diagnostics bug"):
            await manager._lifecycle.cleanup_after_update()

    assert manager.status.finished_at is not None
    assert manager.status.state == UpdateState.failed


@pytest.mark.asyncio
async def test_cleanup_skips_wifi_cleanup_for_usb_transport(tmp_path) -> None:
    manager, _runner, _repo = setup_update_env(tmp_path)
    manager.status.transport = UpdateTransport.usb_internet
    manager.status.state = UpdateState.running
    manager.status.phase = UpdatePhase.installing

    with patch(
        "vibesensor.use_cases.updates.wifi.wifi_orchestrator.parse_wifi_diagnostics",
        side_effect=AssertionError("Wi-Fi diagnostics should not run for USB transport"),
    ):
        await manager._lifecycle.cleanup_after_update()

    assert manager.status.finished_at is not None


def test_handle_cancelled_cleanup_error_logs_warning(tmp_path, caplog) -> None:
    manager, _runner, _repo = setup_update_env(tmp_path)

    with caplog.at_level("WARNING"):
        try:
            raise RuntimeError("cleanup bug")
        except RuntimeError as exc:
            manager._lifecycle.handle_cancelled_cleanup_error(exc)

    assert any(
        record.message == "Update cleanup interrupted during cancellation"
        for record in caplog.records
    )
