"""Status-presentation helpers for GPS speed monitoring."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from vibesensor.adapters.gps.speed_resolution import SpeedResolution
from vibesensor.shared.constants import MPS_TO_KMH, NUMERIC_TYPES
from vibesensor.shared.types.speed_source_config import ResolvedSpeedSource

_GPS_MAX_EPH_M: float = 40.0


@dataclass(frozen=True)
class GPSSpeedStatusState:
    """Immutable transport/policy snapshot for JSON status presentation."""

    gps_enabled: bool
    connection_state: str
    device_info: str | None
    last_fix_mode: int | None
    last_epx_m: float | None
    last_epy_m: float | None
    last_epv_m: float | None
    raw_speed_mps: float | None
    last_update_ts: float | None
    last_error: str | None
    current_reconnect_delay: float
    stale_timeout_s: float


@dataclass(frozen=True, slots=True)
class SpeedSourceStatusSnapshot:
    """Typed GPS/speed-source status snapshot returned inside the runtime."""

    gps_enabled: bool
    connection_state: str
    device: str | None
    fix_mode: int | None
    fix_dimension: Literal["3d", "2d", "none"]
    speed_confidence: Literal["low", "medium", "high"]
    epx_m: float | None
    epy_m: float | None
    epv_m: float | None
    last_update_age_s: float | None
    raw_speed_kmh: float | None
    effective_speed_kmh: float | None
    last_error: str | None
    reconnect_delay_s: float | None
    fallback_active: bool
    speed_source: ResolvedSpeedSource
    stale_timeout_s: float


def speed_confidence(
    last_fix_mode: int | None,
    last_epx_m: float | None,
    last_epy_m: float | None,
) -> Literal["low", "medium", "high"]:
    if not isinstance(last_fix_mode, int) or last_fix_mode < 2:
        return "low"
    if last_fix_mode >= 3:
        return "high"
    if last_epx_m is not None and last_epy_m is not None:
        if last_epx_m <= _GPS_MAX_EPH_M and last_epy_m <= _GPS_MAX_EPH_M:
            return "medium"
        return "low"
    return "low"


def build_status_snapshot(
    state: GPSSpeedStatusState,
    *,
    resolution: SpeedResolution,
    effective_connection_state: str,
    now_mono: float | None = None,
) -> SpeedSourceStatusSnapshot:
    now = time.monotonic() if now_mono is None else now_mono

    last_update_age_s: float | None = None
    if state.last_update_ts is not None:
        last_update_age_s = round(now - state.last_update_ts, 2)

    raw_speed_kmh: float | None = None
    if isinstance(state.raw_speed_mps, NUMERIC_TYPES) and not isinstance(state.raw_speed_mps, bool):
        raw_speed_kmh = round(float(state.raw_speed_mps) * MPS_TO_KMH, 2)

    effective_speed_kmh: float | None = None
    if isinstance(resolution.speed_mps, NUMERIC_TYPES) and not isinstance(
        resolution.speed_mps, bool
    ):
        effective_speed_kmh = round(float(resolution.speed_mps) * MPS_TO_KMH, 2)

    return SpeedSourceStatusSnapshot(
        gps_enabled=state.gps_enabled,
        connection_state=effective_connection_state,
        device=state.device_info,
        fix_mode=state.last_fix_mode,
        fix_dimension=(
            "3d"
            if isinstance(state.last_fix_mode, int) and state.last_fix_mode >= 3
            else "2d"
            if state.last_fix_mode == 2
            else "none"
        ),
        speed_confidence=speed_confidence(
            state.last_fix_mode,
            state.last_epx_m,
            state.last_epy_m,
        ),
        epx_m=state.last_epx_m,
        epy_m=state.last_epy_m,
        epv_m=state.last_epv_m,
        last_update_age_s=last_update_age_s,
        raw_speed_kmh=raw_speed_kmh,
        effective_speed_kmh=effective_speed_kmh,
        last_error=state.last_error,
        reconnect_delay_s=(
            round(state.current_reconnect_delay, 1)
            if effective_connection_state == "disconnected"
            else None
        ),
        fallback_active=resolution.fallback_active,
        speed_source=resolution.source,
        stale_timeout_s=state.stale_timeout_s,
    )
