from __future__ import annotations

import asyncio
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
