from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from .constants import KMH_TO_MPS

LOGGER = logging.getLogger(__name__)

_GPS_DISABLED_POLL_S: float = 5.0
"""Sleep interval when GPS is disabled."""

_GPS_RECONNECT_DELAY_S: float = 2.0
"""Delay before reconnecting after a GPS connection loss."""

_GPS_CONNECT_TIMEOUT_S: float = 3.0
_GPS_READ_TIMEOUT_S: float = 3.0
_GPS_RECONNECT_MAX_DELAY_S: float = 15.0


class GPSSpeedMonitor:
    def __init__(self, gps_enabled: bool):
        self.gps_enabled = gps_enabled
        self.speed_mps: float | None = None
        self.override_speed_mps: float | None = None

    @property
    def effective_speed_mps(self) -> float | None:
        if isinstance(self.override_speed_mps, (int, float)):
            return float(self.override_speed_mps)
        if isinstance(self.speed_mps, (int, float)):
            return float(self.speed_mps)
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

    async def run(self, host: str = "127.0.0.1", port: int = 2947) -> None:
        reconnect_delay = _GPS_RECONNECT_DELAY_S
        while True:
            if not self.gps_enabled:
                self.speed_mps = None
                await asyncio.sleep(_GPS_DISABLED_POLL_S)
                continue

            writer: asyncio.StreamWriter | None = None
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=_GPS_CONNECT_TIMEOUT_S,
                )
                writer.write(b'?WATCH={"enable":true,"json":true};\n')
                await writer.drain()
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
                        continue
                    speed = payload.get("speed")
                    if isinstance(speed, (int, float)):
                        self.speed_mps = float(speed)
                reconnect_delay = _GPS_RECONNECT_DELAY_S
            except asyncio.CancelledError:
                if writer is not None:
                    writer.close()
                raise
            except Exception:
                self.speed_mps = None
                LOGGER.debug("GPS connection lost, retrying in %gs", reconnect_delay)
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(_GPS_RECONNECT_MAX_DELAY_S, reconnect_delay * 2.0)
            finally:
                if writer is not None:
                    writer.close()
                    await writer.wait_closed()
