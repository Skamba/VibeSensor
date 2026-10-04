from __future__ import annotations

import asyncio
from urllib.error import URLError

from vibesensor.simulator.server_http import set_server_speed_override_kmh
from vibesensor.simulator.sim_client import SimClient

__all__ = ["apply_scripted_speed", "speed_sync_failure_message"]


def speed_sync_failure_message(exc: URLError | OSError | TimeoutError | ValueError) -> str:
    return f"[scenario] speed sync HTTP update failed, retrying: {type(exc).__name__}: {exc}"


async def apply_scripted_speed(
    clients: list[SimClient],
    speed_kmh: float,
    *,
    server_host: str,
    server_http_port: int,
    server_check_timeout: float,
    gps_feed: bool,
) -> str | None:
    """Set the scripted speed on every client and, unless a GPS feed reports it, type it in.

    With *gps_feed* the simulated GPS receiver reports the clients' speed, so
    nothing is sent. Otherwise returns a failure message when the server's
    manual-speed update failed. Callers retry on
    their next tick: the simulated tones always follow the scripted speed, so
    giving up after one slow response would leave the server analysing them
    against a frozen speed for the rest of the scenario.
    """
    for client in clients:
        client.current_speed_kmh = speed_kmh
    if gps_feed:
        return None
    try:
        await asyncio.to_thread(
            set_server_speed_override_kmh,
            server_host,
            server_http_port,
            speed_kmh,
            server_check_timeout,
        )
    except (URLError, OSError, TimeoutError, ValueError) as exc:
        return speed_sync_failure_message(exc)
    return None
