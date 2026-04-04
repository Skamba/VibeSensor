from __future__ import annotations

from vibesensor.adapters.obd.admin_device_parsing import (
    parse_bluetooth_device_info,
    parse_bluetooth_scan_events,
)
from vibesensor.adapters.obd.admin_helper import BluetoothObdAdminHelper


def test_parse_bluetooth_device_info_prefers_local_name_over_mac_alias() -> None:
    device = parse_bluetooth_device_info(
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

    assert device.name == "Vgate iCar Pro BLE 4.0"
    assert device.mac_address == "020000000040"


def test_parse_bluetooth_device_info_keeps_human_readable_alias_when_name_missing() -> None:
    device = parse_bluetooth_device_info(
        """
        Device 02:00:00:00:00:40
        Alias: OBDLink CX
        Paired: yes
        Trusted: yes
        Connected: no
        """,
        "02:00:00:00:00:40",
    )

    assert device.name == "OBDLink CX"
    assert device.paired is True
    assert device.trusted is True


def test_scan_devices_prefers_detailed_name_over_mac_alias() -> None:
    responses = {
        ("rfkill", "unblock", "bluetooth"): (0, "", ""),
        ("systemctl", "start", "bluetooth"): (0, "", ""),
        ("bluetoothctl", "power", "on"): (0, "", ""),
        (
            "bluetoothctl",
            "--timeout",
            "8",
            "scan",
            "on",
        ): (0, "[NEW] Device 02:00:00:00:00:40 02-00-00-00-00-40", ""),
        (
            "bluetoothctl",
            "devices",
        ): (0, "Device 02:00:00:00:00:40 02-00-00-00-00-40", ""),
        ("bluetoothctl", "devices", "Paired"): (0, "", ""),
        ("bluetoothctl", "paired-devices"): (0, "", ""),
        ("bluetoothctl", "scan", "off"): (0, "", ""),
        (
            "bluetoothctl",
            "info",
            "02:00:00:00:00:40",
        ): (
            0,
            """
            Device 02:00:00:00:00:40
            Name: Veepeak BLE+
            Alias: 02-00-00-00-00-40
            Paired: no
            Trusted: no
            Connected: no
            """,
            "",
        ),
    }
    calls: list[tuple[str, ...]] = []

    def runner(argv: list[str], timeout_s: int, allow_timeout: bool) -> tuple[int, str, str]:
        del timeout_s, allow_timeout
        key = tuple(argv)
        calls.append(key)
        return responses[key]

    devices = BluetoothObdAdminHelper(runner=runner).scan_devices(timeout_s=8)

    assert len(devices) == 1
    assert devices[0].name == "Veepeak BLE+"
    assert ("bluetoothctl", "info", "02:00:00:00:00:40") in calls
    assert not any(call and call[0] == "sdptool" for call in calls)


def test_parse_bluetooth_scan_events_parses_new_device_lines_with_ansi() -> None:
    devices = parse_bluetooth_scan_events(
        "\x1b[0;92m[NEW]\x1b[0m Device 02:00:00:00:00:B1 Test Speaker\n"
        "\x1b[0;93m[CHG]\x1b[0m Device 02:00:00:00:00:B1 RSSI: 0xffffffd6 (-42)\n"
    )

    assert len(devices) == 1
    assert devices[0].mac_address == "0200000000b1"
    assert devices[0].name == "Test Speaker"


def test_scan_devices_uses_timed_scan_output_when_devices_list_is_empty() -> None:
    responses = {
        ("rfkill", "unblock", "bluetooth"): (0, "", ""),
        ("systemctl", "start", "bluetooth"): (0, "", ""),
        ("bluetoothctl", "power", "on"): (0, "", ""),
        (
            "bluetoothctl",
            "--timeout",
            "8",
            "scan",
            "on",
        ): (
            0,
            "[NEW] Device 02:00:00:00:00:B1 Test Speaker",
            "",
        ),
        ("bluetoothctl", "devices"): (0, "", ""),
        ("bluetoothctl", "devices", "Paired"): (0, "", ""),
        ("bluetoothctl", "paired-devices"): (0, "", ""),
        ("bluetoothctl", "scan", "off"): (0, "", ""),
    }
    calls: list[tuple[str, ...]] = []

    def runner(argv: list[str], timeout_s: int, allow_timeout: bool) -> tuple[int, str, str]:
        del timeout_s, allow_timeout
        key = tuple(argv)
        calls.append(key)
        return responses[key]

    devices = BluetoothObdAdminHelper(runner=runner).scan_devices(timeout_s=8)

    assert len(devices) == 1
    assert devices[0].name == "Test Speaker"
    assert (
        "bluetoothctl",
        "--timeout",
        "8",
        "scan",
        "on",
    ) in calls


def test_scan_devices_sorts_human_readable_names_ahead_of_mac_aliases() -> None:
    responses = {
        ("rfkill", "unblock", "bluetooth"): (0, "", ""),
        ("systemctl", "start", "bluetooth"): (0, "", ""),
        ("bluetoothctl", "power", "on"): (0, "", ""),
        (
            "bluetoothctl",
            "--timeout",
            "8",
            "scan",
            "on",
        ): (
            0,
            "\n".join(
                [
                    "[NEW] Device 52:00:00:00:00:77 52-00-00-00-00-77",
                    "[NEW] Device 02:00:00:00:00:B1 Test Speaker",
                    "[NEW] Device 11:22:33:44:55:66",
                ]
            ),
            "",
        ),
        (
            "bluetoothctl",
            "devices",
        ): (
            0,
            "\n".join(
                [
                    "Device 52:00:00:00:00:77 52-00-00-00-00-77",
                    "Device 02:00:00:00:00:B1 Test Speaker",
                    "Device 11:22:33:44:55:66",
                ]
            ),
            "",
        ),
        ("bluetoothctl", "devices", "Paired"): (0, "", ""),
        ("bluetoothctl", "paired-devices"): (0, "", ""),
        ("bluetoothctl", "scan", "off"): (0, "", ""),
        (
            "bluetoothctl",
            "info",
            "52:00:00:00:00:77",
        ): (
            0,
            """
            Device 52:00:00:00:00:77
            Alias: 52-00-00-00-00-77
            Paired: no
            Trusted: no
            Connected: no
            """,
            "",
        ),
        (
            "bluetoothctl",
            "info",
            "11:22:33:44:55:66",
        ): (
            0,
            """
            Device 11:22:33:44:55:66
            Paired: no
            Trusted: no
            Connected: no
            """,
            "",
        ),
    }

    def runner(argv: list[str], timeout_s: int, allow_timeout: bool) -> tuple[int, str, str]:
        del timeout_s, allow_timeout
        return responses[tuple(argv)]

    devices = BluetoothObdAdminHelper(runner=runner).scan_devices(timeout_s=8)

    assert [device.mac_address for device in devices] == [
        "0200000000b1",
        "112233445566",
        "520000000077",
    ]
