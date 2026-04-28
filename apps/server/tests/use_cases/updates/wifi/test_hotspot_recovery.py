from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from test_support.update_status import build_update_status_harness
from use_cases.updates._update_manager_test_helpers import FakeRunner

from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.wifi.wifi_config import (
    HOTSPOT_RESTORE_RETRIES,
    build_default_wifi_config,
)
from vibesensor.use_cases.updates.wifi.wifi_hotspot_recovery import UpdateHotspotRecovery


def _build_recovery(
    tmp_path: Path,
    *,
    delay_s: float = 0.01,
) -> tuple[UpdateHotspotRecovery, FakeRunner, UpdateStatusTracker]:
    runner = FakeRunner()
    status = build_update_status_harness(tmp_path / "state.json")
    config = replace(
        build_default_wifi_config(ap_con_name="VibeSensor-AP", wifi_ifname="wlan0"),
        hotspot_restore_delay_s=delay_s,
    )
    commands = UpdateCommandExecutor(runner=runner)
    recovery = UpdateHotspotRecovery(
        commands=commands,
        status=status,
        config=config,
    )
    return recovery, runner, status


@pytest.mark.asyncio
async def test_stop_hotspot_returns_true_when_nmcli_reports_inactive(tmp_path: Path) -> None:
    recovery, runner, tracker = _build_recovery(tmp_path)
    runner.set_response("connection down VibeSensor-AP", 10, "", "inactive")

    assert await recovery.stop_hotspot() is True
    assert any(
        "Hotspot down returned non-zero; may already be inactive" in line
        for line in tracker.status.log_tail
    )


@pytest.mark.asyncio
async def test_cleanup_uplink_downs_then_deletes_connection(tmp_path: Path) -> None:
    recovery, runner, _tracker = _build_recovery(tmp_path)

    await recovery.cleanup_uplink()

    commands = [" ".join(call[0]) for call in runner.calls]
    assert "connection down VibeSensor-Uplink" in commands[0]
    assert "connection delete VibeSensor-Uplink" in commands[1]


@pytest.mark.asyncio
async def test_restore_hotspot_retries_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    recovery, runner, tracker = _build_recovery(tmp_path)
    original_run = runner.run
    restore_attempts = {"count": 0}

    async def flaky_restore(args, *, timeout=30, env=None):
        joined = " ".join(args)
        if "connection up VibeSensor-AP" in joined:
            restore_attempts["count"] += 1
            if restore_attempts["count"] < 3:
                return (10, "", "failed")
        return await original_run(args, timeout=timeout, env=env)

    runner.run = flaky_restore
    sleep = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "vibesensor.use_cases.updates.wifi.wifi_hotspot_recovery.asyncio.sleep",
        sleep,
    )

    assert await recovery.restore_hotspot() is True
    assert restore_attempts["count"] == 3
    assert sleep.await_count == 2
    assert any("Hotspot restored on attempt 3" in line for line in tracker.status.log_tail)

    commands = [" ".join(call[0]) for call in runner.calls]
    assert "connection down VibeSensor-Uplink" in commands[0]
    assert "connection delete VibeSensor-Uplink" in commands[1]
    assert "connection up VibeSensor-AP" in commands[2]


@pytest.mark.asyncio
async def test_restore_hotspot_exhausts_retries_and_records_issue(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    recovery, runner, tracker = _build_recovery(tmp_path)
    runner.set_response("connection up VibeSensor-AP", 10, "", "failed")
    sleep = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "vibesensor.use_cases.updates.wifi.wifi_hotspot_recovery.asyncio.sleep",
        sleep,
    )

    assert await recovery.restore_hotspot() is False
    assert sleep.await_count == HOTSPOT_RESTORE_RETRIES - 1
    assert any(
        issue.phase == "restoring_hotspot"
        and issue.message == "Failed to restore hotspot after retries"
        for issue in tracker.status.issues
    )


@pytest.mark.asyncio
async def test_restore_hotspot_still_attempts_ap_recovery_after_cleanup_failure(
    tmp_path: Path,
) -> None:
    recovery, runner, tracker = _build_recovery(tmp_path)
    runner.set_response("connection down VibeSensor-Uplink", 10, "", "down failed")

    assert await recovery.restore_hotspot() is True
    assert any(
        "Transient uplink cleanup failed before hotspot restore; attempting AP recovery anyway"
        in line
        for line in tracker.status.log_tail
    )
    assert any("down failed" in line for line in tracker.status.log_tail)

    commands = [" ".join(call[0]) for call in runner.calls]
    assert "connection down VibeSensor-Uplink" in commands[0]
    assert "connection delete VibeSensor-Uplink" in commands[1]
    assert "connection up VibeSensor-AP" in commands[2]
