"""Typed OBD adapter/runtime snapshots."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ObdDeviceSnapshot", "ObdStatusSnapshot"]


@dataclass(frozen=True, slots=True)
class ObdDeviceSnapshot:
    """Bluetooth identity/state for a single OBD adapter."""

    mac_address: str
    name: str | None
    paired: bool
    trusted: bool
    connected: bool
    rfcomm_channel: int | None


@dataclass(frozen=True, slots=True)
class ObdStatusSnapshot:
    """Detailed OBD runtime/admin snapshot for field diagnostics."""

    configured_device_mac: str | None
    configured_device_name: str | None
    connection_state: str
    device_mac: str | None
    device_name: str | None
    paired: bool
    trusted: bool
    connected: bool
    rfcomm_channel: int | None
    last_sample_age_s: float | None
    last_speed_kmh: float | None
    last_rpm: float | None
    last_error: str | None
    last_raw_response: str | None
    reconnect_delay_s: float | None
    debug_hint: str | None
