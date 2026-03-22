from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from _update_manager_test_helpers import FakeRunner

from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStateStore, UpdateStatusTracker
from vibesensor.use_cases.updates.wifi_config import build_default_wifi_config
from vibesensor.use_cases.updates.wifi_readiness import UpdateWifiReadiness


def _build_readiness(
    tmp_path: Path,
    *,
    dns_ready_min_wait_s: float = 0.05,
    dns_retry_interval_s: float = 0.01,
) -> tuple[UpdateWifiReadiness, FakeRunner, UpdateStatusTracker]:
    runner = FakeRunner()
    tracker = UpdateStatusTracker(state_store=UpdateStateStore(tmp_path / "state.json"))
    config = replace(
        build_default_wifi_config(ap_con_name="VibeSensor-AP", wifi_ifname="wlan0"),
        dns_ready_min_wait_s=dns_ready_min_wait_s,
        dns_retry_interval_s=dns_retry_interval_s,
    )
    commands = UpdateCommandExecutor(runner=runner, tracker=tracker)
    readiness = UpdateWifiReadiness(commands=commands, tracker=tracker, config=config)
    return readiness, runner, tracker


@pytest.mark.asyncio
async def test_bring_uplink_up_retries_ssid_not_found_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    readiness, runner, tracker = _build_readiness(tmp_path)
    original_run = runner.run
    connect_calls = {"count": 0}

    async def run_with_retry(args, *, timeout=30, env=None):
        joined = " ".join(args)
        if "connection up VibeSensor-Uplink" in joined:
            connect_calls["count"] += 1
            if connect_calls["count"] == 1:
                return (10, "", "Error: No network with SSID 'TestNet' found.\n")
        return await original_run(args, timeout=timeout, env=env)

    runner.run = run_with_retry
    sleep = AsyncMock(return_value=None)
    monkeypatch.setattr("vibesensor.use_cases.updates.wifi_readiness.asyncio.sleep", sleep)

    assert await readiness.bring_uplink_up("TestNet")
    assert connect_calls["count"] == 2
    assert sleep.await_count == 1
    assert not tracker.status.issues
    assert any("dev wifi list ifname wlan0" in " ".join(call[0]) for call in runner.calls)


@pytest.mark.asyncio
async def test_wait_for_dns_ready_reports_clear_failure(tmp_path: Path) -> None:
    readiness, runner, tracker = _build_readiness(tmp_path)
    runner.set_response("socket.getaddrinfo", 1, "", "Temporary failure in name resolution")

    assert not await readiness.wait_for_dns_ready()
    assert any(
        issue.message == "Connected to Wi-Fi, but internet/DNS is not ready"
        and "Temporary failure in name resolution" in (issue.detail or "")
        for issue in tracker.status.issues
    )
