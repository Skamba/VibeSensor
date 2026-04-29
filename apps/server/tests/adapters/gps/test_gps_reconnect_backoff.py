"""Behavior tests for GPS reconnect backoff and device-info capture."""

from __future__ import annotations

import asyncio

import pytest
from test_support.core import async_wait_until

from vibesensor.adapters.gps.gps_speed import GPSSpeedMonitor
from vibesensor.adapters.gps.transport_lifecycle import (
    GPS_RECONNECT_DELAY_S,
    GPS_RECONNECT_MAX_DELAY_S,
)


class TestGPSReconnectBackoff:
    """Cover reconnect delay growth/capping and VERSION-message device-info capture."""

    @pytest.mark.asyncio
    async def test_reconnect_delay_doubles_and_caps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monitor = GPSSpeedMonitor(gps_enabled=True)
        delays_seen: list[float] = []

        connect_count = 0

        async def _mock_open_connection(host, port):
            nonlocal connect_count
            connect_count += 1
            delays_seen.append(monitor.current_reconnect_delay)
            if connect_count >= 5:
                raise asyncio.CancelledError()
            raise ConnectionRefusedError("test")

        original_sleep = asyncio.sleep

        async def _fast_sleep(delay):
            await original_sleep(0)

        monkeypatch.setattr(asyncio, "open_connection", _mock_open_connection)
        monkeypatch.setattr(asyncio, "sleep", _fast_sleep)

        with pytest.raises(asyncio.CancelledError):
            await monitor.run(host="127.0.0.1", port=29470)

        assert delays_seen[0] == GPS_RECONNECT_DELAY_S
        for i in range(1, min(3, len(delays_seen))):
            assert delays_seen[i] >= delays_seen[i - 1]
        for delay in delays_seen:
            assert delay <= GPS_RECONNECT_MAX_DELAY_S

    @pytest.mark.asyncio
    async def test_version_message_sets_device_info(self) -> None:
        monitor = GPSSpeedMonitor(gps_enabled=True)

        async def _handler(reader, writer):
            await reader.readline()
            writer.write(b'{"class":"VERSION","rev":"3.25"}\n')
            await writer.drain()
            writer.write(b'{"class":"TPV","mode":3,"speed":10.0}\n')
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(_handler, host="127.0.0.1", port=0)
        host, port = server.sockets[0].getsockname()[:2]

        task = asyncio.create_task(monitor.run(host=host, port=port))
        assert await async_wait_until(
            lambda: monitor.device_info == "gpsd 3.25" and monitor.speed_mps == 10.0,
            timeout_s=1.5,
        ), "Timed out waiting for GPS VERSION and TPV messages to update monitor state"
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        server.close()
        await server.wait_closed()

        assert monitor.device_info is not None
        assert "3.25" in monitor.device_info
