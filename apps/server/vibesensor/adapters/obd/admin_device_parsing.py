"""Bluetooth OBD device parsing and name-resolution helpers."""

from __future__ import annotations

import re

from vibesensor.adapters.obd.common import normalize_obd_mac
from vibesensor.adapters.obd.models import ObdDeviceSnapshot

__all__ = [
    "parse_bluetooth_device_info",
    "parse_bluetooth_devices",
    "parse_bluetooth_scan_events",
    "parse_rfcomm_channel",
]

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(raw: str) -> str:
    return _ANSI_ESCAPE_RE.sub("", raw)


def _clean_bluetooth_name(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip()
    return value or None


def _looks_like_mac_alias(raw: str | None) -> bool:
    value = _clean_bluetooth_name(raw)
    if value is None:
        return False
    compact = value.replace(":", "").replace("-", "")
    if len(compact) != 12:
        return False
    try:
        bytes.fromhex(compact)
    except ValueError:
        return False
    return True


def _has_human_readable_bluetooth_name(raw: str | None) -> bool:
    value = _clean_bluetooth_name(raw)
    return value is not None and not _looks_like_mac_alias(value)


def _preferred_bluetooth_name(*candidates: str | None) -> str | None:
    cleaned = [
        value for value in (_clean_bluetooth_name(candidate) for candidate in candidates) if value
    ]
    if not cleaned:
        return None
    for candidate in cleaned:
        if not _looks_like_mac_alias(candidate):
            return candidate
    return cleaned[0]


def parse_bluetooth_devices(output: str) -> list[ObdDeviceSnapshot]:
    """Parse ``bluetoothctl devices``-style output."""

    devices: dict[str, ObdDeviceSnapshot] = {}
    for raw_line in output.splitlines():
        line = _strip_ansi(raw_line).strip()
        if not line.startswith("Device "):
            continue
        _, raw_mac, *name_parts = line.split()
        try:
            mac_address = normalize_obd_mac(raw_mac)
        except ValueError:
            continue
        name = _clean_bluetooth_name(" ".join(name_parts))
        devices[mac_address] = ObdDeviceSnapshot(
            mac_address=mac_address,
            name=name,
            paired=False,
            trusted=False,
            connected=False,
            rfcomm_channel=None,
        )
    return list(devices.values())


def parse_bluetooth_scan_events(output: str) -> list[ObdDeviceSnapshot]:
    """Parse discovery lines from ``bluetoothctl --timeout N scan on`` output."""

    devices: dict[str, ObdDeviceSnapshot] = {}
    for raw_line in output.splitlines():
        line = _strip_ansi(raw_line).strip()
        if line.startswith("[NEW] Device "):
            line = line.removeprefix("[NEW] ").strip()
        elif not line.startswith("Device "):
            continue
        _, raw_mac, *name_parts = line.split()
        try:
            mac_address = normalize_obd_mac(raw_mac)
        except ValueError:
            continue
        devices[mac_address] = ObdDeviceSnapshot(
            mac_address=mac_address,
            name=_clean_bluetooth_name(" ".join(name_parts)),
            paired=False,
            trusted=False,
            connected=False,
            rfcomm_channel=None,
        )
    return list(devices.values())


def parse_bluetooth_device_info(output: str, mac_address: str) -> ObdDeviceSnapshot:
    """Parse ``bluetoothctl info`` output into an ``ObdDeviceSnapshot``."""

    name: str | None = None
    local_name: str | None = None
    alias: str | None = None
    paired = False
    trusted = False
    connected = False
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line.startswith("Name:"):
            name = _clean_bluetooth_name(line.partition(":")[2]) or name
        elif line.startswith("LocalName:"):
            local_name = _clean_bluetooth_name(line.partition(":")[2]) or local_name
        elif line.startswith("Alias:"):
            alias = _clean_bluetooth_name(line.partition(":")[2]) or alias
        elif line.startswith("Paired:"):
            paired = line.partition(":")[2].strip().lower() == "yes"
        elif line.startswith("Trusted:"):
            trusted = line.partition(":")[2].strip().lower() == "yes"
        elif line.startswith("Connected:"):
            connected = line.partition(":")[2].strip().lower() == "yes"
    return ObdDeviceSnapshot(
        mac_address=normalize_obd_mac(mac_address),
        name=_preferred_bluetooth_name(name, local_name, alias),
        paired=paired,
        trusted=trusted,
        connected=connected,
        rfcomm_channel=None,
    )


def parse_rfcomm_channel(output: str) -> int | None:
    """Return the first advertised RFCOMM channel from ``sdptool browse`` output."""

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line.lower().startswith("channel:"):
            continue
        _, _, value = line.partition(":")
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None
