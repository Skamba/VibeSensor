"""Behavior tests for GPS reconnect backoff and receiver detection."""

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
    """Cover reconnect delay growth and capping."""

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
async def test_gpsd_version_banner_is_no_receiver(monkeypatch: pytest.MonkeyPatch) -> None:
    """gpsd greets with VERSION and an empty DEVICES list when nothing is plugged in."""
    monkeypatch.setattr("vibesensor.speed.gps_transport_lifecycle.GPS_READ_TIMEOUT_S", 0.02)
    monitor = GPSSpeedMonitor(gps_enabled=True)
    release = asyncio.Event()
    queries: list[bytes] = []

    async def _handler(reader, writer):
        await reader.readline()
        writer.write(b'{"class":"VERSION","rev":"3.25"}\n{"class":"DEVICES","devices":[]}\n')
        await writer.drain()
        while not release.is_set():
            line = await reader.readline()
            if not line:
                break
            queries.append(line)
            writer.write(b'{"class":"DEVICES","devices":[]}\n')
            await writer.drain()
        writer.close()

    server = await asyncio.start_server(_handler, host="127.0.0.1", port=0)
    host, port = server.sockets[0].getsockname()[:2]
    task = asyncio.create_task(monitor.run(host=host, port=port))
    try:
        # A quiet gpsd is asked for its devices instead of being reconnected to.
        assert await async_wait_until(lambda: len(queries) >= 3, timeout_s=3.0)
        status = monitor.status_snapshot()
        assert (status.device, status.fix_wait_s) == (None, None)
        assert monitor.connection_state == "connected"
        assert set(queries) == {b"?DEVICES;\n"}
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_gpsd_without_receiver_keeps_the_session_for_a_hot_plugged_one(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No receiver: stay connected, no warnings; a hot-plugged receiver reuses the session."""
    monkeypatch.setattr("vibesensor.speed.gps_transport_lifecycle.GPS_READ_TIMEOUT_S", 0.02)
    monitor = GPSSpeedMonitor(gps_enabled=True)
    sessions = 0
    plug_in = asyncio.Event()
    fix = asyncio.Event()
    release = asyncio.Event()

    async def _answer_queries(reader, writer):
        while True:
            line = await reader.readline()
            if not line:
                return
            if not plug_in.is_set():
                writer.write(b'{"class":"DEVICES","devices":[]}\n')
                await writer.drain()

    async def _handler(reader, writer):
        nonlocal sessions
        sessions += 1
        await reader.readline()
        writer.write(b'{"class":"VERSION","rev":"3.25"}\n{"class":"DEVICES","devices":[]}\n')
        await writer.drain()
        answering = asyncio.create_task(_answer_queries(reader, writer))
        await plug_in.wait()
        writer.write(b'{"class":"DEVICE","path":"/dev/ttyACM0","activated":"2026-10-06T10:00Z"}\n')
        while not fix.is_set():
            writer.write(b'{"class":"TPV","device":"/dev/ttyACM0","mode":1}\n')
            await writer.drain()
            await asyncio.sleep(0.005)
        writer.write(b'{"class":"TPV","device":"/dev/ttyACM0","mode":3,"speed":10.0}\n')
        await writer.drain()
        await release.wait()
        answering.cancel()
        writer.close()

    server = await asyncio.start_server(_handler, host="127.0.0.1", port=0)
    host, port = server.sockets[0].getsockname()[:2]
    caplog.set_level("DEBUG", logger="vibesensor.speed.gps_transport_runner")
    task = asyncio.create_task(monitor.run(host=host, port=port))
    try:
        assert await async_wait_until(
            lambda: monitor.connection_state == "connected", timeout_s=2.0
        )
        await asyncio.sleep(0.2)
        assert monitor.device_info is None
        plug_in.set()
        assert await async_wait_until(lambda: monitor.device_info == "/dev/ttyACM0", timeout_s=2.0)
        await asyncio.sleep(0.05)
        waiting = monitor.status_snapshot()
        assert waiting.fix_wait_s is not None and waiting.fix_wait_s > 0.0
        fix.set()
        assert await async_wait_until(lambda: monitor.speed_mps == 10.0, timeout_s=2.0)
        assert monitor.status_snapshot().fix_wait_s is None
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        server.close()
        await server.wait_closed()

    assert sessions == 1
    assert not [r for r in caplog.records if r.levelname == "WARNING"]


@pytest.mark.asyncio
async def test_gpsd_that_stops_answering_is_reconnected_with_backoff(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """gpsd never answers, not even ``?DEVICES``: back off, warn once, log the recovery."""
    monkeypatch.setattr("vibesensor.speed.gps_transport_lifecycle.GPS_RECONNECT_DELAY_S", 0.01)
    monkeypatch.setattr("vibesensor.speed.gps_transport_lifecycle.GPS_RECONNECT_MAX_DELAY_S", 0.04)
    monkeypatch.setattr("vibesensor.speed.gps_transport_lifecycle.GPS_READ_TIMEOUT_S", 0.02)
    monitor = GPSSpeedMonitor(gps_enabled=True)
    sessions = 0
    answering = asyncio.Event()
    release = asyncio.Event()

    async def _handler(reader, writer):
        nonlocal sessions
        sessions += 1
        await reader.readline()
        if answering.is_set():
            writer.write(b'{"class":"TPV","device":"/dev/ttyACM0","mode":3,"speed":10.0}\n')
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
        answering.set()
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
