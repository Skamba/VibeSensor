from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from typing import Any

from .constants import KMH_TO_MPS, MPS_TO_KMH

LOGGER = logging.getLogger(__name__)

_GPS_DISABLED_POLL_S: float = 5.0
"""Sleep interval when GPS is disabled."""

_GPS_RECONNECT_DELAY_S: float = 2.0
"""Delay before reconnecting after a GPS connection loss."""

_GPS_CONNECT_TIMEOUT_S: float = 3.0
_GPS_READ_TIMEOUT_S: float = 3.0
_GPS_RECONNECT_MAX_DELAY_S: float = 15.0

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

        # --- fallback ---
        self.stale_timeout_s: float = DEFAULT_STALE_TIMEOUT_S
        self.fallback_mode: str = DEFAULT_FALLBACK_MODE
        self.fallback_active: bool = False

    @property
    def effective_speed_mps(self) -> float | None:
        if self.manual_source_selected is None:
            if isinstance(self.override_speed_mps, (int, float)):
                return float(self.override_speed_mps)
        elif self.manual_source_selected is True:
            self.fallback_active = False
            if isinstance(self.override_speed_mps, (int, float)):
                return float(self.override_speed_mps)
            return None
        # Check if GPS is fresh
        if isinstance(self.speed_mps, (int, float)):
            if self._is_gps_stale():
                # GPS data exists but is stale → activate fallback
                return self._fallback_speed_mps()
            self.fallback_active = False
            return float(self.speed_mps)
        # No GPS data at all → check if fallback should kick in
        if self.gps_enabled and self.connection_state in ("disconnected", "stale"):
            return self._fallback_speed_mps()
        return None

    def _is_gps_stale(self) -> bool:
        """Check if the last GPS update is older than the configured stale timeout."""
        if self.last_update_ts is None:
            return True
        age = time.monotonic() - self.last_update_ts
        return age > self.stale_timeout_s

    def _fallback_speed_mps(self) -> float | None:
        """Return fallback speed (manual override) if fallback mode is manual."""
        if self.fallback_mode == "manual" and isinstance(self.override_speed_mps, (int, float)):
            self.fallback_active = True
            return float(self.override_speed_mps)
        self.fallback_active = True
        return None

    def set_speed_override_kmh(self, speed_kmh: float | None) -> float | None:
        if speed_kmh is None:
            self.override_speed_mps = None
            return None
        speed_val = max(0.0, float(speed_kmh))
        if speed_val <= 0:
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

    def status_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable status snapshot for the API."""
        now = time.monotonic()
        # Refresh stale state
        if self.gps_enabled and self.connection_state == "connected":
            if self._is_gps_stale():
                self.connection_state = "stale"

        last_update_age_s: float | None = None
        if self.last_update_ts is not None:
            last_update_age_s = round(now - self.last_update_ts, 2)

        raw_speed_kmh: float | None = None
        if isinstance(self.speed_mps, (int, float)):
            raw_speed_kmh = round(float(self.speed_mps) * MPS_TO_KMH, 2)

        effective = self.effective_speed_mps
        effective_speed_kmh: float | None = None
        if isinstance(effective, (int, float)):
            effective_speed_kmh = round(float(effective) * MPS_TO_KMH, 2)

        return {
            "gps_enabled": self.gps_enabled,
            "connection_state": self.connection_state,
            "device": self.device_info,
            "last_update_age_s": last_update_age_s,
            "raw_speed_kmh": raw_speed_kmh,
            "effective_speed_kmh": effective_speed_kmh,
            "last_error": self.last_error,
            "reconnect_delay_s": (
                round(self.current_reconnect_delay, 1)
                if self.connection_state == "disconnected"
                else None
            ),
            "fallback_active": self.fallback_active,
            "stale_timeout_s": self.stale_timeout_s,
            "fallback_mode": self.fallback_mode,
        }

    async def run(self, host: str = "127.0.0.1", port: int = 2947) -> None:
        reconnect_delay = _GPS_RECONNECT_DELAY_S
        while True:
            if not self.gps_enabled:
                self.speed_mps = None
                self.connection_state = "disabled"
                self.fallback_active = False
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
                    speed = payload.get("speed")
                    if isinstance(speed, (int, float)) and math.isfinite(speed) and speed >= 0:
                        self.speed_mps = float(speed)
                        self.last_update_ts = time.monotonic()
                        self.fallback_active = False
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
            except Exception as exc:
                self.speed_mps = None
                self.connection_state = "disconnected"
                self.last_error = str(exc) or type(exc).__name__
                self.current_reconnect_delay = reconnect_delay
                LOGGER.debug("GPS connection lost, retrying in %gs", reconnect_delay)
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(_GPS_RECONNECT_MAX_DELAY_S, reconnect_delay * 2.0)
            finally:
                if writer is not None and not writer_closed:
                    writer.close()
                    await writer.wait_closed()
