from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from test_support.update_status import build_update_status_harness
from use_cases.updates._update_manager_test_helpers import FakeRunner

from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.transport.failures import UpdateTransportStepError
from vibesensor.use_cases.updates.transport.uplink_readiness import UpdateUplinkReadiness
from vibesensor.use_cases.updates.wifi.wifi_config import build_default_wifi_config


def _build_readiness(
    tmp_path: Path,
    *,
    dns_ready_min_wait_s: float = 0.05,
    dns_retry_interval_s: float = 0.01,
) -> tuple[UpdateUplinkReadiness, FakeRunner]:
    runner = FakeRunner()
    status = build_update_status_harness(tmp_path / "state.json")
    config = replace(
        build_default_wifi_config(ap_con_name="VibeSensor-AP", wifi_ifname="wlan0"),
        dns_ready_min_wait_s=dns_ready_min_wait_s,
        dns_retry_interval_s=dns_retry_interval_s,
    )
    commands = UpdateCommandExecutor(runner=runner)
    readiness = UpdateUplinkReadiness(
        commands=commands,
        status=status,
        config=config,
    )
    return readiness, runner


@pytest.mark.asyncio
async def test_wait_for_dns_ready_retries_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    readiness, runner = _build_readiness(tmp_path, dns_ready_min_wait_s=1.0)
    original_run = runner.run
    probe_attempts = {"count": 0}

    async def flaky_probe(args, *, timeout=30, env=None):
        joined = " ".join(args)
        if "socket.getaddrinfo" in joined:
            probe_attempts["count"] += 1
            if probe_attempts["count"] < 3:
                return (1, "", "Temporary failure in name resolution")
        return await original_run(args, timeout=timeout, env=env)

    runner.run = flaky_probe
    sleep = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "vibesensor.use_cases.updates.transport.uplink_readiness.asyncio.sleep",
        sleep,
    )

    await readiness.wait_for_dns_ready()

    assert probe_attempts["count"] == 3
    assert sleep.await_count == 2


@pytest.mark.asyncio
async def test_wait_for_dns_ready_raises_clear_failure(tmp_path: Path) -> None:
    readiness, runner = _build_readiness(tmp_path)
    runner.set_response("socket.getaddrinfo", 1, "", "Temporary failure in name resolution")

    with pytest.raises(UpdateTransportStepError) as exc_info:
        await readiness.wait_for_dns_ready()

    assert str(exc_info.value) == "Connected to Wi-Fi, but internet/DNS is not ready"
    assert "Temporary failure in name resolution" in exc_info.value.detail
