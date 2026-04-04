"""Device-info and RFCOMM lookup for Bluetooth OBD adapters."""

from __future__ import annotations

from dataclasses import replace

from vibesensor.adapters.obd.common import bluetooth_mac_address, normalize_obd_mac
from vibesensor.adapters.obd.models import ObdDeviceSnapshot

from .admin_bluetooth import BluetoothAdminSession, HelperFailure
from .admin_device_parsing import parse_bluetooth_device_info, parse_rfcomm_channel

__all__ = ["BluetoothObdDeviceInspector"]


class BluetoothObdDeviceInspector:
    """Resolve one adapter's Bluetooth and RFCOMM state."""

    __slots__ = ("_bluetooth",)

    def __init__(self, *, bluetooth: BluetoothAdminSession) -> None:
        self._bluetooth = bluetooth

    def device_info(
        self,
        mac_address: str,
        *,
        ensure_ready: bool = True,
        resolve_rfcomm: bool = True,
    ) -> ObdDeviceSnapshot:
        normalized = normalize_obd_mac(mac_address)
        if ensure_ready:
            self._bluetooth.prepare_controller()
        bt_mac = bluetooth_mac_address(normalized)
        info_output = self._bluetooth.bluetoothctl("info", bt_mac, timeout_s=8, ignore_errors=True)
        device = parse_bluetooth_device_info(info_output, normalized)
        if not resolve_rfcomm:
            return device
        try:
            channel_output = self._bluetooth.run(
                ["sdptool", "browse", bt_mac],
                timeout_s=10,
                allow_timeout=False,
            )
        except HelperFailure:
            channel = None
        else:
            channel = parse_rfcomm_channel(channel_output)
        return replace(device, rfcomm_channel=channel)
