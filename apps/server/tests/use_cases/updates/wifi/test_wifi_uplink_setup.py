from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from test_support.update_status import build_update_status_harness
from use_cases.updates._update_manager_test_helpers import FakeRunner

from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.transport.failures import UpdateTransportStepError
from vibesensor.use_cases.updates.wifi.wifi_config import build_default_wifi_config
from vibesensor.use_cases.updates.wifi.wifi_uplink_setup import (
    UpdateUplinkProvisioner,
    ssid_security_modes,
)


def _build_uplink_provisioner(
    tmp_path: Path,
    *,
    uplink_connect_retries: int = 3,
    uplink_rescan_delay_s: float = 0.0,
) -> tuple[UpdateUplinkProvisioner, FakeRunner, UpdateStatusTracker]:
    runner = FakeRunner()
    status = build_update_status_harness(tmp_path / "state.json")
    commands = UpdateCommandExecutor(runner=runner)
    provisioner = UpdateUplinkProvisioner(
        commands=commands,
        status=status,
        config=replace(
            build_default_wifi_config(ap_con_name="VibeSensor-AP", wifi_ifname="wlan0"),
            uplink_connect_retries=uplink_connect_retries,
            uplink_rescan_delay_s=uplink_rescan_delay_s,
        ),
    )
    return provisioner, runner, status


def test_ssid_security_modes_handles_escaped_ssids() -> None:
    scan_output = "Cafe\\:Guest:WPA2 WPA3\nOpenNet:--\n"

    assert ssid_security_modes(scan_output, "Cafe:Guest") == {"WPA2 WPA3"}
    assert ssid_security_modes(scan_output, "OpenNet") == set()


@pytest.mark.asyncio
async def test_prepare_uplink_connection_requires_password_for_secured_network(
    tmp_path: Path,
) -> None:
    provisioner, runner, _status = _build_uplink_provisioner(tmp_path)
    runner.set_response("dev wifi list", 0, "Pim:WPA2 WPA3\n")

    with pytest.raises(
        UpdateTransportStepError,
        match="Wi-Fi password required for secured network",
    ):
        await provisioner.prepare_uplink_connection("Pim", "")


@pytest.mark.asyncio
async def test_prepare_uplink_connection_reports_password_configuration_failure(
    tmp_path: Path,
) -> None:
    provisioner, runner, _status = _build_uplink_provisioner(tmp_path)
    runner.set_response("wifi-sec.psk", 10, "", "failed to set Wi-Fi credentials")

    with pytest.raises(
        UpdateTransportStepError,
        match="Failed to set Wi-Fi credentials",
    ) as exc_info:
        await provisioner.prepare_uplink_connection("Pim", "tomaat123")

    assert exc_info.value.detail == "failed to set Wi-Fi credentials"


@pytest.mark.asyncio
async def test_bring_uplink_up_retries_ssid_not_found_then_succeeds(
    tmp_path: Path,
) -> None:
    provisioner, runner, tracker = _build_uplink_provisioner(tmp_path)
    runner.set_response_sequence(
        "connection up VibeSensor-Uplink",
        (10, "", "Error: No network with SSID 'TestNet' found.\n"),
        (0, "", ""),
    )

    await provisioner.bring_uplink_up("TestNet")

    assert any("rescanning and retrying" in line for line in tracker.status.log_tail)


@pytest.mark.asyncio
async def test_bring_uplink_up_fails_immediately_for_non_retryable_error(
    tmp_path: Path,
) -> None:
    provisioner, runner, _status = _build_uplink_provisioner(tmp_path)
    runner.set_response(
        "connection up VibeSensor-Uplink",
        10,
        "",
        "Error: Connection activation failed",
    )

    with pytest.raises(
        UpdateTransportStepError,
        match="Failed to connect to Wi-Fi 'TestNet'",
    ) as exc_info:
        await provisioner.bring_uplink_up("TestNet")

    assert exc_info.value.detail == "Error: Connection activation failed"


@pytest.mark.asyncio
async def test_bring_uplink_up_exhausts_retryable_ssid_not_found_error(
    tmp_path: Path,
) -> None:
    provisioner, runner, tracker = _build_uplink_provisioner(tmp_path, uplink_connect_retries=2)
    runner.set_response(
        "connection up VibeSensor-Uplink",
        10,
        "",
        "Error: No network with SSID 'TestNet' found.\n",
    )

    with pytest.raises(
        UpdateTransportStepError,
        match="Failed to connect to Wi-Fi 'TestNet'",
    ) as exc_info:
        await provisioner.bring_uplink_up("TestNet")

    assert exc_info.value.detail == "Error: No network with SSID 'TestNet' found.\n"
    assert any("rescanning and retrying" in line for line in tracker.status.log_tail)
