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
        # True means manual is the selected primary source.
        # False means GPS is primary and manual is fallback-only.
        self.manual_source_selected: bool = False

        # --- status tracking ---
        self.connection_state: str = "disabled" if not gps_enabled else "disconnected"
        self.last_update_ts: float | None = None
        self.last_error: str | None = None
        self.current_reconnect_delay: float = _GPS_RECONNECT_DELAY_S
        self.device_info: str | None = None

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
        if self.manual_source_selected:
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
    def _has_good_3d_fix(payload: dict[str, Any]) -> bool:
        mode = payload.get("mode")
        if not isinstance(mode, int) or mode < 3:
            return False

        eph = payload.get("eph")
        if isinstance(eph, (int, float)) and math.isfinite(eph) and eph > _GPS_MAX_EPH_M:
            return False

        eps = payload.get("eps")
        if isinstance(eps, (int, float)) and math.isfinite(eps) and eps > _GPS_MAX_EPS_MPS:
            return False

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
                    has_3d_fix = self._has_good_3d_fix(payload)
                    speed = payload.get("speed")
                    if (
                        has_3d_fix
                        and isinstance(speed, (int, float))
                        and math.isfinite(speed)
                        and speed >= 0
                    ):
                        self.speed_mps = float(speed)
                        self.last_update_ts = time.monotonic()
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
