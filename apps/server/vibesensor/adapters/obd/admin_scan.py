"""Bluetooth OBD scan and enrichment services."""

from __future__ import annotations

from dataclasses import replace

from vibesensor.adapters.obd.models import ObdDeviceSnapshot

from .admin_bluetooth import BluetoothAdminSession, HelperFailure
from .admin_device_parsing import (
    _has_human_readable_bluetooth_name,
    _looks_like_mac_alias,
    _preferred_bluetooth_name,
    parse_bluetooth_devices,
    parse_bluetooth_scan_events,
)
from .admin_inspection import BluetoothObdDeviceInspector

__all__ = ["BluetoothObdScanner"]


class BluetoothObdScanner:
    """Scan for adapters and enrich discovered devices when needed."""

    __slots__ = ("_bluetooth", "_inspector")

    def __init__(
        self,
        *,
        bluetooth: BluetoothAdminSession,
        inspector: BluetoothObdDeviceInspector,
    ) -> None:
        self._bluetooth = bluetooth
        self._inspector = inspector

    def scan_devices(self, *, timeout_s: int) -> list[ObdDeviceSnapshot]:
        self._bluetooth.prepare_controller()
        scan_timeout_s = max(3, int(timeout_s))
        scan_output = self._bluetooth.run(
            ["bluetoothctl", "--timeout", str(scan_timeout_s), "scan", "on"],
            timeout_s=scan_timeout_s + 2,
            allow_timeout=False,
        )
        try:
            devices = {
                device.mac_address: device for device in parse_bluetooth_scan_events(scan_output)
            }
            devices.update(
                {
                    device.mac_address: device
                    for device in parse_bluetooth_devices(
                        self._bluetooth.bluetoothctl("devices", timeout_s=5, ignore_errors=True)
                    )
                }
            )
            paired_devices = {
                device.mac_address
                for device in parse_bluetooth_devices(
                    self._bluetooth.bluetoothctl(
                        "devices",
                        "Paired",
                        timeout_s=5,
                        ignore_errors=True,
                    )
                )
            }
            paired_devices.update(
                {
                    device.mac_address
                    for device in parse_bluetooth_devices(
                        self._bluetooth.bluetoothctl(
                            "paired-devices",
                            timeout_s=5,
                            ignore_errors=True,
                        )
                    )
                }
            )
        finally:
            self._bluetooth.bluetoothctl("scan", "off", timeout_s=5, ignore_errors=True)
        resolved: list[ObdDeviceSnapshot] = []
        for device in devices.values():
            needs_detailed_info = (
                device.mac_address in paired_devices
                or device.name is None
                or _looks_like_mac_alias(device.name)
            )
            if not needs_detailed_info:
                resolved.append(device)
                continue
            try:
                detailed = self._inspector.device_info(
                    device.mac_address,
                    ensure_ready=False,
                    resolve_rfcomm=False,
                )
            except HelperFailure:
                resolved.append(replace(device, paired=device.mac_address in paired_devices))
                continue
            resolved.append(
                replace(
                    detailed,
                    name=_preferred_bluetooth_name(detailed.name, device.name),
                    paired=detailed.paired or device.mac_address in paired_devices,
                )
            )
        return sorted(
            resolved,
            key=lambda device: (
                not device.connected,
                not device.paired,
                not _has_human_readable_bluetooth_name(device.name),
                (device.name or device.mac_address).lower(),
            ),
        )
