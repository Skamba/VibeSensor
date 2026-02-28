from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from typing import Any, NamedTuple

from .constants import KMH_TO_MPS, MPS_TO_KMH


class SpeedResolution(NamedTuple):
    """Immutable snapshot of the resolved speed state — no side effects."""

    speed_mps: float | None
    fallback_active: bool
    source: str  # "manual", "gps", "fallback_manual", "none"


LOGGER = logging.getLogger(__name__)

_GPS_DISABLED_POLL_S: float = 5.0
"""Sleep interval when GPS is disabled."""

_GPS_RECONNECT_DELAY_S: float = 2.0
"""Delay before reconnecting after a GPS connection loss."""

_GPS_CONNECT_TIMEOUT_S: float = 3.0
_GPS_READ_TIMEOUT_S: float = 3.0
_GPS_RECONNECT_MAX_DELAY_S: float = 15.0
_GPS_MAX_EPH_M: float = 40.0
_GPS_MAX_EPS_MPS: float = 1.5
_GPS_ZERO_DROP_PREV_THRESHOLD_MPS: float = 0.5
_GPS_ZERO_CONFIRM_SAMPLES: int = 3

# Fallback defaults
DEFAULT_STALE_TIMEOUT_S: float = 10.0
MIN_STALE_TIMEOUT_S: float = 3.0
MAX_STALE_TIMEOUT_S: float = 120.0
VALID_FALLBACK_MODES: tuple[str, ...] = ("manual",)
DEFAULT_FALLBACK_MODE: str = "manual"


