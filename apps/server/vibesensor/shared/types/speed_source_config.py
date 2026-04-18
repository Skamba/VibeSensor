"""Shared speed-source configuration contracts and helpers."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, NotRequired, TypedDict

from vibesensor.domain import normalize_sensor_id
from vibesensor.domain.speed_source import SpeedSourceKind
from vibesensor.shared.constants.type_checks import NUMERIC_TYPES

if TYPE_CHECKING:
    from vibesensor.domain import SpeedSource

__all__ = [
    "ResolvedSpeedSource",
    "SpeedSourceConfig",
    "SpeedSourcePayload",
    "SpeedSourceUpdatePayload",
    "_parse_manual_speed",
]

_isfinite = math.isfinite

type ResolvedSpeedSource = Literal["gps", "obd2", "manual", "fallback_manual", "none"]


class SpeedSourceUpdatePayload(TypedDict, total=False):
    speedSource: SpeedSourceKind
    manualSpeedKph: float | None
    staleTimeoutS: float
    obdDeviceMac: str | None
    obdDeviceName: str | None


class SpeedSourcePayload(TypedDict):
    speedSource: SpeedSourceKind
    manualSpeedKph: float | None
    staleTimeoutS: float
    obdDeviceMac: NotRequired[str | None]
    obdDeviceName: NotRequired[str | None]


def _parse_manual_speed(value: object) -> float | None:
    """Return a positive, finite float speed (≤500 km/h) or None."""
    if isinstance(value, NUMERIC_TYPES):
        speed = float(value)
        if _isfinite(speed) and 0 < speed <= 500:
            return speed
    return None


def _parse_stale_timeout(value: object) -> float:
    """Return a stale-timeout value clamped to [3, 120], default 10."""
    if isinstance(value, NUMERIC_TYPES):
        return max(3.0, min(120.0, float(value)))
    return 10.0


def _coerce_speed_source(value: object) -> SpeedSourceKind:
    if isinstance(value, str):
        try:
            return SpeedSourceKind(value)
        except ValueError:
            pass
    return SpeedSourceKind.GPS


def _parse_obd_device_mac(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        try:
            return normalize_sensor_id(candidate)
        except ValueError:
            return None
    return None


def _parse_obd_device_name(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        name = value.strip()
        if not name:
            return None
        return name[:128]
    return None


@dataclass(slots=True)
class SpeedSourceConfig:
    """Speed source settings (GPS, OBD2, or manual) with fallback policy."""

    speed_source: SpeedSourceKind
    manual_speed_kph: float | None
    stale_timeout_s: float
    obd_device_mac: str | None = None
    obd_device_name: str | None = None

    @property
    def manual_source_selected(self) -> bool:
        return self.speed_source is SpeedSourceKind.MANUAL

    @classmethod
    def default(cls) -> SpeedSourceConfig:
        """Return a GPS-based default speed source config."""
        return cls(
            speed_source=SpeedSourceKind.GPS,
            manual_speed_kph=None,
            stale_timeout_s=10.0,
            obd_device_mac=None,
            obd_device_name=None,
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> SpeedSourceConfig:
        """Construct a :class:`SpeedSourceConfig` from a raw dict (e.g., from API payload)."""
        speed_source = _coerce_speed_source(data.get("speedSource"))
        manual_speed_kph = _parse_manual_speed(data.get("manualSpeedKph"))
        stale_timeout_s = _parse_stale_timeout(data.get("staleTimeoutS"))
        return cls(
            speed_source=speed_source,
            manual_speed_kph=manual_speed_kph,
            stale_timeout_s=stale_timeout_s,
            obd_device_mac=_parse_obd_device_mac(data.get("obdDeviceMac")),
            obd_device_name=_parse_obd_device_name(data.get("obdDeviceName")),
        )

    def to_dict(self) -> SpeedSourcePayload:
        """Serialize this speed source config to a plain dict for JSON persistence."""
        payload: SpeedSourcePayload = {
            "speedSource": self.speed_source,
            "manualSpeedKph": self.manual_speed_kph,
            "staleTimeoutS": self.stale_timeout_s,
        }
        if self.obd_device_mac is not None:
            payload["obdDeviceMac"] = self.obd_device_mac
        if self.obd_device_name is not None:
            payload["obdDeviceName"] = self.obd_device_name
        return payload

    def copy(self) -> SpeedSourceConfig:
        return SpeedSourceConfig(
            speed_source=self.speed_source,
            manual_speed_kph=self.manual_speed_kph,
            stale_timeout_s=self.stale_timeout_s,
            obd_device_mac=self.obd_device_mac,
            obd_device_name=self.obd_device_name,
        )

    def updated(self, data: SpeedSourceUpdatePayload) -> SpeedSourceConfig:
        updated = self.copy()
        updated.apply_update(data)
        return updated

    def apply_update(self, data: SpeedSourceUpdatePayload) -> None:
        """Mutate in-place from an API update payload."""
        speed_source = data.get("speedSource")
        if speed_source is not None:
            self.speed_source = _coerce_speed_source(speed_source)
        if "manualSpeedKph" in data:
            manual_speed = data["manualSpeedKph"]
            if manual_speed is None:
                self.manual_speed_kph = None
            else:
                self.manual_speed_kph = _parse_manual_speed(manual_speed)
        stale_timeout = data.get("staleTimeoutS")
        if stale_timeout is not None:
            self.stale_timeout_s = _parse_stale_timeout(stale_timeout)
        if "obdDeviceMac" in data:
            self.obd_device_mac = _parse_obd_device_mac(data["obdDeviceMac"])
            if self.obd_device_mac is None:
                self.obd_device_name = None
        if "obdDeviceName" in data:
            self.obd_device_name = _parse_obd_device_name(data["obdDeviceName"])
        if self.obd_device_mac is None:
            self.obd_device_name = None
        if self.speed_source == SpeedSourceKind.MANUAL and self.manual_speed_kph is None:
            raise ValueError("SpeedSourceConfig with speed_source=MANUAL requires manual_speed_kph")

    def to_speed_source(self) -> SpeedSource:
        """Return the domain ``SpeedSource`` value object for this config."""
        from vibesensor.domain import SpeedSource

        return SpeedSource(
            kind=self.speed_source,
            manual_speed_kmh=self.manual_speed_kph,
        )
