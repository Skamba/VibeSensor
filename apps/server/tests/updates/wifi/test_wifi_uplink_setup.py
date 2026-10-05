from __future__ import annotations

import os
import re
from dataclasses import replace
from pathlib import Path

import pytest
from test_support.update_status import build_update_status_harness
from updates._update_manager_test_helpers import FakeRunner

from vibesensor.updates.runner import UpdateCommandExecutor
from vibesensor.updates.status.tracker import UpdateStatusTracker
from vibesensor.updates.transport.failures import UpdateTransportStepError
from vibesensor.updates.wifi.wifi_config import build_default_wifi_config
from vibesensor.updates.wifi.wifi_uplink_setup import (
    UpdateUplinkProvisioner,
    psk_passwd_file,
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
    runner.set_response("dev wifi list", 0, "HomeNet:WPA2 WPA3\n")

    with pytest.raises(
        UpdateTransportStepError,
        match="Wi-Fi password required for secured network",
    ):
        await provisioner.prepare_uplink_connection("HomeNet", "")


def test_psk_passwd_file_escapes_what_nmcli_would_unescape_or_strip() -> None:
    assert psk_passwd_file("example-psk") == "802-11-wireless-security.psk:example-psk\n"
    assert psk_passwd_file(" a\\b:c ") == "802-11-wireless-security.psk:\\040a\\134b:c\\040\n"


@pytest.mark.asyncio
async def test_wifi_password_reaches_nmcli_through_memory_never_argv(tmp_path: Path) -> None:
    provisioner, runner, _status = _build_uplink_provisioner(tmp_path)
    # nmcli (here: a real reader of the same path) opens the passwd-file while
    # the command runs; afterwards the descriptor is closed.
    seen: list[str] = []
    original_run = runner.run

    async def reading_run(args, **kwargs):
        if "passwd-file" in args:
            seen.append(Path(args[args.index("passwd-file") + 1]).read_text())
        return await original_run(args, **kwargs)

    runner.run = reading_run

    await provisioner.prepare_uplink_connection("HomeNet", "example-psk")
    await provisioner.bring_uplink_up("HomeNet", "example-psk")

    assert all("example-psk" not in arg for args, _ in runner.calls for arg in args)
    configure, up = (args for args, _ in runner.calls[-2:])
    assert configure[-2:] == ["wifi-sec.key-mgmt", "wpa-psk"]
    assert up[-3:-1] == ["VibeSensor-Uplink", "passwd-file"]
    assert re.fullmatch(rf"/proc/{os.getpid()}/fd/\d+", up[-1])
    assert seen == ["802-11-wireless-security.psk:example-psk\n"]
    assert not Path(up[-1]).exists()


@pytest.mark.asyncio
async def test_open_network_is_brought_up_without_a_passwd_file(tmp_path: Path) -> None:
    provisioner, runner, _status = _build_uplink_provisioner(tmp_path)

    await provisioner.prepare_uplink_connection("Cafe", "")
    await provisioner.bring_uplink_up("Cafe", "")

    configure, up = (args for args, _ in runner.calls[-2:])
    assert "wifi-sec.key-mgmt" not in configure
    assert up[-1] == "VibeSensor-Uplink"


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

    await provisioner.bring_uplink_up("TestNet", "pass1234")

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
        await provisioner.bring_uplink_up("TestNet", "pass1234")

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
        await provisioner.bring_uplink_up("TestNet", "pass1234")

    assert exc_info.value.detail == "Error: No network with SSID 'TestNet' found.\n"
    assert any("rescanning and retrying" in line for line in tracker.status.log_tail)
