"""GPS speed monitor — tracks current vehicle speed from NMEA sentences.

``GPSSpeedMonitor`` parses GPVTG/GPRMC sentences from a serial GPS device
and exposes the current speed in m/s with a configurable resolution window.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from typing import Literal, NamedTuple

from vibesensor.shared.types.backend_types import FallbackMode, ResolvedSpeedSource
from vibesensor.shared.constants import KMH_TO_MPS, MPS_TO_KMH, NUMERIC_TYPES
from vibesensor.shared.types.json_types import JsonObject, is_json_object


class SpeedResolution(NamedTuple):
    """Immutable snapshot of the resolved speed state — no side effects."""

    speed_mps: float | None
    fallback_active: bool
    source: ResolvedSpeedSource


LOGGER = logging.getLogger(__name__)

__all__ = ["GPSSpeedMonitor", "SpeedResolution"]

_GPS_DISABLED_POLL_S: float = 5.0
"""Sleep interval when GPS is disabled."""

_GPS_RECONNECT_DELAY_S: float = 2.0
"""Delay before reconnecting after a GPS connection loss."""

_GPS_CONNECT_TIMEOUT_S: float = 3.0
_GPS_READ_TIMEOUT_S: float = 3.0
_GPS_RECONNECT_MAX_DELAY_S: float = 15.0
_GPS_MAX_EPH_M: float = 40.0
_GPS_ZERO_DROP_PREV_THRESHOLD_MPS: float = 0.5
_GPS_ZERO_CONFIRM_SAMPLES: int = 3

# Fallback defaults
DEFAULT_STALE_TIMEOUT_S: float = 10.0
MIN_STALE_TIMEOUT_S: float = 3.0
MAX_STALE_TIMEOUT_S: float = 120.0
VALID_FALLBACK_MODES: frozenset[str] = frozenset({"manual"})
"""Use frozenset so ``in`` membership tests are O(1) and the set is immutable."""
DEFAULT_FALLBACK_MODE: FallbackMode = "manual"

# Speed plausibility limits
_GPS_MAX_SPEED_MPS: float = 150.0
"""Reject GPS TPV speed samples above this value (≈ 540 km/h) as implausible."""
MAX_MANUAL_SPEED_KMH: float = 500.0
"""Upper bound for manually supplied speed overrides."""


def _is_numeric(value: object) -> bool:
    """Return True if *value* is int/float but **not** bool (bool ⊂ int)."""
    return isinstance(value, NUMERIC_TYPES) and not isinstance(value, bool)


class GPSSpeedMonitor:
    """Monitors GPS speed over a serial connection and exposes it via ``speed_mps``."""

    def __init__(self, gps_enabled: bool):
        """Initialise the GPS speed monitor with the given enabled flag."""
        self.gps_enabled = gps_enabled
        self.override_speed_mps: float | None = None
        self.manual_source_selected: bool = True

        # --- status tracking ---
        self.connection_state: str = "disabled" if not gps_enabled else "disconnected"
        # Atomic (speed, timestamp) snapshot: both fields are always written
        # together so cross-thread readers never see a torn state.
        # The ``speed_mps`` property reads/writes this tuple so the two
        # representations can never diverge.
        self._speed_snapshot: tuple[float | None, float | None] = (None, None)
        self.last_error: str | None = None
        self.current_reconnect_delay: float = _GPS_RECONNECT_DELAY_S
        self.device_info: str | None = None
        self.last_fix_mode: int | None = None
        self.last_epx_m: float | None = None
        self.last_epy_m: float | None = None
        self.last_epv_m: float | None = None
        self._zero_speed_streak: int = 0

        # --- fallback ---
        self.stale_timeout_s: float = DEFAULT_STALE_TIMEOUT_S
        self.fallback_mode: FallbackMode = DEFAULT_FALLBACK_MODE

    @property
    def speed_mps(self) -> float | None:
        """Current GPS speed from the atomic snapshot."""
        return self._speed_snapshot[0]

    @speed_mps.setter
    def speed_mps(self, value: float | None) -> None:
        """Set GPS speed, preserving the existing timestamp."""
        self._speed_snapshot = (value, self._speed_snapshot[1])

    # ------------------------------------------------------------------
    # Speed resolution — pure computation, no side effects
    # ------------------------------------------------------------------

    def resolve_speed(self) -> SpeedResolution:
        """Return a consistent (speed, fallback_active, source) snapshot.

        This method is **pure**: it never mutates instance state.  All
        consumers should prefer this over reading ``effective_speed_mps``
        and ``fallback_active`` separately when they need both values.
        """
        if self.manual_source_selected and _is_numeric(self.override_speed_mps):
            # _is_numeric() excludes bool to prevent accidental bool→speed coercion.
            override_speed = self.override_speed_mps
            if override_speed is not None:
                return SpeedResolution(float(override_speed), False, "manual")
        # Manual selected but no override set → fall through to GPS

        # Read from the atomic (speed, timestamp) snapshot so the speed value
        # and the staleness check are always consistent with each other.
        _speed, _ts = self._speed_snapshot
        if isinstance(_speed, NUMERIC_TYPES):
            if self._is_gps_stale():
                fb = self._fallback_speed_value()
                return SpeedResolution(fb, True, "fallback_manual" if fb is not None else "none")
            return SpeedResolution(float(_speed), False, "gps")  # type: ignore[arg-type]

        # No GPS data at all → check if fallback should kick in
        eff_conn = self._effective_connection_state()
        if self.gps_enabled and eff_conn in ("disconnected", "stale"):
            fb = self._fallback_speed_value()
            return SpeedResolution(fb, True, "fallback_manual" if fb is not None else "none")

        return SpeedResolution(None, False, "none")

    @property
    def effective_speed_mps(self) -> float | None:
        """Convenience property — delegates to :meth:`resolve_speed`."""
        return self.resolve_speed().speed_mps

    @property
    def fallback_active(self) -> bool:
        """Whether the current effective speed uses a fallback source.

        Computed from :meth:`resolve_speed`; never stale.
        """
        return self.resolve_speed().fallback_active

    @property
    def last_update_ts(self) -> float | None:
        """Read timestamp from the atomic snapshot."""
        return self._speed_snapshot[1]

    @last_update_ts.setter
    def last_update_ts(self, value: float | None) -> None:
        """Write timestamp via legacy setter — preserves current speed."""
        self._speed_snapshot = (self._speed_snapshot[0], value)

    def _effective_connection_state(self) -> str:
        """Return the effective connection state **without** mutating ``self``."""
        if self.gps_enabled and self.connection_state == "connected" and self._is_gps_stale():
            return "stale"
        return self.connection_state

    def _is_gps_stale(self) -> bool:
        """Check if the last GPS update is older than the configured stale timeout."""
        _speed, ts = self._speed_snapshot  # atomic tuple read
        if ts is None:
            return True
        age = time.monotonic() - ts
        return age > self.stale_timeout_s

    def _fallback_speed_value(self) -> float | None:
        """Return fallback speed if available — **no side effects**."""
        # _is_numeric() excludes bool to match the guard in resolve_speed().
        if self.fallback_mode == "manual" and _is_numeric(self.override_speed_mps):
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
        fallback_mode: str | None = None,
    ) -> None:
        """Update fallback settings at runtime."""
        if stale_timeout_s is not None:
            self.stale_timeout_s = max(
                MIN_STALE_TIMEOUT_S,
                min(MAX_STALE_TIMEOUT_S, float(stale_timeout_s)),
            )
        if fallback_mode is not None:
            if fallback_mode in VALID_FALLBACK_MODES:
                self.fallback_mode = "manual"
            else:
                LOGGER.warning(
                    "Ignoring unknown fallback_mode %r; valid values: %s",
                    fallback_mode,
                    sorted(VALID_FALLBACK_MODES),
                )

    @staticmethod
    def _read_non_negative_metric(payload: JsonObject, field: str) -> float | None:
        value = payload.get(field)
        if isinstance(value, NUMERIC_TYPES) and not isinstance(value, bool):
            numeric_value = float(value)  # type: ignore[arg-type]
            if math.isfinite(numeric_value) and numeric_value >= 0:
                return numeric_value
        return None

    @staticmethod
    def _tpv_mode(payload: JsonObject) -> int | None:
        mode = payload.get("mode")
        if isinstance(mode, int) and not isinstance(mode, bool):
            return mode
        return None

    def _speed_confidence(self) -> Literal["low", "medium", "high"]:
        mode = self.last_fix_mode
        if not isinstance(mode, int) or mode < 2:
            return "low"
        if mode >= 3:
            return "high"
        if self.last_epx_m is not None and self.last_epy_m is not None:
            if self.last_epx_m <= _GPS_MAX_EPH_M and self.last_epy_m <= _GPS_MAX_EPH_M:
                return "medium"
            return "low"
        # 2-D fix but no horizontal-error estimate — quality is unconfirmed.
        return "low"

    def _accept_speed_sample(self, speed_mps: float) -> bool:
        if speed_mps == 0.0:
            prev_speed = self._speed_snapshot[0]  # direct tuple read
            if (
                isinstance(prev_speed, NUMERIC_TYPES)
                and prev_speed > _GPS_ZERO_DROP_PREV_THRESHOLD_MPS  # type: ignore[operator]
            ):
                self._zero_speed_streak += 1
                return self._zero_speed_streak >= _GPS_ZERO_CONFIRM_SAMPLES
        self._zero_speed_streak = 0
        return True

    def _reset_fix_metadata(self) -> None:
        """Clear stale fix-quality fields when GPS disconnects.

        Prevents the status dict from showing contradictory state like
        connection_state="disconnected" + fix_dimension="3d" or a stale
        device name that no longer reflects the active connection.
        """
        self.last_fix_mode = None
        self.last_epx_m = None
        self.last_epy_m = None
        self.last_epv_m = None
        self._zero_speed_streak = 0
        self._speed_snapshot = (None, None)
        self.device_info = None

    def status_dict(self) -> dict[str, object]:
        """Return a JSON-serializable status snapshot — **no side effects**."""
        now = time.monotonic()
        # Use a single resolve_speed() call for a consistent snapshot.
        resolution = self.resolve_speed()
        conn_state = self._effective_connection_state()

        # Read the atomic snapshot once; avoids repeated property access.
        raw_speed, last_ts = self._speed_snapshot

        last_update_age_s: float | None = None
        if last_ts is not None:
            last_update_age_s = round(now - last_ts, 2)

        raw_speed_kmh: float | None = None
        if isinstance(raw_speed, NUMERIC_TYPES):
            raw_speed_kmh = round(raw_speed * MPS_TO_KMH, 2)  # type: ignore[operator]

        effective_speed_kmh: float | None = None
        if isinstance(resolution.speed_mps, NUMERIC_TYPES):
            effective_speed_kmh = round(resolution.speed_mps * MPS_TO_KMH, 2)  # type: ignore[operator]

        return {
            "gps_enabled": self.gps_enabled,
            "connection_state": conn_state,
            "device": self.device_info,
            "fix_mode": self.last_fix_mode,
            "fix_dimension": (
                "3d"
                if isinstance(self.last_fix_mode, int) and self.last_fix_mode >= 3
                else "2d"
                if self.last_fix_mode == 2
                else "none"
            ),
            "speed_confidence": self._speed_confidence(),
            "epx_m": self.last_epx_m,
            "epy_m": self.last_epy_m,
            "epv_m": self.last_epv_m,
            "last_update_age_s": last_update_age_s,
            "raw_speed_kmh": raw_speed_kmh,
            "effective_speed_kmh": effective_speed_kmh,
            "last_error": self.last_error,
            "reconnect_delay_s": (
                round(self.current_reconnect_delay, 1) if conn_state == "disconnected" else None
            ),
            "fallback_active": resolution.fallback_active,
            "speed_source": resolution.source,
            "stale_timeout_s": self.stale_timeout_s,
            "fallback_mode": self.fallback_mode,
        }

    async def run(self, host: str = "127.0.0.1", port: int = 2947) -> None:
        # Local-bind hot-loop functions to avoid repeated attribute lookups.
        _loads = json.loads
        _isfinite = math.isfinite
        _monotonic = time.monotonic
        _is_num = _is_numeric
        _read_metric = self._read_non_negative_metric
        _tpv = self._tpv_mode

        reconnect_delay = _GPS_RECONNECT_DELAY_S
        while True:
            if not self.gps_enabled:
                self.speed_mps = None
                self.connection_state = "disabled"
                await asyncio.sleep(_GPS_DISABLED_POLL_S)
                continue

            writer: asyncio.StreamWriter | None = None
            writer_closed = False
            try:
                self.connection_state = "disconnected"
                reader, connected_writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=_GPS_CONNECT_TIMEOUT_S,
                )
                writer = connected_writer
                writer.write(b'?WATCH={"enable":true,"json":true};\n')
                await writer.drain()
                self.connection_state = "connected"
                self.last_error = None
                # Reset reconnect delay so status_dict shows the initial value
                # after a successful connection, not the last back-off delay.
                self.current_reconnect_delay = _GPS_RECONNECT_DELAY_S
                reconnect_delay = _GPS_RECONNECT_DELAY_S
                while True:
                    line = await asyncio.wait_for(reader.readline(), timeout=_GPS_READ_TIMEOUT_S)
                    if not line:
                        self.speed_mps = None
                        self.connection_state = "disconnected"
                        self._reset_fix_metadata()
                        break
                    try:
                        _parsed = _loads(line.decode("utf-8", errors="replace"))
                    except json.JSONDecodeError:
                        LOGGER.debug("Ignoring malformed GPS JSON line")
                        continue
                    if not is_json_object(_parsed):
                        LOGGER.debug("Ignoring non-object GPS JSON line")
                        continue
                    payload: JsonObject = _parsed
                    if payload.get("class") != "TPV":
                        # Extract device info from VERSION messages
                        if payload.get("class") == "VERSION":
                            rev = payload.get("rev")
                            if isinstance(rev, str):
                                self.device_info = f"gpsd {rev}"
                        continue
                    mode = _tpv(payload)
                    self.last_fix_mode = mode
                    self.last_epx_m = _read_metric(payload, "epx")
                    self.last_epy_m = _read_metric(payload, "epy")
                    self.last_epv_m = _read_metric(payload, "epv")
                    speed = payload.get("speed")
                    if (
                        isinstance(mode, int)
                        and mode >= 2
                        and isinstance(speed, NUMERIC_TYPES)
                        and not isinstance(speed, bool)
                    ):
                        speed_f = float(speed)  # type: ignore[arg-type]
                        if _isfinite(speed_f) and 0 <= speed_f <= _GPS_MAX_SPEED_MPS:
                            if self._accept_speed_sample(speed_f):
                                self._speed_snapshot = (speed_f, _monotonic())
                        else:
                            self._zero_speed_streak = 0
                    else:
                        self._zero_speed_streak = 0
                    # Extract device from TPV
                    device = payload.get("device")
                    if isinstance(device, str) and device:
                        self.device_info = device
                reconnect_delay = _GPS_RECONNECT_DELAY_S
            except asyncio.CancelledError:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
                    writer_closed = True
                self.speed_mps = None
                raise
            except (
                OSError,
                TimeoutError,
                ConnectionError,
                EOFError,
                json.JSONDecodeError,
            ) as exc:
                self.speed_mps = None
                self.connection_state = "disconnected"
                self._reset_fix_metadata()
                self.last_error = str(exc) or type(exc).__name__
                self.current_reconnect_delay = reconnect_delay
                LOGGER.warning(
                    "GPS connection lost, retrying in %gs: %s",
                    reconnect_delay,
                    exc,
                    exc_info=True,
                )
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(_GPS_RECONNECT_MAX_DELAY_S, reconnect_delay * 2.0)
            finally:
                if writer is not None and not writer_closed:
                    writer.close()
                    await writer.wait_closed()
