from __future__ import annotations

import asyncio
import time

import pytest

from vibesensor.gps_speed import GPSSpeedMonitor

# -- effective_speed_mps -------------------------------------------------------


def test_gps_used_as_fallback_when_no_override() -> None:
    m = GPSSpeedMonitor(gps_enabled=True)
    m.speed_mps = 10.0
    m.last_update_ts = time.monotonic()  # mark GPS data as fresh
    assert m.effective_speed_mps == 10.0


def test_override_has_priority_over_gps() -> None:
    m = GPSSpeedMonitor(gps_enabled=True)
    m.speed_mps = 10.0
    m.override_speed_mps = 25.0
    assert m.effective_speed_mps == 25.0


def test_override_used_when_no_gps() -> None:
    m = GPSSpeedMonitor(gps_enabled=False)
    m.manual_source_selected = True
    m.override_speed_mps = 25.0
    assert m.effective_speed_mps == 25.0


def test_effective_none_when_nothing_set() -> None:
    m = GPSSpeedMonitor(gps_enabled=False)
    assert m.effective_speed_mps is None


# -- set_speed_override_kmh ---------------------------------------------------


def test_override_converts_kmh_to_mps() -> None:
    m = GPSSpeedMonitor(gps_enabled=False)
    result = m.set_speed_override_kmh(72.0)
    assert result == 72.0
    assert m.override_speed_mps is not None
    assert abs(m.override_speed_mps - 20.0) < 1e-9


def test_override_none_clears() -> None:
    m = GPSSpeedMonitor(gps_enabled=False)
    m.set_speed_override_kmh(90.0)
    m.set_speed_override_kmh(None)
    assert m.override_speed_mps is None


def test_override_zero_sets_stationary() -> None:
    m = GPSSpeedMonitor(gps_enabled=False)
    m.set_speed_override_kmh(90.0)
    # Zero is a valid speed (vehicle is stationary)
    m.set_speed_override_kmh(0.0)
    assert m.override_speed_mps == 0.0


def test_override_negative_clears() -> None:
    m = GPSSpeedMonitor(gps_enabled=False)
    m.set_speed_override_kmh(90.0)
    m.set_speed_override_kmh(-10.0)
    assert m.override_speed_mps is None


# -- integer speed_mps ---------------------------------------------------------


def test_integer_speed_mps_treated_as_float() -> None:
    """speed_mps set to int should still be returned as float via effective_speed_mps."""
    m = GPSSpeedMonitor(gps_enabled=True)
    m.speed_mps = 10  # type: ignore[assignment]
    m.last_update_ts = time.monotonic()  # mark GPS data as fresh
    result = m.effective_speed_mps
    assert result is not None
    assert isinstance(result, float)
    assert result == 10.0


@pytest.mark.asyncio
async def test_run_can_be_cancelled_while_gps_stream_hangs() -> None:
    monitor = GPSSpeedMonitor(gps_enabled=True)

    async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await asyncio.sleep(0.5)
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(_handler, host="127.0.0.1", port=0)
    host, port = server.sockets[0].getsockname()[:2]
    task = asyncio.create_task(monitor.run(host=host, port=port))
    await asyncio.sleep(0.2)
    task.cancel()
    results = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(results[0], asyncio.CancelledError)
    assert monitor.speed_mps is None
    server.close()
    await server.wait_closed()


@pytest.mark.asyncio
async def test_run_cancellation_waits_writer_close_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor = GPSSpeedMonitor(gps_enabled=True)

    class _FakeReader:
        async def readline(self) -> bytes:
            await asyncio.sleep(5)
            return b""

    class _FakeWriter:
        def __init__(self) -> None:
            self.wait_closed_calls = 0

        def write(self, _payload: bytes) -> None:
            return None

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            self.wait_closed_calls += 1

    fake_writer = _FakeWriter()

    async def _open_connection(_host: str, _port: int):
        return _FakeReader(), fake_writer

    monkeypatch.setattr(asyncio, "open_connection", _open_connection)
    task = asyncio.create_task(monitor.run(host="127.0.0.1", port=2947))
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert fake_writer.wait_closed_calls == 1
    assert monitor.speed_mps is None
