"""GPSD message classification and typed field extraction.

Separates wire-format parsing from transport-state mutation so GPSD
protocol rules can evolve independently of ``GPSTransportState``
snapshot updates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from vibesensor.common.json_types import JsonObject
from vibesensor.common.type_checks import NUMERIC_TYPES


@dataclass(frozen=True, slots=True)
class GpsdReceivers:
    """The receivers gpsd reports: a DEVICES list, or one DEVICE change.

    gpsd greets every client with its VERSION and, once watching, a DEVICES
    list, even when no receiver is plugged in; only a listed device means a
    receiver is there. A hot-plugged receiver arrives as a DEVICE message and
    one unplugged as a DEVICE message with ``"activated": 0``.
    """

    added: tuple[str, ...]
    removed: tuple[str, ...] = ()
    replaces_all: bool = False
    """A DEVICES list names every receiver: anything not in it is gone."""


@dataclass(frozen=True, slots=True)
class NormalizedTpvData:
    """Typed fields extracted from a GPSD TPV message."""

    mode: int | None
    speed: float | None
    epx: float | None
    epy: float | None
    epv: float | None
    device: str | None


GpsdMessage = GpsdReceivers | NormalizedTpvData | None
"""Classified result: receiver presence, normalized TPV data, or None for
unsupported message classes."""


def read_tpv_mode(payload: JsonObject) -> int | None:
    """Extract the TPV fix mode as a validated integer."""
    mode = payload.get("mode")
    if isinstance(mode, int) and not isinstance(mode, bool):
        return mode
    return None


def read_non_negative_metric(payload: JsonObject, field: str) -> float | None:
    """Extract a non-negative finite float metric from *payload*."""
    value = payload.get(field)
    if isinstance(value, NUMERIC_TYPES) and not isinstance(value, bool):
        numeric_value = float(value)
        if math.isfinite(numeric_value) and numeric_value >= 0:
            return numeric_value
    return None


def _read_speed(payload: JsonObject) -> float | None:
    """Extract speed as a validated finite float, or None."""
    speed = payload.get("speed")
    if isinstance(speed, NUMERIC_TYPES) and not isinstance(speed, bool):
        speed_f = float(speed)
        if math.isfinite(speed_f):
            return speed_f
    return None


def _read_device(
    payload: JsonObject,
) -> str | None:
    """Extract device string if present and non-empty."""
    device = payload.get("device")
    if isinstance(device, str) and device:
        return device
    return None


def _device_path(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    path = payload.get("path")
    return path if isinstance(path, str) and path else None


def _receivers(payload: JsonObject) -> GpsdReceivers | None:
    if payload.get("class") == "DEVICES":
        devices = payload.get("devices")
        if not isinstance(devices, list):
            return None
        paths = tuple(path for path in map(_device_path, devices) if path is not None)
        return GpsdReceivers(added=paths, replaces_all=True)
    path = _device_path(payload)
    if path is None:
        return None
    activated = payload.get("activated")
    if activated == 0 and not isinstance(activated, bool):
        return GpsdReceivers(added=(), removed=(path,))
    return GpsdReceivers(added=(path,))


def classify_gpsd_message(payload: JsonObject) -> GpsdMessage:
    """Classify a raw GPSD JSON message and extract typed fields.

    Returns ``GpsdReceivers`` for DEVICES/DEVICE messages, a
    ``NormalizedTpvData`` for TPV messages, or ``None`` for
    unsupported message classes (VERSION, WATCH, SKY, ...).
    """
    payload_class = payload.get("class")

    if payload_class in ("DEVICES", "DEVICE"):
        return _receivers(payload)

    if payload_class == "TPV":
        return NormalizedTpvData(
            mode=read_tpv_mode(payload),
            speed=_read_speed(payload),
            epx=read_non_negative_metric(payload, "epx"),
            epy=read_non_negative_metric(payload, "epy"),
            epv=read_non_negative_metric(payload, "epv"),
            device=_read_device(payload),
        )

    return None
