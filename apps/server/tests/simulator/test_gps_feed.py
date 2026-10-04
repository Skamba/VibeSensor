from __future__ import annotations

import asyncio
import socket
from types import SimpleNamespace

import pytest
from test_support.polling import async_wait_until

from vibesensor.simulator.gps_feed import start_gps_feed
from vibesensor.speed.gps_speed import GPSSpeedMonitor


@pytest.mark.asyncio
async def test_the_server_reads_the_simulated_speed_as_a_3d_gps_fix() -> None:
    """The server's gpsd reader follows the simulated car's speed until the feed stops."""
    car = SimpleNamespace(current_speed_kmh=72.0)
    stop = asyncio.Event()
    feed = await start_gps_feed([car], "127.0.0.1", 0, stop)  # type: ignore[list-item]
    port = feed.sockets[0].getsockname()[1]
    monitor = GPSSpeedMonitor(gps_enabled=True)
    reader = asyncio.create_task(monitor.run(port=port))
    try:
        assert await async_wait_until(lambda: monitor.speed_mps == pytest.approx(20.0), 5.0)
        assert monitor.last_fix_mode == 3
        car.current_speed_kmh = 36.0
        assert await async_wait_until(lambda: monitor.speed_mps == pytest.approx(10.0), 5.0)
        stop.set()
        assert await async_wait_until(lambda: monitor.connection_state != "connected", 5.0)
    finally:
        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)
        feed.close()
        await feed.wait_closed()


async def test_the_feed_serves_a_port_a_test_harness_holds_between_runs() -> None:
    """A bound, never-listening SO_REUSEPORT socket keeps others off the port, not the feed."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
        held.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        held.bind(("127.0.0.1", 0))
        port = held.getsockname()[1]
        stop = asyncio.Event()
        car = SimpleNamespace(current_speed_kmh=72.0)
        feed = await start_gps_feed([car], "127.0.0.1", port, stop)  # type: ignore[list-item]
        try:
            for _ in range(10):
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                assert b"VERSION" in await asyncio.wait_for(reader.readline(), 5)
                writer.close()
        finally:
            stop.set()
            feed.close()
            await feed.wait_closed()
