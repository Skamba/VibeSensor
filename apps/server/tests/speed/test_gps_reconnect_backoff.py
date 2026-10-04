"""Behavior tests for GPS reconnect backoff and device-info capture."""

from __future__ import annotations

import asyncio

import pytest
from test_support.polling import async_wait_until

from vibesensor.speed.gps_speed import GPSSpeedMonitor
from vibesensor.speed.gps_transport_lifecycle import (
    GPS_RECONNECT_DELAY_S,
    GPS_RECONNECT_MAX_DELAY_S,
)


class TestGPSReconnectBackoff:
    """Cover reconnect delay growth/capping and VERSION-message device-info capture."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("error", "expected_delays"),
        [
            pytest.param(
                TimeoutError(),
                [
                    GPS_RECONNECT_DELAY_S,
                    GPS_RECONNECT_DELAY_S * 2,
                    GPS_RECONNECT_DELAY_S * 4,
                    GPS_RECONNECT_MAX_DELAY_S,
                ],
                id="timeout_doubles_and_caps",
            ),
            # Nothing listens yet: gpsd is picked up within the initial delay once it is back.
            pytest.param(
                ConnectionRefusedError("test"), [GPS_RECONNECT_DELAY_S] * 4, id="refused_retries"
            ),
        ],
    )
    async def test_reconnect_delay_after_failed_connects(
        self, monkeypatch: pytest.MonkeyPatch, error: OSError, expected_delays: list[float]
    ) -> None:
        monitor = GPSSpeedMonitor(gps_enabled=True)
        retry_delays: list[float] = []

        connect_count = 0

        async def _mock_open_connection(host, port):
            nonlocal connect_count
            connect_count += 1
            if connect_count >= 5:
                raise asyncio.CancelledError()
            raise error

        original_sleep = asyncio.sleep

        async def _fast_sleep(delay):
            retry_delays.append(delay)
            await original_sleep(0)

        monkeypatch.setattr(asyncio, "open_connection", _mock_open_connection)
        monkeypatch.setattr(asyncio, "sleep", _fast_sleep)

        with pytest.raises(asyncio.CancelledError):
            await monitor.run(host="127.0.0.1", port=29470)

        assert connect_count == 5
        assert retry_delays == expected_delays

    @pytest.mark.asyncio
    async def test_version_message_sets_device_info(self) -> None:
        monitor = GPSSpeedMonitor(gps_enabled=True)
        release = asyncio.Event()

        async def _handler(reader, writer):
            await reader.readline()
            writer.write(b'{"class":"VERSION","rev":"3.25"}\n')
            await writer.drain()
            writer.write(b'{"class":"TPV","mode":3,"speed":10.0}\n')
            await writer.drain()
            # Like a real gpsd, keep the stream open: a close would clear the state under test.
            await release.wait()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(_handler, host="127.0.0.1", port=0)
        host, port = server.sockets[0].getsockname()[:2]

        task = asyncio.create_task(monitor.run(host=host, port=port))
        assert await async_wait_until(
            lambda: monitor.device_info == "gpsd 3.25" and monitor.speed_mps == 10.0,
            timeout_s=1.5,
        ), "Timed out waiting for GPS VERSION and TPV messages to update monitor state"
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        server.close()
        await server.wait_closed()

        assert monitor.device_info is not None
        assert "3.25" in monitor.device_info


@pytest.mark.asyncio
async def test_gpsd_without_receiver_backs_off_and_logs_once(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """gpsd accepts and greets but never sends a TPV: back off, warn once, log the recovery."""
    monkeypatch.setattr("vibesensor.speed.gps_transport_lifecycle.GPS_RECONNECT_DELAY_S", 0.01)
    monkeypatch.setattr("vibesensor.speed.gps_transport_lifecycle.GPS_RECONNECT_MAX_DELAY_S", 0.04)
    monkeypatch.setattr("vibesensor.speed.gps_transport_lifecycle.GPS_READ_TIMEOUT_S", 0.02)
    monitor = GPSSpeedMonitor(gps_enabled=True)
    sessions = 0
    receiver_attached = asyncio.Event()
    release = asyncio.Event()

    async def _handler(reader, writer):
        nonlocal sessions
        sessions += 1
        await reader.readline()
        writer.write(b'{"class":"VERSION","rev":"3.25"}\n')
        if receiver_attached.is_set():
            writer.write(b'{"class":"TPV","mode":3,"speed":10.0}\n')
        await writer.drain()
        await release.wait()
        writer.close()

    server = await asyncio.start_server(_handler, host="127.0.0.1", port=0)
    host, port = server.sockets[0].getsockname()[:2]
    caplog.set_level("DEBUG", logger="vibesensor.speed.gps_transport_runner")
    task = asyncio.create_task(monitor.run(host=host, port=port))
    try:
        assert await async_wait_until(lambda: sessions >= 5, timeout_s=3.0)
        # Successful connects alone do not reset the backoff.
        assert monitor.current_reconnect_delay == pytest.approx(0.04)
        receiver_attached.set()
        assert await async_wait_until(lambda: monitor.speed_mps == 10.0, timeout_s=3.0)
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        server.close()
        await server.wait_closed()

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert [r.getMessage().split(";")[0] for r in warnings] == ["GPS unavailable (TimeoutError)"]
    assert any(r.getMessage().startswith("GPS data resumed after") for r in caplog.records)