class GPSSpeedMonitor:
    def __init__(self, gps_enabled: bool):
        self.gps_enabled = gps_enabled
        self.speed_mps: float | None = None
        self.override_speed_mps: float | None = None
        # None keeps legacy behavior (override has top priority) for backwards
        # compatibility in isolated monitor usage/tests.
        # True means manual is the selected primary source.
        # False means GPS is primary and manual is fallback-only.
        self.manual_source_selected: bool | None = None

        # --- status tracking ---
        self.connection_state: str = "disabled" if not gps_enabled else "disconnected"
        self.last_update_ts: float | None = None
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
        self.fallback_mode: str = DEFAULT_FALLBACK_MODE

    # ------------------------------------------------------------------
    # Speed resolution — pure computation, no side effects
    # ------------------------------------------------------------------

    def resolve_speed(self) -> SpeedResolution:
        """Return a consistent (speed, fallback_active, source) snapshot.

        This method is **pure**: it never mutates instance state.  All
        consumers should prefer this over reading ``effective_speed_mps``
        and ``fallback_active`` separately when they need both values.
        """
        if self.manual_source_selected is None:
            # Legacy path: override has top priority
            if isinstance(self.override_speed_mps, (int, float)):
                return SpeedResolution(float(self.override_speed_mps), False, "manual")
        elif self.manual_source_selected is True:
            if isinstance(self.override_speed_mps, (int, float)):
                return SpeedResolution(float(self.override_speed_mps), False, "manual")
            # Manual selected but no override set → fall through to GPS

        # Check if GPS data exists and is fresh
        if isinstance(self.speed_mps, (int, float)):
            if self._is_gps_stale():
                fb = self._fallback_speed_value()
                return SpeedResolution(fb, True, "fallback_manual" if fb is not None else "none")
            return SpeedResolution(float(self.speed_mps), False, "gps")

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

    def _effective_connection_state(self) -> str:
        """Return the effective connection state **without** mutating ``self``."""
        if self.gps_enabled and self.connection_state == "connected" and self._is_gps_stale():
            return "stale"
        return self.connection_state

    def _is_gps_stale(self) -> bool:
        """Check if the last GPS update is older than the configured stale timeout."""
        if self.last_update_ts is None:
            return True
        age = time.monotonic() - self.last_update_ts
        return age > self.stale_timeout_s

    def _fallback_speed_value(self) -> float | None:
        """Return fallback speed if available — **no side effects**."""
        if self.fallback_mode == "manual" and isinstance(self.override_speed_mps, (int, float)):
            return float(self.override_speed_mps)
        return None

    def set_speed_override_kmh(self, speed_kmh: float | None) -> float | None:
        if speed_kmh is None:
            self.override_speed_mps = None
            return None
        speed_val = float(speed_kmh)
        if speed_val < 0 or not math.isfinite(speed_val):
            self.override_speed_mps = None
            return None
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
        if fallback_mode is not None and fallback_mode in VALID_FALLBACK_MODES:
            self.fallback_mode = fallback_mode

    @staticmethod
    def _read_non_negative_metric(payload: dict[str, Any], field: str) -> float | None:
        value = payload.get(field)
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value >= 0
        ):
            return float(value)
        return None

    @staticmethod
    def _tpv_mode(payload: dict[str, Any]) -> int | None:
        mode = payload.get("mode")
        if isinstance(mode, int) and not isinstance(mode, bool):
            return mode
        return None

    def _speed_confidence(self) -> str:
        mode = self.last_fix_mode
        if not isinstance(mode, int) or mode < 2:
            return "low"
        if mode >= 3:
            return "high"
        if self.last_epx_m is not None and self.last_epy_m is not None:
            if self.last_epx_m <= _GPS_MAX_EPH_M and self.last_epy_m <= _GPS_MAX_EPH_M:
                return "medium"
            return "low"
        return "medium"

    def _accept_speed_sample(self, speed_mps: float) -> bool:
        if speed_mps == 0.0:
            prev_speed = self.speed_mps
            if (
                isinstance(prev_speed, (int, float))
                and prev_speed > _GPS_ZERO_DROP_PREV_THRESHOLD_MPS
            ):
                self._zero_speed_streak += 1
                return self._zero_speed_streak >= _GPS_ZERO_CONFIRM_SAMPLES
        self._zero_speed_streak = 0
        return True

    def status_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable status snapshot — **no side effects**."""
        now = time.monotonic()
        # Use a single resolve_speed() call for a consistent snapshot.
        resolution = self.resolve_speed()
        conn_state = self._effective_connection_state()

        last_update_age_s: float | None = None
        if self.last_update_ts is not None:
            last_update_age_s = round(now - self.last_update_ts, 2)

        raw_speed_kmh: float | None = None
        if isinstance(self.speed_mps, (int, float)):
            raw_speed_kmh = round(float(self.speed_mps) * MPS_TO_KMH, 2)

        effective_speed_kmh: float | None = None
        if isinstance(resolution.speed_mps, (int, float)):
            effective_speed_kmh = round(float(resolution.speed_mps) * MPS_TO_KMH, 2)

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
            "stale_timeout_s": self.stale_timeout_s,
            "fallback_mode": self.fallback_mode,
        }

    async def run(self, host: str = "127.0.0.1", port: int = 2947) -> None:
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
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=_GPS_CONNECT_TIMEOUT_S,
                )
                writer.write(b'?WATCH={"enable":true,"json":true};\n')
                await writer.drain()
                self.connection_state = "connected"
                self.last_error = None
                while True:
                    line = await asyncio.wait_for(reader.readline(), timeout=_GPS_READ_TIMEOUT_S)
                    if not line:
                        self.speed_mps = None
                        self.connection_state = "disconnected"
                        break
                    try:
                        payload: dict[str, Any] = json.loads(line.decode("utf-8", errors="replace"))
                    except json.JSONDecodeError:
                        LOGGER.debug("Ignoring malformed GPS JSON line")
                        continue
                    if payload.get("class") != "TPV":
                        # Extract device info from VERSION messages
                        if payload.get("class") == "VERSION":
                            rev = payload.get("rev")
                            if isinstance(rev, str):
                                self.device_info = f"gpsd {rev}"
                        continue
                    mode = self._tpv_mode(payload)
                    self.last_fix_mode = mode
                    self.last_epx_m = self._read_non_negative_metric(payload, "epx")
                    self.last_epy_m = self._read_non_negative_metric(payload, "epy")
                    self.last_epv_m = self._read_non_negative_metric(payload, "epv")
                    speed = payload.get("speed")
                    if (
                        isinstance(mode, int)
                        and mode >= 2
                        and isinstance(speed, (int, float))
                        and not isinstance(speed, bool)
                        and math.isfinite(speed)
                        and speed >= 0
                    ):
                        speed_mps = float(speed)
                        if self._accept_speed_sample(speed_mps):
                            self.speed_mps = speed_mps
                            self.last_update_ts = time.monotonic()
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
            except (OSError, TimeoutError, ConnectionError) as exc:
                self.speed_mps = None
                self.connection_state = "disconnected"
                self.last_error = str(exc) or type(exc).__name__
                self.current_reconnect_delay = reconnect_delay
                LOGGER.warning("GPS connection lost, retrying in %gs", reconnect_delay)
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(_GPS_RECONNECT_MAX_DELAY_S, reconnect_delay * 2.0)
            finally:
                if writer is not None and not writer_closed:
                    writer.close()
                    await writer.wait_closed()
