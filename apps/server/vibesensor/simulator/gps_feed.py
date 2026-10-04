"""A simulated GPS receiver: serves the simulated car's speed over the gpsd protocol.

The server reads it like the Pi's gpsd (``gps.gpsd_port``), so a simulated drive
records a measured speed, as a real drive with a GPS receiver does.
"""

from __future__ import annotations

import asyncio
import contextlib
import json

from vibesensor.simulator.sim_client import SimClient

__all__ = ["start_gps_feed"]

_REPORT_INTERVAL_S = 0.2
_VERSION: dict[str, object] = {
    "class": "VERSION",
    "release": "vibesensor-sim",
    "rev": "vibesensor-sim",
}


def _line(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload) + "\n").encode("utf-8")


async def start_gps_feed(
    clients: list[SimClient], host: str, port: int, stop_event: asyncio.Event
) -> asyncio.Server:
    """Listen on *port*; each connection gets 3D-fix TPV reports at the clients' speed.

    Connections end when *stop_event* is set; the caller closes the returned server.
    """

    async def report(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            writer.write(_line(_VERSION))
            while not stop_event.is_set():
                speed_mps = clients[0].current_speed_kmh / 3.6
                writer.write(
                    _line({"class": "TPV", "device": "sim", "mode": 3, "speed": speed_mps})
                )
                await writer.drain()
                await asyncio.sleep(_REPORT_INTERVAL_S)
        except ConnectionError:
            pass
        finally:
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()

    # SO_REUSEPORT, like the server's own listener: a test harness can hold the
    # port for a run of simulators so no other process takes it in between.
    return await asyncio.start_server(report, host, port, reuse_port=True)
