"""Root-side Bluetooth OBD admin wrapper: parsing, scan/pair flows, and the client contract."""

from __future__ import annotations

import dataclasses
import json

import pytest
from test_support.root_helpers import load_root_helper

from vibesensor.common.privileged_helper import PrivilegedResult
from vibesensor.domain.sensor import normalize_sensor_id
from vibesensor.speed.obd.admin_client import POWER_ON_WAIT_S as CLIENT_POWER_ON_WAIT_S
from vibesensor.speed.obd.admin_client import ObdAdminClient
from vibesensor.speed.obd.models import ObdDeviceSnapshot

obd_admin = load_root_helper("vibesensor_obd_admin.py")

_BUSY = "Failed to set power on: org.bluez.Error.Busy"
_PREPARE = {
    ("rfkill", "unblock", "bluetooth"): (0, "", ""),
    ("systemctl", "start", "bluetooth"): (0, "", ""),
    ("bluetoothctl", "power", "on"): (0, "", ""),
}


def _scripted(responses: dict[tuple[str, ...], tuple[int, str, str]], calls: list[tuple[str, ...]]):
    def runner(argv: list[str], timeout_s: int, allow_timeout: bool) -> tuple[int, str, str]:
        del timeout_s, allow_timeout
        calls.append(tuple(argv))
        return responses[tuple(argv)]

    return obd_admin.BluetoothAdmin(runner=runner)


def test_wrapper_matches_the_server_client_contract() -> None:
    assert obd_admin.POWER_ON_WAIT_S == CLIENT_POWER_ON_WAIT_S
    assert [f.name for f in dataclasses.fields(obd_admin.Device)] == [
        f.name for f in dataclasses.fields(ObdDeviceSnapshot)
    ]
    for raw in ("AA:BB:CC:DD:EE:FF", "aabbccddeeff", " 02000000004D "):
        assert obd_admin.normalize_mac(raw) == normalize_sensor_id(raw)
    for bad in ("AA:BB:CC", "zzbbccddeeff"):
        with pytest.raises(ValueError):
            obd_admin.normalize_mac(bad)


def test_device_info_prefers_local_name_over_mac_alias_and_keeps_human_alias() -> None:
    device = obd_admin.parse_device_info(
        """
        Device 02:00:00:00:00:40
        Alias: 02-00-00-00-00-40
        LocalName: Vgate iCar Pro BLE 4.0
        Paired: no
        Trusted: no
        Connected: no
        """,
        "02:00:00:00:00:40",
    )
    aliased = obd_admin.parse_device_info(
        "Alias: OBDLink CX\nPaired: yes\nTrusted: yes\nConnected: no\n", "02:00:00:00:00:40"
    )

    assert device.name == "Vgate iCar Pro BLE 4.0"
    assert device.mac_address == "020000000040"
    assert (aliased.name, aliased.paired, aliased.trusted, aliased.connected) == (
        "OBDLink CX",
        True,
        True,
        False,
    )


def test_scan_events_parse_new_device_lines_with_ansi() -> None:
    devices = obd_admin.parse_devices(
        "\x1b[0;92m[NEW]\x1b[0m Device 02:00:00:00:00:B1 Test Speaker\n"
        "\x1b[0;93m[CHG]\x1b[0m Device 02:00:00:00:00:B1 RSSI: 0xffffffd6 (-42)\n",
        scan_events=True,
    )

    assert [(d.mac_address, d.name) for d in devices] == [("0200000000b1", "Test Speaker")]


def test_scan_prefers_detailed_names_and_sorts_human_names_first() -> None:
    info = "Device {mac}\n{extra}Paired: no\nTrusted: no\nConnected: no\n"
    responses = {
        **_PREPARE,
        ("bluetoothctl", "--timeout", "8", "scan", "on"): (
            0,
            "[NEW] Device 52:00:00:00:00:77 52-00-00-00-00-77\n"
            "[NEW] Device 02:00:00:00:00:B1 Test Speaker\n"
            "[NEW] Device 11:22:33:44:55:66\n",
            "",
        ),
        ("bluetoothctl", "devices"): (0, "Device 02:00:00:00:00:40 02-00-00-00-00-40", ""),
        ("bluetoothctl", "devices", "Paired"): (0, "", ""),
        ("bluetoothctl", "paired-devices"): (0, "", ""),
        ("bluetoothctl", "scan", "off"): (0, "", ""),
        ("bluetoothctl", "info", "52:00:00:00:00:77"): (
            0,
            info.format(mac="52:00:00:00:00:77", extra="Alias: 52-00-00-00-00-77\n"),
            "",
        ),
        ("bluetoothctl", "info", "11:22:33:44:55:66"): (
            0,
            info.format(mac="11:22:33:44:55:66", extra=""),
            "",
        ),
        ("bluetoothctl", "info", "02:00:00:00:00:40"): (
            0,
            info.format(mac="02:00:00:00:00:40", extra="Name: Veepeak BLE+\n"),
            "",
        ),
    }
    calls: list[tuple[str, ...]] = []

    devices = _scripted(responses, calls).scan_devices(timeout_s=8)

    assert [(d.mac_address, d.name) for d in devices] == [
        ("0200000000b1", "Test Speaker"),
        ("020000000040", "Veepeak BLE+"),
        ("112233445566", None),
        ("520000000077", "52-00-00-00-00-77"),
    ]
    assert ("bluetoothctl", "scan", "off") in calls
    assert not any(call[0] == "sdptool" for call in calls)


