from __future__ import annotations

import asyncio
from dataclasses import dataclass
from urllib.error import URLError

from vibesensor.adapters.simulator.server_http import set_server_speed_override_kmh
from vibesensor.adapters.simulator.sim_client import SimClient

__all__ = ["ScriptedSpeedSyncResult", "apply_scripted_speed", "speed_sync_disable_message"]


@dataclass(frozen=True, slots=True)
class ScriptedSpeedSyncResult:
    server_speed_sync_enabled: bool
    failure_message: str | None = None


def speed_sync_disable_message(exc: URLError | OSError | TimeoutError | ValueError) -> str:
    return f"[scenario] speed sync disabled after HTTP update failed: {type(exc).__name__}: {exc}"


async def apply_scripted_speed(
    clients: list[SimClient],
    speed_kmh: float,
    *,
    server_host: str,
    server_http_port: int,
    server_check_timeout: float,
    server_speed_sync_enabled: bool,
) -> ScriptedSpeedSyncResult:
    for client in clients:
        client.current_speed_kmh = speed_kmh
    if not server_speed_sync_enabled:
        return ScriptedSpeedSyncResult(server_speed_sync_enabled=False)
    try:
        await asyncio.to_thread(
            set_server_speed_override_kmh,
            server_host,
            server_http_port,
            speed_kmh,
            server_check_timeout,
        )
    except (URLError, OSError, TimeoutError, ValueError) as exc:
        return ScriptedSpeedSyncResult(
            server_speed_sync_enabled=False,
            failure_message=speed_sync_disable_message(exc),
        )
    return ScriptedSpeedSyncResult(server_speed_sync_enabled=True)
