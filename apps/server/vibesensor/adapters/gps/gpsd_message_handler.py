"""GPSD message classification and typed field extraction.

Separates wire-format parsing from transport-state mutation so GPSD
protocol rules can evolve independently of ``GPSTransportState``
snapshot updates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from vibesensor.shared.constants.type_checks import NUMERIC_TYPES
from vibesensor.shared.types.json_types import JsonObject


@dataclass(frozen=True, slots=True)
class GpsdVersionInfo:
    """Normalized VERSION message payload."""

    revision: str


@dataclass(frozen=True, slots=True)
class NormalizedTpvData:
    """Typed fields extracted from a GPSD TPV message."""

    mode: int | None
    speed: float | None
    epx: float | None
    epy: float | None
    epv: float | None
    device: str | None


GpsdMessage = GpsdVersionInfo | NormalizedTpvData | None
"""Classified result: VERSION info, normalized TPV data, or None for
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


def classify_gpsd_message(payload: JsonObject) -> GpsdMessage:
    """Classify a raw GPSD JSON message and extract typed fields.

    Returns a ``GpsdVersionInfo`` for VERSION messages, a
    ``NormalizedTpvData`` for TPV messages, or ``None`` for
    unsupported message classes.
    """
    payload_class = payload.get("class")

    if payload_class == "VERSION":
        revision = payload.get("rev")
        if isinstance(revision, str):
            return GpsdVersionInfo(revision=revision)
        return None

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