def test_pair_runs_the_bluetoothctl_sequence_and_requires_trust() -> None:
    mac = "02:00:00:00:00:4D"
    responses = {
        **_PREPARE,
        **{
            ("bluetoothctl", *step): (0, "", "")
            for step in (("agent", "on"), ("default-agent",), ("pair", mac), ("trust", mac))
        },
        ("bluetoothctl", "connect", mac): (1, "", "Failed to connect"),
        ("bluetoothctl", "info", mac): (0, "Paired: yes\nTrusted: no\nConnected: no\n", ""),
        ("sdptool", "browse", mac): (0, "Service Name: SPP\nChannel: 1\n", ""),
    }
    calls: list[tuple[str, ...]] = []

    with pytest.raises(obd_admin.HelperFailure, match="trust setup failed"):
        _scripted(responses, calls).pair_device("02000000004d")

    responses["bluetoothctl", "info", mac] = (0, "Paired: yes\nTrusted: yes\nConnected: yes\n", "")
    device = _scripted(responses, calls).pair_device("02000000004d")

    assert (device.paired, device.trusted, device.connected, device.rfcomm_channel) == (
        True,
        True,
        True,
        1,
    )


class _FakeBluez:
    """Answer ``power on`` with *power_on_error* and report Powered after *powered_after_s*."""

    def __init__(self, *, power_on_error: str | None, powered_after_s: float | None) -> None:
        self.power_on_error = power_on_error
        self.powered_after_s = powered_after_s
        self.now = 0.0
        self.calls: list[tuple[str, ...]] = []

    def runner(self, argv: list[str], timeout_s: int, allow_timeout: bool) -> tuple[int, str, str]:
        del timeout_s, allow_timeout
        self.calls.append(tuple(argv))
        if argv == ["bluetoothctl", "power", "on"] and self.power_on_error is not None:
            return 1, "", self.power_on_error
        if argv == ["bluetoothctl", "show"]:
            powered = self.powered_after_s is not None and self.now >= self.powered_after_s
            return 0, f"Controller B8:27:EB:00:00:01\n\tPowered: {'yes' if powered else 'no'}\n", ""
        return 0, "", ""

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def admin(self):
        return obd_admin.BluetoothAdmin(
            runner=self.runner, sleep=self.sleep, monotonic=lambda: self.now
        )


def test_busy_power_on_waits_for_the_adapter_bluez_is_already_powering() -> None:
    bluez = _FakeBluez(power_on_error=_BUSY, powered_after_s=2.0)

    bluez.admin().prepare_controller()

    assert bluez.calls[:3] == list(_PREPARE)
    assert 2.0 <= bluez.now < obd_admin.POWER_ON_WAIT_S


def test_busy_power_on_fails_with_busy_when_the_adapter_never_powers() -> None:
    bluez = _FakeBluez(power_on_error=_BUSY, powered_after_s=None)

    with pytest.raises(obd_admin.HelperFailure, match=r"org\.bluez\.Error\.Busy"):
        bluez.admin().prepare_controller()

    assert obd_admin.POWER_ON_WAIT_S <= bluez.now < obd_admin.POWER_ON_WAIT_S + 1


def test_other_power_on_failures_are_not_waited_out() -> None:
    bluez = _FakeBluez(power_on_error="No default controller available", powered_after_s=0.0)

    with pytest.raises(obd_admin.HelperFailure, match="No default controller"):
        bluez.admin().prepare_controller()

    assert ("bluetoothctl", "show") not in bluez.calls
    assert bluez.now == 0.0


def test_main_output_round_trips_through_the_server_client(
    capsys: pytest.CaptureFixture[str],
) -> None:
    bluez = _FakeBluez(power_on_error=None, powered_after_s=0.0)

    def run_main(args: list[str]):
        code = obd_admin.main(args, admin=bluez.admin())
        return PrivilegedResult(code, capsys.readouterr().out, "")

    client = ObdAdminClient(runner=lambda args, _timeout: run_main(args))

    device = client.device_info("02:00:00:00:00:4D")
    assert device == ObdDeviceSnapshot("02000000004d", None, False, False, False, None)
    assert client.scan_devices(timeout_s=3) == []
    assert obd_admin.main(["info", "not-a-mac"], admin=bluez.admin()) == 1
    assert json.loads(capsys.readouterr().out) == {"error": "sensor_id must be 12 hex chars"}
