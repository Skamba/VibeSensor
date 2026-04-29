from __future__ import annotations

import asyncio

import pytest
from test_support.gps import set_gps_snapshot_age

from vibesensor.adapters.gps.gps_speed import GPSSpeedMonitor

# -- effective_speed_mps -------------------------------------------------------


def test_gps_used_as_fallback_when_no_override() -> None:
    monitor = GPSSpeedMonitor(gps_enabled=True)
    monitor.speed_mps = 10.0
    set_gps_snapshot_age(monitor)  # mark GPS data as fresh
    assert monitor.effective_speed_mps == 10.0


def test_override_has_priority_over_gps() -> None:
    monitor = GPSSpeedMonitor(gps_enabled=True)
    monitor.speed_mps = 10.0
    monitor.override_speed_mps = 25.0
    assert monitor.effective_speed_mps == 25.0


def test_override_used_when_no_gps() -> None:
    monitor = GPSSpeedMonitor(gps_enabled=False)
    monitor.manual_source_selected = True
    monitor.override_speed_mps = 25.0
    assert monitor.effective_speed_mps == 25.0


def test_effective_none_when_nothing_set() -> None:
    monitor = GPSSpeedMonitor(gps_enabled=False)
    assert monitor.effective_speed_mps is None


# -- set_speed_override_kmh ---------------------------------------------------


def test_override_converts_kmh_to_mps() -> None:
    monitor = GPSSpeedMonitor(gps_enabled=False)
    result = monitor.set_speed_override_kmh(72.0)
    assert result == 72.0
    assert monitor.override_speed_mps is not None
    assert abs(monitor.override_speed_mps - 20.0) < 1e-9


@pytest.mark.parametrize(
    ("clear_value", "expected"),
    [
        pytest.param(None, None, id="none_clears"),
        pytest.param(0.0, 0.0, id="zero_sets_stationary"),
        pytest.param(-10.0, None, id="negative_clears"),
    ],
)
def test_override_boundary_values(clear_value: float | None, expected: float | None) -> None:
    """Setting override after a valid value: None clears, 0 is stationary, negative clears."""
    monitor = GPSSpeedMonitor(gps_enabled=False)
    monitor.set_speed_override_kmh(90.0)
    monitor.set_speed_override_kmh(clear_value)
    assert monitor.override_speed_mps == expected


# -- integer speed_mps ---------------------------------------------------------


def test_integer_speed_mps_treated_as_float() -> None:
    """speed_mps set to int should still be returned as float via effective_speed_mps."""
    monitor = GPSSpeedMonitor(gps_enabled=True)
    monitor.speed_mps = 10
    set_gps_snapshot_age(monitor)  # mark GPS data as fresh
    result = monitor.effective_speed_mps
    assert result is not None
    assert isinstance(result, float)
    assert result == 10.0


@pytest.mark.asyncio
async def test_run_can_be_cancelled_while_gps_stream_hangs() -> None:
    monitor = GPSSpeedMonitor(gps_enabled=True)
    client_connected = asyncio.Event()

    async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        client_connected.set()
        try:
            await reader.read()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(_handler, host="127.0.0.1", port=0)
    host, port = server.sockets[0].getsockname()[:2]
    task = asyncio.create_task(monitor.run(host=host, port=port))
    await asyncio.wait_for(client_connected.wait(), timeout=1.0)
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
    read_started = asyncio.Event()
    release_read = asyncio.Event()

    class _FakeReader:
        async def readline(self) -> bytes:
            read_started.set()
            await release_read.wait()
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
    await asyncio.wait_for(read_started.wait(), timeout=1.0)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert fake_writer.wait_closed_calls == 1
    assert monitor.speed_mps is None


def test_speed_mps_setter_replaces_timestamp_without_preserving_stale_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor = GPSSpeedMonitor(gps_enabled=True)
    monitor._speed_snapshot = (10.0, 5.0)

    monkeypatch.setattr("vibesensor.adapters.gps.gps_transport.time.monotonic", lambda: 42.0)

    monitor.speed_mps = 7.5

    assert monitor._speed_snapshot == (7.5, 42.0)


def test_speed_mps_setter_clears_timestamp_when_speed_clears() -> None:
    monitor = GPSSpeedMonitor(gps_enabled=True)
    monitor._speed_snapshot = (10.0, 5.0)

    monitor.speed_mps = None

    assert monitor._speed_snapshot == (None, None)
