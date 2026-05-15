from __future__ import annotations

from vibesensor.adapters.obd.admin_device_parsing import (
    parse_bluetooth_device_info,
    parse_bluetooth_scan_events,
)
from vibesensor.adapters.obd.admin_helper import BluetoothObdAdminHelper


def test_parse_bluetooth_device_info_prefers_local_name_over_mac_alias() -> None:
    device = parse_bluetooth_device_info(
        """
        Device 57:17:41:56:58:40
        Alias: 57-17-41-56-58-40
        LocalName: Vgate iCar Pro BLE 4.0
        Paired: no
        Trusted: no
        Connected: no
        """,
        "57:17:41:56:58:40",
    )

    assert device.name == "Vgate iCar Pro BLE 4.0"
    assert device.mac_address == "571741565840"


def test_parse_bluetooth_device_info_keeps_human_readable_alias_when_name_missing() -> None:
    device = parse_bluetooth_device_info(
        """
        Device 57:17:41:56:58:40
        Alias: OBDLink CX
        Paired: yes
        Trusted: yes
        Connected: no
        """,
        "57:17:41:56:58:40",
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
        ): (0, "[NEW] Device 57:17:41:56:58:40 57-17-41-56-58-40", ""),
        (
            "bluetoothctl",
            "devices",
        ): (0, "Device 57:17:41:56:58:40 57-17-41-56-58-40", ""),
        ("bluetoothctl", "devices", "Paired"): (0, "", ""),
        ("bluetoothctl", "paired-devices"): (0, "", ""),
        ("bluetoothctl", "scan", "off"): (0, "", ""),
        (
            "bluetoothctl",
            "info",
            "57:17:41:56:58:40",
        ): (
            0,
            """
            Device 57:17:41:56:58:40
            Name: Veepeak BLE+
            Alias: 57-17-41-56-58-40
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
    assert ("bluetoothctl", "info", "57:17:41:56:58:40") in calls
    assert not any(call and call[0] == "sdptool" for call in calls)


def test_parse_bluetooth_scan_events_parses_new_device_lines_with_ansi() -> None:
    devices = parse_bluetooth_scan_events(
        "\x1b[0;92m[NEW]\x1b[0m Device 00:22:D9:00:1B:B1 Audioengine HD6\n"
        "\x1b[0;93m[CHG]\x1b[0m Device 00:22:D9:00:1B:B1 RSSI: 0xffffffd6 (-42)\n"
    )

    assert len(devices) == 1
    assert devices[0].mac_address == "0022d9001bb1"
    assert devices[0].name == "Audioengine HD6"


def test_scan_devices_uses_timed_scan_output_and_sorts_human_names() -> None:
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
                    "[NEW] Device 53:40:AC:57:11:77 53-40-AC-57-11-77",
                    "[NEW] Device 00:22:D9:00:1B:B1 Audioengine HD6",
                    "[NEW] Device 11:22:33:44:55:66",
                ]
            ),
            "",
        ),
        ("bluetoothctl", "devices"): (0, "", ""),
        ("bluetoothctl", "devices", "Paired"): (0, "", ""),
        ("bluetoothctl", "paired-devices"): (0, "", ""),
        ("bluetoothctl", "scan", "off"): (0, "", ""),
        (
            "bluetoothctl",
            "info",
            "53:40:AC:57:11:77",
        ): (
            0,
            """
            Device 53:40:AC:57:11:77
            Alias: 53-40-AC-57-11-77
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
    calls: list[tuple[str, ...]] = []

    def runner(argv: list[str], timeout_s: int, allow_timeout: bool) -> tuple[int, str, str]:
        del timeout_s, allow_timeout
        key = tuple(argv)
        calls.append(key)
        return responses[key]

    devices = BluetoothObdAdminHelper(runner=runner).scan_devices(timeout_s=8)

    assert [device.mac_address for device in devices] == [
        "0022d9001bb1",
        "112233445566",
        "5340ac571177",
    ]
    assert devices[0].name == "Audioengine HD6"
    assert (
        "bluetoothctl",
        "--timeout",
        "8",
        "scan",
        "on",
    ) in calls
