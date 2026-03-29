"""Shared Bluetooth/OBD utility helpers."""

from __future__ import annotations

from vibesensor.domain import normalize_sensor_id

__all__ = ["bluetooth_mac_address", "normalize_obd_mac"]


def normalize_obd_mac(value: str) -> str:
    """Normalize and validate an OBD adapter MAC address."""
    return normalize_sensor_id(value)


def bluetooth_mac_address(value: str) -> str:
    """Return *value* as an upper-case colon-separated Bluetooth MAC string."""
    normalized = normalize_obd_mac(value)
    return ":".join(normalized[index : index + 2].upper() for index in range(0, len(normalized), 2))
