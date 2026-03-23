"""Shared speed-source configuration contracts and helpers."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, TypeAlias

from typing_extensions import TypedDict  # noqa: UP035 (Pydantic on Python 3.11)

from vibesensor.domain.speed_source import SpeedSourceKind
from vibesensor.shared.constants import NUMERIC_TYPES

if TYPE_CHECKING:
    from vibesensor.domain import SpeedSource

__all__ = [
    "ResolvedSpeedSource",
    "SpeedSourceConfig",
    "SpeedSourcePayload",
    "SpeedSourceUpdatePayload",
    "VALID_SPEED_SOURCES",
    "_parse_manual_speed",
]

_isfinite = math.isfinite

ResolvedSpeedSource: TypeAlias = Literal["gps", "manual", "fallback_manual", "none"]
VALID_SPEED_SOURCES: tuple[str, ...] = tuple(kind.value for kind in SpeedSourceKind)


class SpeedSourceUpdatePayload(TypedDict, total=False):
    speedSource: SpeedSourceKind
    manualSpeedKph: float | None
    staleTimeoutS: float


class SpeedSourcePayload(TypedDict):
    speedSource: SpeedSourceKind
    manualSpeedKph: float | None
    staleTimeoutS: float


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


@dataclass(slots=True)
class SpeedSourceConfig:
    """Speed source settings (GPS, OBD2, or manual) with fallback policy."""

    speed_source: SpeedSourceKind
    manual_speed_kph: float | None
    stale_timeout_s: float

    @classmethod
    def default(cls) -> SpeedSourceConfig:
        """Return a GPS-based default speed source config."""
        return cls(
            speed_source=SpeedSourceKind.GPS,
            manual_speed_kph=None,
            stale_timeout_s=10.0,
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
        )

    def to_dict(self) -> SpeedSourcePayload:
        """Serialize this speed source config to a plain dict for JSON persistence."""
        return {
            "speedSource": self.speed_source,
            "manualSpeedKph": self.manual_speed_kph,
            "staleTimeoutS": self.stale_timeout_s,
        }

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
        if self.speed_source == SpeedSourceKind.MANUAL and self.manual_speed_kph is None:
            raise ValueError("SpeedSourceConfig with speed_source=MANUAL requires manual_speed_kph")

    def to_speed_source(self) -> SpeedSource:
        """Return the domain ``SpeedSource`` value object for this config."""
        from vibesensor.domain import SpeedSource

        return SpeedSource(
            kind=self.speed_source,
            manual_speed_kmh=self.manual_speed_kph,
        )
