from __future__ import annotations

from pathlib import Path

import pytest
from test_support.update_status import UpdateStatusHarness, build_update_status_harness
from use_cases.updates._update_manager_test_helpers import FakeRunner

from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.wifi.wifi_config import build_default_wifi_config
from vibesensor.use_cases.updates.wifi.wifi_uplink_setup import (
    UpdateUplinkProvisioner,
    ssid_security_modes,
)


def _build_uplink_provisioner(
    tmp_path: Path,
) -> tuple[UpdateUplinkProvisioner, FakeRunner, UpdateStatusHarness]:
    runner = FakeRunner()
    status = build_update_status_harness(tmp_path / "state.json")
    commands = UpdateCommandExecutor(runner=runner, recorder=status.recorder)
    provisioner = UpdateUplinkProvisioner(
        commands=commands,
        status_controller=status.controller,
        status_recorder=status.recorder,
        config=build_default_wifi_config(ap_con_name="VibeSensor-AP", wifi_ifname="wlan0"),
    )
    return provisioner, runner, status.tracker


def test_ssid_security_modes_handles_escaped_ssids() -> None:
    scan_output = "Cafe\\:Guest:WPA2 WPA3\nOpenNet:--\n"

    assert ssid_security_modes(scan_output, "Cafe:Guest") == {"WPA2 WPA3"}
    assert ssid_security_modes(scan_output, "OpenNet") == set()


@pytest.mark.asyncio
async def test_prepare_uplink_connection_requires_password_for_secured_network(
    tmp_path: Path,
) -> None:
    provisioner, runner, tracker = _build_uplink_provisioner(tmp_path)
    runner.set_response("dev wifi list", 0, "Pim:WPA2 WPA3\n")

    assert not await provisioner.prepare_uplink_connection("Pim", "")
    assert any(
        issue.message == "Wi-Fi password required for secured network"
        for issue in tracker.status.issues
    )


@pytest.mark.asyncio
async def test_prepare_uplink_connection_applies_password(tmp_path: Path) -> None:
    provisioner, runner, tracker = _build_uplink_provisioner(tmp_path)

    assert await provisioner.prepare_uplink_connection("Pim", "tomaat123")
    assert not tracker.status.issues
    assert any(
        "connection modify VibeSensor-Uplink wifi-sec.key-mgmt wpa-psk wifi-sec.psk tomaat123"
        in " ".join(call[0])
        for call in runner.calls
    )
