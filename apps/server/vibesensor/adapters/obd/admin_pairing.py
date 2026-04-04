"""Bluetooth OBD pairing workflow."""

from __future__ import annotations

from vibesensor.adapters.obd.common import bluetooth_mac_address, normalize_obd_mac
from vibesensor.adapters.obd.models import ObdDeviceSnapshot

from .admin_bluetooth import BluetoothAdminSession, HelperFailure
from .admin_inspection import BluetoothObdDeviceInspector

__all__ = ["BluetoothObdPairer"]


class BluetoothObdPairer:
    """Pair, trust, connect, and verify one Bluetooth OBD adapter."""

    __slots__ = ("_bluetooth", "_inspector")

    def __init__(
        self,
        *,
        bluetooth: BluetoothAdminSession,
        inspector: BluetoothObdDeviceInspector,
    ) -> None:
        self._bluetooth = bluetooth
        self._inspector = inspector

    def pair_device(self, mac_address: str) -> ObdDeviceSnapshot:
        normalized = normalize_obd_mac(mac_address)
        self._bluetooth.prepare_controller()
        bt_mac = bluetooth_mac_address(normalized)
        self._bluetooth.bluetoothctl("agent", "on", timeout_s=5, ignore_errors=True)
        self._bluetooth.bluetoothctl("default-agent", timeout_s=5, ignore_errors=True)
        self._bluetooth.bluetoothctl("pair", bt_mac, timeout_s=25, ignore_errors=True)
        self._bluetooth.bluetoothctl("trust", bt_mac, timeout_s=10, ignore_errors=True)
        self._bluetooth.bluetoothctl("connect", bt_mac, timeout_s=15, ignore_errors=True)
        device = self._inspector.device_info(normalized, ensure_ready=False)
        if not device.paired:
            raise HelperFailure("Bluetooth OBD pairing did not complete successfully")
        if not device.trusted:
            raise HelperFailure("Bluetooth OBD adapter paired, but trust setup failed")
        return device
