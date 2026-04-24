"""Speed-resolution policy for live speed sources and manual overrides."""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, NamedTuple, cast

from vibesensor.shared.constants.type_checks import NUMERIC_TYPES
from vibesensor.shared.constants.units import KMH_TO_MPS
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


@dataclass(frozen=True, slots=True)
class SpeedResolutionPolicySnapshot:
    """Immutable policy snapshot captured by concurrent GPS readers."""

    override_speed_mps: float | None = None
    manual_source_selected: bool = True
    stale_timeout_s: float = DEFAULT_STALE_TIMEOUT_S


class SpeedResolutionPolicy:
    """Owns the immutable policy snapshot swapped atomically by writers."""

    def __init__(
        self,
        override_speed_mps: float | None = None,
        manual_source_selected: bool = True,
        stale_timeout_s: float = DEFAULT_STALE_TIMEOUT_S,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._snapshot = SpeedResolutionPolicySnapshot(
            override_speed_mps=self._normalized_override_speed_mps(override_speed_mps),
            manual_source_selected=bool(manual_source_selected),
            stale_timeout_s=self._normalized_stale_timeout(stale_timeout_s),
        )
        self._monotonic = monotonic

    def snapshot(self) -> SpeedResolutionPolicySnapshot:
        return self._snapshot

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SpeedResolutionPolicy) and self._snapshot == other._snapshot

    def _replace_snapshot(self, **changes: object) -> None:
        self._snapshot = replace(self._snapshot, **cast(dict[str, Any], changes))

    @property
    def override_speed_mps(self) -> float | None:
        return self._snapshot.override_speed_mps

    @override_speed_mps.setter
    def override_speed_mps(self, value: float | None) -> None:
        self._replace_snapshot(override_speed_mps=self._normalized_override_speed_mps(value))

    @property
    def manual_source_selected(self) -> bool:
        return self._snapshot.manual_source_selected

    @manual_source_selected.setter
    def manual_source_selected(self, value: bool) -> None:
        self._replace_snapshot(manual_source_selected=bool(value))

    @property
    def stale_timeout_s(self) -> float:
        return self._snapshot.stale_timeout_s

    @stale_timeout_s.setter
    def stale_timeout_s(self, value: float) -> None:
        self._replace_snapshot(stale_timeout_s=self._normalized_stale_timeout(value))

    @staticmethod
    def _normalized_override_speed_mps(value: float | None) -> float | None:
        if value is None or isinstance(value, bool) or not isinstance(value, NUMERIC_TYPES):
            return None
        speed_val = float(value)
        return speed_val if math.isfinite(speed_val) else None

    @staticmethod
    def _normalized_stale_timeout(value: float) -> float:
        return max(MIN_STALE_TIMEOUT_S, min(MAX_STALE_TIMEOUT_S, float(value)))

    @staticmethod
    def _normalized_override_speed_kmh(
        speed_kmh: float | None,
    ) -> tuple[float | None, float | None]:
        if speed_kmh is None:
            return None, None
        speed_val = float(speed_kmh)
        if speed_val < 0 or not math.isfinite(speed_val):
            return None, None
        if speed_val > MAX_MANUAL_SPEED_KMH:
            LOGGER.warning(
                "Manual speed override %.1f km/h exceeds cap %.1f km/h; clamping.",
                speed_val,
                MAX_MANUAL_SPEED_KMH,
            )
            speed_val = MAX_MANUAL_SPEED_KMH
        return speed_val * KMH_TO_MPS, speed_val

    def apply_speed_source_settings(
        self,
        *,
        effective_speed_kmh: float | None,
        manual_source_selected: bool,
        stale_timeout_s: float | None = None,
    ) -> float | None:
        override_speed_mps, applied_speed_kmh = self._normalized_override_speed_kmh(
            effective_speed_kmh
        )
        snapshot = self._snapshot
        resolved_timeout = (
            snapshot.stale_timeout_s
            if stale_timeout_s is None
            else self._normalized_stale_timeout(stale_timeout_s)
        )
        self._snapshot = SpeedResolutionPolicySnapshot(
            override_speed_mps=override_speed_mps,
            manual_source_selected=bool(manual_source_selected),
            stale_timeout_s=resolved_timeout,
        )
        return applied_speed_kmh

    def resolve(
        self,
        *,
        gps_enabled: bool,
        connection_state: str,
        speed_snapshot: tuple[float | None, float | None],
        snapshot: SpeedResolutionPolicySnapshot | None = None,
        live_source: ResolvedSpeedSource = "gps",
        reference_time_s: float | None = None,
    ) -> SpeedResolution:
        policy = self._snapshot if snapshot is None else snapshot
        if policy.manual_source_selected and isinstance(policy.override_speed_mps, NUMERIC_TYPES):
            override_speed = policy.override_speed_mps
            if override_speed is not None and not isinstance(override_speed, bool):
                return SpeedResolution(float(override_speed), False, "manual")

        gps_speed, _ = speed_snapshot
        if isinstance(gps_speed, NUMERIC_TYPES) and not isinstance(gps_speed, bool):
            if self.is_gps_stale(
                speed_snapshot,
                snapshot=policy,
                reference_time_s=reference_time_s,
            ):
                fallback_speed = self.fallback_speed_value(snapshot=policy)
                return SpeedResolution(
                    fallback_speed,
                    True,
                    "fallback_manual" if fallback_speed is not None else "none",
                )
            return SpeedResolution(float(gps_speed), False, live_source)

        effective_connection = self.effective_connection_state(
            gps_enabled=gps_enabled,
            actual_connection_state=connection_state,
            speed_snapshot=speed_snapshot,
            snapshot=policy,
            reference_time_s=reference_time_s,
        )
        if gps_enabled and effective_connection in ("disconnected", "stale"):
            fallback_speed = self.fallback_speed_value(snapshot=policy)
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
        snapshot: SpeedResolutionPolicySnapshot | None = None,
        reference_time_s: float | None = None,
    ) -> str:
        policy = self._snapshot if snapshot is None else snapshot
        if (
            gps_enabled
            and actual_connection_state == "connected"
            and self.is_gps_stale(
                speed_snapshot,
                snapshot=policy,
                reference_time_s=reference_time_s,
            )
        ):
            return "stale"
        return actual_connection_state

    def is_gps_stale(
        self,
        speed_snapshot: tuple[float | None, float | None],
        *,
        snapshot: SpeedResolutionPolicySnapshot | None = None,
        reference_time_s: float | None = None,
    ) -> bool:
        policy = self._snapshot if snapshot is None else snapshot
        _, timestamp = speed_snapshot
        if timestamp is None:
            return True
        age = (self._monotonic() if reference_time_s is None else reference_time_s) - timestamp
        return age > policy.stale_timeout_s

    def fallback_speed_value(
        self,
        *,
        snapshot: SpeedResolutionPolicySnapshot | None = None,
    ) -> float | None:
        policy = self._snapshot if snapshot is None else snapshot
        if isinstance(policy.override_speed_mps, NUMERIC_TYPES) and not isinstance(
            policy.override_speed_mps, bool
        ):
            override_speed = policy.override_speed_mps
            if override_speed is not None:
                return float(override_speed)
        return None

    def set_speed_override_kmh(self, speed_kmh: float | None) -> float | None:
        override_speed_mps, applied_speed_kmh = self._normalized_override_speed_kmh(speed_kmh)
        self._replace_snapshot(override_speed_mps=override_speed_mps)
        return applied_speed_kmh

    def set_manual_source_selected(self, selected: bool) -> None:
        self._replace_snapshot(manual_source_selected=bool(selected))

    def set_fallback_settings(
        self,
        stale_timeout_s: float | None = None,
        **_kwargs: object,
    ) -> None:
        if stale_timeout_s is not None:
            self._replace_snapshot(stale_timeout_s=self._normalized_stale_timeout(stale_timeout_s))
