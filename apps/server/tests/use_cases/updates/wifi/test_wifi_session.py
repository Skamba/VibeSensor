from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from test_support.update_status import build_update_status_harness
from use_cases.updates._update_manager_test_helpers import FakeRunner

from vibesensor.shared.exceptions import UpdateTransportError
from vibesensor.use_cases.updates.models import (
    UpdateIssue,
    UpdatePhase,
    UpdateRequest,
    UpdateState,
    UpdateTransport,
)
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.wifi import UpdateWifiSession, build_default_wifi_config


def _build_session(
    tmp_path: Path,
    *,
    restore_retries: int = 3,
    restore_delay_s: float = 0.01,
) -> tuple[UpdateWifiSession, FakeRunner, UpdateStatusTracker]:
    runner = FakeRunner()
    status = build_update_status_harness(tmp_path / "state.json")
    config = replace(
        build_default_wifi_config(ap_con_name="VibeSensor-AP", wifi_ifname="wlan0"),
        hotspot_restore_retries=restore_retries,
        hotspot_restore_delay_s=restore_delay_s,
    )
    commands = UpdateCommandExecutor(runner=runner)
    session = UpdateWifiSession(
        commands=commands,
        status=status,
        config=config,
    )
    return session, runner, status


def _wifi_request(ssid: str = "TestNet", password: str = "") -> UpdateRequest:
    return UpdateRequest(
        transport=UpdateTransport.wifi,
        ssid=ssid,
        password=password,
    )


def _seed_checked_phase(tracker: UpdateStatusTracker) -> None:
    tracker.start_job(_wifi_request())
    tracker.transition(UpdatePhase.stopping_hotspot)
    tracker.transition(UpdatePhase.connecting_wifi)
    tracker.transition(UpdatePhase.checking)


def _seed_installing_phase(tracker: UpdateStatusTracker) -> None:
    _seed_checked_phase(tracker)
    tracker.transition(UpdatePhase.downloading)
    tracker.transition(UpdatePhase.installing)


@pytest.mark.asyncio
async def test_recover_interrupted_update_restores_hotspot_successfully(
    tmp_path: Path,
) -> None:
    session, _runner, tracker = _build_session(tmp_path)

    await session.recover_interrupted_update(tracker.status)

    assert any("startup_recover: restoring hotspot" in line for line in tracker.status.log_tail)
    assert any(
        "startup_recover: hotspot restored successfully" in line for line in tracker.status.log_tail
    )


@pytest.mark.asyncio
async def test_prepare_stops_hotspot_and_connects_uplink(tmp_path: Path) -> None:
    session, _runner, tracker = _build_session(tmp_path)
    tracker.start_job(_wifi_request(password="pass123"))

    prepared_transport = await session.prepare(_wifi_request(password="pass123"))

    assert tracker.status.phase == UpdatePhase.connecting_wifi
    assert prepared_transport is session
    assert any("Stopping hotspot..." in line for line in tracker.status.log_tail)
    assert any("Wi-Fi connected successfully" in line for line in tracker.status.log_tail)


@pytest.mark.asyncio
async def test_recover_interrupted_update_records_restore_failure(tmp_path: Path) -> None:
    session, runner, tracker = _build_session(
        tmp_path,
        restore_retries=1,
        restore_delay_s=0,
    )
    runner.set_response("connection up VibeSensor-AP", 10, "", "failed")

    await session.recover_interrupted_update(tracker.status)

    assert any(
        issue.message == "Failed to restore hotspot after interrupted update"
        for issue in tracker.status.issues
    )
    assert any(
        "startup_recover: hotspot restore failed" in line for line in tracker.status.log_tail
    )


@pytest.mark.asyncio
async def test_cleanup_restore_hotspot_records_issue_on_failure(tmp_path: Path) -> None:
    session, runner, tracker = _build_session(
        tmp_path,
        restore_retries=1,
        restore_delay_s=0,
    )
    _seed_installing_phase(tracker)
    runner.set_response("connection up VibeSensor-AP", 10, "", "failed")

    await session.cleanup_after_update()

    assert any(
        issue.phase == "cleanup" and issue.message == "Failed to restore hotspot during cleanup"
        for issue in tracker.status.issues
    )
    assert any("Cleanup hotspot restore failed" in line for line in tracker.status.log_tail)


@pytest.mark.asyncio
async def test_cleanup_after_update_collects_cleanup_diagnostics(tmp_path: Path) -> None:
    session, _runner, _tracker = _build_session(tmp_path)
    expected_issues = [
        UpdateIssue(
            phase="diagnostics",
            message="Hotspot summary reports failure",
            detail="status=failed",
        ),
    ]

    with patch(
        "vibesensor.use_cases.updates.wifi.wifi_session.parse_wifi_diagnostics",
        return_value=expected_issues,
    ):
        await session.cleanup_after_update()

    assert _tracker.status.issues == expected_issues


@pytest.mark.asyncio
async def test_complete_success_restores_hotspot_without_marking_terminal_state(
    tmp_path: Path,
) -> None:
    session, _runner, tracker = _build_session(tmp_path)
    _seed_checked_phase(tracker)

    await session.complete_success()

    assert tracker.status.state == UpdateState.running
    assert tracker.status.phase == UpdatePhase.restoring_hotspot
    assert any("Restoring hotspot..." in line for line in tracker.status.log_tail)


@pytest.mark.asyncio
async def test_complete_success_raises_when_restore_fails(tmp_path: Path) -> None:
    session, runner, tracker = _build_session(
        tmp_path,
        restore_retries=1,
        restore_delay_s=0,
    )
    _seed_checked_phase(tracker)
    runner.set_response("connection up VibeSensor-AP", 10, "", "failed")

    with pytest.raises(UpdateTransportError, match="Failed to restore hotspot after update"):
        await session.complete_success()

    assert tracker.status.state == UpdateState.running
    assert tracker.status.phase == UpdatePhase.restoring_hotspot
    assert any(
        issue.phase == UpdatePhase.restoring_hotspot.value
        and issue.message == "Failed to restore hotspot after retries"
        for issue in tracker.status.issues
    )


@pytest.mark.asyncio
async def test_cleanup_restore_orchestration_restores_hotspot_when_needed(tmp_path: Path) -> None:
    session, _runner, tracker = _build_session(tmp_path)
    _seed_installing_phase(tracker)

    await session.cleanup_after_update()

    assert tracker.status.phase == UpdatePhase.restoring_hotspot
    assert any("Restoring hotspot..." in line for line in tracker.status.log_tail)


@pytest.mark.asyncio
async def test_cleanup_restore_orchestration_skips_restore_when_no_longer_needed(
    tmp_path: Path,
) -> None:
    session, _runner, tracker = _build_session(tmp_path)
    _seed_checked_phase(tracker)
    tracker.mark_success("done")

    await session.cleanup_after_update()

    assert tracker.status.state == UpdateState.success
    assert tracker.status.phase == UpdatePhase.done
    assert not any("Restoring hotspot..." in line for line in tracker.status.log_tail)


@pytest.mark.asyncio
async def test_cleanup_restore_preserves_failure_phase(tmp_path: Path) -> None:
    session, _runner, tracker = _build_session(tmp_path)
    _seed_installing_phase(tracker)
    tracker.fail(UpdatePhase.installing, "install failed")

    await session.cleanup_after_update()

    assert tracker.status.state == UpdateState.failed
    assert tracker.status.phase == UpdatePhase.installing
    assert any("Restoring hotspot..." in line for line in tracker.status.log_tail)
