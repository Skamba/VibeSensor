"""Speed-resolution policy for GPS and manual overrides."""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import NamedTuple

from vibesensor.shared.constants import KMH_TO_MPS, NUMERIC_TYPES
from vibesensor.shared.types.speed_source_config import ResolvedSpeedSource

LOGGER = logging.getLogger(__name__)

DEFAULT_STALE_TIMEOUT_S: float = 10.0
MIN_STALE_TIMEOUT_S: float = 3.0
MAX_STALE_TIMEOUT_S: float = 120.0
MAX_MANUAL_SPEED_KMH: float = 500.0
"""Upper bound for manually supplied speed overrides."""


class SpeedResolution(NamedTuple):
    """Immutable snapshot of the resolved speed state — no side effects."""

    speed_mps: float | None
    fallback_active: bool
    source: ResolvedSpeedSource


@dataclass
class SpeedResolutionPolicy:
    """Encapsulates override priority, stale fallback, and source selection."""

    override_speed_mps: float | None = None
    manual_source_selected: bool = True
    stale_timeout_s: float = DEFAULT_STALE_TIMEOUT_S

    def resolve(
        self,
        *,
        gps_enabled: bool,
        connection_state: str,
        speed_snapshot: tuple[float | None, float | None],
    ) -> SpeedResolution:
        if self.manual_source_selected and isinstance(self.override_speed_mps, NUMERIC_TYPES):
            override_speed = self.override_speed_mps
            if override_speed is not None and not isinstance(override_speed, bool):
                return SpeedResolution(float(override_speed), False, "manual")

        gps_speed, _ = speed_snapshot
        if isinstance(gps_speed, NUMERIC_TYPES) and not isinstance(gps_speed, bool):
            if self.is_gps_stale(speed_snapshot):
                fallback_speed = self.fallback_speed_value()
                return SpeedResolution(
                    fallback_speed,
                    True,
                    "fallback_manual" if fallback_speed is not None else "none",
                )
            return SpeedResolution(float(gps_speed), False, "gps")

        effective_connection = self.effective_connection_state(
            gps_enabled=gps_enabled,
            actual_connection_state=connection_state,
            speed_snapshot=speed_snapshot,
        )
        if gps_enabled and effective_connection in ("disconnected", "stale"):
            fallback_speed = self.fallback_speed_value()
            return SpeedResolution(
                fallback_speed,
                True,
                "fallback_manual" if fallback_speed is not None else "none",
            )

        return SpeedResolution(None, False, "none")

    def effective_connection_state(
        self,
        *,
        gps_enabled: bool,
        actual_connection_state: str,
        speed_snapshot: tuple[float | None, float | None],
    ) -> str:
        if (
            gps_enabled
            and actual_connection_state == "connected"
            and self.is_gps_stale(speed_snapshot)
        ):
            return "stale"
        return actual_connection_state

    def is_gps_stale(self, speed_snapshot: tuple[float | None, float | None]) -> bool:
        _, timestamp = speed_snapshot
        if timestamp is None:
            return True
        age = time.monotonic() - timestamp
        return age > self.stale_timeout_s

    def fallback_speed_value(self) -> float | None:
        if isinstance(self.override_speed_mps, NUMERIC_TYPES) and not isinstance(
            self.override_speed_mps, bool
        ):
            override_speed = self.override_speed_mps
            if override_speed is not None:
                return float(override_speed)
        return None

    def set_speed_override_kmh(self, speed_kmh: float | None) -> float | None:
        if speed_kmh is None:
            self.override_speed_mps = None
            return None
        speed_val = float(speed_kmh)
        if speed_val < 0 or not math.isfinite(speed_val):
            self.override_speed_mps = None
            return None
        if speed_val > MAX_MANUAL_SPEED_KMH:
            LOGGER.warning(
                "Manual speed override %.1f km/h exceeds cap %.1f km/h; clamping.",
                speed_val,
                MAX_MANUAL_SPEED_KMH,
            )
            speed_val = MAX_MANUAL_SPEED_KMH
        self.override_speed_mps = speed_val * KMH_TO_MPS
        return speed_val

    def set_manual_source_selected(self, selected: bool) -> None:
        self.manual_source_selected = bool(selected)

    def set_fallback_settings(
        self,
        stale_timeout_s: float | None = None,
        **_kwargs: object,
    ) -> None:
        if stale_timeout_s is not None:
            self.stale_timeout_s = max(
                MIN_STALE_TIMEOUT_S,
                min(MAX_STALE_TIMEOUT_S, float(stale_timeout_s)),
            )
