from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from test_support.update_status import build_update_status_harness
from use_cases.updates._update_manager_test_helpers import FakeRunner

from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.transport.failures import UpdateTransportStepError
from vibesensor.use_cases.updates.wifi.wifi_config import build_default_wifi_config
from vibesensor.use_cases.updates.wifi.wifi_uplink_setup import (
    UpdateUplinkProvisioner,
    ssid_security_modes,
)


def _build_uplink_provisioner(tmp_path: Path) -> tuple[UpdateUplinkProvisioner, FakeRunner]:
    runner = FakeRunner()
    commands = UpdateCommandExecutor(runner=runner)
    provisioner = UpdateUplinkProvisioner(
        commands=commands,
        status=build_update_status_harness(tmp_path / "state.json"),
        config=build_default_wifi_config(ap_con_name="VibeSensor-AP", wifi_ifname="wlan0"),
    )
    return provisioner, runner


def test_ssid_security_modes_handles_escaped_ssids() -> None:
    scan_output = "Cafe\\:Guest:WPA2 WPA3\nOpenNet:--\n"

    assert ssid_security_modes(scan_output, "Cafe:Guest") == {"WPA2 WPA3"}
    assert ssid_security_modes(scan_output, "OpenNet") == set()


@pytest.mark.asyncio
async def test_prepare_uplink_connection_requires_password_for_secured_network(
    tmp_path: Path,
) -> None:
    provisioner, runner = _build_uplink_provisioner(tmp_path)
    runner.set_response("dev wifi list", 0, "Pim:WPA2 WPA3\n")

    with pytest.raises(
        UpdateTransportStepError,
        match="Wi-Fi password required for secured network",
    ):
        await provisioner.prepare_uplink_connection("Pim", "")


@pytest.mark.asyncio
async def test_prepare_uplink_connection_applies_password(tmp_path: Path) -> None:
    provisioner, runner = _build_uplink_provisioner(tmp_path)

    await provisioner.prepare_uplink_connection("Pim", "tomaat123")
    assert any(
        "connection modify VibeSensor-Uplink wifi-sec.key-mgmt wpa-psk wifi-sec.psk tomaat123"
        in " ".join(call[0])
        for call in runner.calls
    )


@pytest.mark.asyncio
async def test_bring_uplink_up_retries_ssid_not_found_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    provisioner, runner = _build_uplink_provisioner(tmp_path)
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
    monkeypatch.setattr("vibesensor.use_cases.updates.wifi.wifi_uplink_setup.asyncio.sleep", sleep)

    await provisioner.bring_uplink_up("TestNet")

    assert connect_calls["count"] == 2
    assert sleep.await_count == 1
    assert any("dev wifi list ifname wlan0" in " ".join(call[0]) for call in runner.calls)


@pytest.mark.asyncio
async def test_bring_uplink_up_fails_immediately_for_non_retryable_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    provisioner, runner = _build_uplink_provisioner(tmp_path)
    runner.set_response(
        "connection up VibeSensor-Uplink",
        10,
        "",
        "Error: Connection activation failed",
    )
    sleep = AsyncMock(return_value=None)
    monkeypatch.setattr("vibesensor.use_cases.updates.wifi.wifi_uplink_setup.asyncio.sleep", sleep)

    with pytest.raises(
        UpdateTransportStepError,
        match="Failed to connect to Wi-Fi 'TestNet'",
    ) as exc_info:
        await provisioner.bring_uplink_up("TestNet")

    assert exc_info.value.detail == "Error: Connection activation failed"
    assert sleep.await_count == 0
    assert not any("dev wifi list ifname wlan0" in " ".join(call[0]) for call in runner.calls)


@pytest.mark.asyncio
async def test_bring_uplink_up_exhausts_retryable_ssid_not_found_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    provisioner, runner = _build_uplink_provisioner(tmp_path)
    runner.set_response(
        "connection up VibeSensor-Uplink",
        10,
        "",
        "Error: No network with SSID 'TestNet' found.\n",
    )
    sleep = AsyncMock(return_value=None)
    monkeypatch.setattr("vibesensor.use_cases.updates.wifi.wifi_uplink_setup.asyncio.sleep", sleep)

    with pytest.raises(
        UpdateTransportStepError,
        match="Failed to connect to Wi-Fi 'TestNet'",
    ) as exc_info:
        await provisioner.bring_uplink_up("TestNet")

    assert exc_info.value.detail == "Error: No network with SSID 'TestNet' found.\n"
    assert sleep.await_count == 2
    assert sum("connection up VibeSensor-Uplink" in " ".join(call[0]) for call in runner.calls) == 3
    assert sum("dev wifi list ifname wlan0" in " ".join(call[0]) for call in runner.calls) == 2
