from __future__ import annotations

import asyncio

import pytest
from test_support.gps import set_gps_snapshot_age

from vibesensor.adapters.gps.gps_speed import GPSSpeedMonitor


@pytest.mark.parametrize(
    ("gps_enabled", "gps_speed_mps", "manual_selected", "override_mps", "expected_mps"),
    [
        pytest.param(True, 10.0, True, None, 10.0, id="fresh-gps-used-without-override"),
        pytest.param(True, 10.0, True, 25.0, 25.0, id="manual-override-beats-gps"),
        pytest.param(False, None, True, 25.0, 25.0, id="manual-override-used-without-gps"),
        pytest.param(False, None, True, None, None, id="nothing-set-resolves-none"),
    ],
)
def test_effective_speed_contract(
    gps_enabled: bool,
    gps_speed_mps: float | None,
    manual_selected: bool,
    override_mps: float | None,
    expected_mps: float | None,
) -> None:
    monitor = GPSSpeedMonitor(gps_enabled=gps_enabled)
    monitor.manual_source_selected = manual_selected
    monitor.override_speed_mps = override_mps
    monitor.speed_mps = gps_speed_mps
    if gps_speed_mps is not None:
        set_gps_snapshot_age(monitor)
    assert monitor.effective_speed_mps == expected_mps


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


@pytest.mark.parametrize(
    ("new_speed_mps", "expected_snapshot"),
    [
        pytest.param(7.5, (7.5, 42.0), id="sets-speed-with-current-timestamp"),
        pytest.param(None, (None, None), id="clears-speed-and-timestamp"),
    ],
)
def test_speed_mps_setter_updates_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    new_speed_mps: float | None,
    expected_snapshot: tuple[float | None, float | None],
) -> None:
    monitor = GPSSpeedMonitor(gps_enabled=True)
    monitor._speed_snapshot = (10.0, 5.0)

    monkeypatch.setattr("vibesensor.adapters.gps.gps_transport.time.monotonic", lambda: 42.0)

    monitor.speed_mps = new_speed_mps

    assert monitor._speed_snapshot == expected_snapshot
