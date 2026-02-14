from __future__ import annotations

import asyncio
import json
from typing import Any


class GPSSpeedMonitor:
    def __init__(self, gps_enabled: bool):
        self.gps_enabled = gps_enabled
        self.speed_mps: float | None = None

    async def _probe_gpsd(self, host: str, port: int) -> bool:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=1.0,
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (OSError, TimeoutError):
            return False

    async def run(self, host: str = "127.0.0.1", port: int = 2947) -> None:
        while True:
            if not self.gps_enabled:
                has_gpsd = await self._probe_gpsd(host, port)
                if not has_gpsd:
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
