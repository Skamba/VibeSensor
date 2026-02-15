from __future__ import annotations

import asyncio
import json
from typing import Any


class GPSSpeedMonitor:
    def __init__(self, gps_enabled: bool):
        self.gps_enabled = gps_enabled
        self.speed_mps: float | None = None
        self.override_speed_mps: float | None = None

    @property
    def effective_speed_mps(self) -> float | None:
        if isinstance(self.speed_mps, (int, float)):
            return float(self.speed_mps)
        if isinstance(self.override_speed_mps, (int, float)):
            return float(self.override_speed_mps)
        return None

    def set_speed_override_kmh(self, speed_kmh: float | None) -> float | None:
        if speed_kmh is None:
            self.override_speed_mps = None
            return None
        speed_val = max(0.0, float(speed_kmh))
        if speed_val <= 0:
            self.override_speed_mps = None
            return None
        self.override_speed_mps = speed_val / 3.6
        return speed_val

    async def run(self, host: str = "127.0.0.1", port: int = 2947) -> None:
        while True:
            if not self.gps_enabled:
                self.speed_mps = None
                await asyncio.sleep(5.0)
                continue

            try:
                reader, writer = await asyncio.open_connection(host, port)
                writer.write(b'?WATCH={"enable":true,"json":true};\n')
                await writer.drain()
                while True:
                    line = await reader.readline()
                    if not line:
                        break
                    try:
                        payload: dict[str, Any] = json.loads(line.decode("utf-8", errors="replace"))
                    except json.JSONDecodeError:
                        continue
                    if payload.get("class") != "TPV":
                        continue
                    speed = payload.get("speed")
                    if isinstance(speed, (int, float)):
                        self.speed_mps = float(speed)
                writer.close()
                await writer.wait_closed()
            except OSError:
                self.speed_mps = None
                await asyncio.sleep(2.0)
