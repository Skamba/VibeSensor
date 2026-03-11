"""Tests for GPSSpeedMonitor.run() async loop behavior."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

from vibesensor.gps_speed import GPSSpeedMonitor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tpv_line(
    speed: float | None = 25.5,
    *,
    mode: int = 3,
    eph: float | None = None,
    eps: float | None = None,
    lat: float | None = 54.6872,
    lon: float | None = 25.2797,
) -> bytes:
    payload: dict[str, float | int | str | None] = {"class": "TPV", "mode": mode}
    if speed is not None:
        payload["speed"] = speed
    if eph is not None:
        payload["eph"] = eph
    if eps is not None:
        payload["eps"] = eps
    payload["lat"] = lat
    payload["lon"] = lon
    return json.dumps(payload).encode() + b"\n"


def _non_tpv_line() -> bytes:
    return json.dumps({"class": "VERSION", "release": "3.25"}).encode() + b"\n"


@asynccontextmanager
async def _gps_server_scenario(
    *lines: bytes,
    settle_s: float = 0.05,
) -> AsyncIterator[GPSSpeedMonitor]:
    """Start a mock gpsd that sends *lines*, yield the connected monitor, then tear down."""
    monitor = GPSSpeedMonitor(gps_enabled=True)

    async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()
        for line in lines:
            writer.write(line)
        await writer.drain()
        await asyncio.sleep(settle_s)
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(_handler, host="127.0.0.1", port=0)
    host, port = server.sockets[0].getsockname()[:2]
    task = asyncio.create_task(monitor.run(host=host, port=port))
    try:
        yield monitor
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        server.close()
        await server.wait_closed()


async def _await_speed(monitor: GPSSpeedMonitor, *, timeout_s: float = 2.5) -> None:
    """Block until ``monitor.speed_mps`` is set or *timeout_s* elapses."""
    for _ in range(int(timeout_s / 0.05)):
        if monitor.speed_mps is not None:
            return
        await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tpv_kwargs", "expected_speed"),
    [
        pytest.param({"speed": 25.5}, 25.5, id="default-3d-fix"),
        pytest.param(
            {"speed": 6.2, "mode": 3, "eph": 90.0, "eps": 3.2},
            6.2,
            id="poor-quality-3d-fix",
        ),
        pytest.param({"speed": 11.1, "mode": 2}, 11.1, id="2d-fix"),
        pytest.param({"speed": 8.8, "lat": None, "lon": None}, 8.8, id="missing-lat-lon"),
    ],
)
async def test_run_accepts_valid_tpv_speed(
    tpv_kwargs: dict[str, object],
    expected_speed: float,
) -> None:
    """TPV messages with valid fix mode and speed update monitor.speed_mps."""
    async with _gps_server_scenario(_tpv_line(**tpv_kwargs)) as monitor:
        await _await_speed(monitor)
        assert monitor.speed_mps == expected_speed


@pytest.mark.asyncio
async def test_run_ignores_non_tpv_messages() -> None:
    """Non-TPV messages are skipped; only TPV updates speed."""
    async with _gps_server_scenario(_non_tpv_line(), _tpv_line(12.3)) as monitor:
        await _await_speed(monitor)
        assert monitor.speed_mps == 12.3


@pytest.mark.asyncio
async def test_run_reconnects_on_connection_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """run() retries after ConnectionRefusedError instead of crashing."""
    monitor = GPSSpeedMonitor(gps_enabled=True)
    attempt_count = 0
    enough_attempts = asyncio.Event()

    async def _failing_open(*args, **kwargs):  # noqa: ANN002, ANN003
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count >= 2:
            enough_attempts.set()
        raise ConnectionRefusedError("mock refused")

    monkeypatch.setattr(asyncio, "open_connection", _failing_open)
    monkeypatch.setattr("vibesensor.gps_speed._GPS_RECONNECT_DELAY_S", 0.02)
    monkeypatch.setattr("vibesensor.gps_speed._GPS_RECONNECT_MAX_DELAY_S", 0.04)
    caplog.set_level("WARNING")

    task = asyncio.create_task(monitor.run(host="127.0.0.1", port=9999))
    await asyncio.wait_for(enough_attempts.wait(), timeout=5.0)

    assert attempt_count >= 2, f"Expected at least 2 attempts, got {attempt_count}"
    assert monitor.speed_mps is None

    task.cancel()
    await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=5.0)

    assert "GPS connection lost, retrying" in caplog.text


@pytest.mark.asyncio
async def test_run_does_not_swallow_processing_programming_errors() -> None:
    monitor = GPSSpeedMonitor(gps_enabled=True)

    def _raise_bug(payload: dict[str, object]) -> int:
        raise RuntimeError("bug")

    monitor._tpv_mode = _raise_bug  # type: ignore[method-assign]

    async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()
        writer.write(_tpv_line(12.3))
        await writer.drain()
        await asyncio.sleep(0.1)
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(_handler, host="127.0.0.1", port=0)
    host, port = server.sockets[0].getsockname()[:2]
    task = asyncio.create_task(monitor.run(host=host, port=port))

    with pytest.raises(RuntimeError, match="bug"):
        await asyncio.wait_for(task, timeout=1.0)

    server.close()
    await server.wait_closed()


@pytest.mark.asyncio
async def test_run_resets_speed_on_disconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    """speed_mps becomes None when the server closes the connection."""
    monitor = GPSSpeedMonitor(gps_enabled=True)

    async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()
        writer.write(_tpv_line(42.0))
        await writer.drain()
        # Give the client time to read
        await asyncio.sleep(0.1)
        # Close the connection to trigger disconnect
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(_handler, host="127.0.0.1", port=0)
    host, port = server.sockets[0].getsockname()[:2]

    # Shrink reconnect delay so the reconnect path runs quickly
    monkeypatch.setattr("vibesensor.gps_speed._GPS_RECONNECT_DELAY_S", 0.05)

    task = asyncio.create_task(monitor.run(host=host, port=port))

    # Wait for speed to be set
    for _ in range(50):
        if monitor.speed_mps is not None:
            break
        await asyncio.sleep(0.05)
    assert monitor.speed_mps == 42.0

    # After the server closes, the client detects EOF and the except block
    # resets speed_mps to None on the next failed reconnect attempt.
    # The server is already closed; the next connect attempt will fail.
    server.close()
    await server.wait_closed()

    for _ in range(80):
        if monitor.speed_mps is None:
            break
        await asyncio.sleep(0.05)
    assert monitor.speed_mps is None

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_run_disabled_polls_without_connecting(monkeypatch: pytest.MonkeyPatch) -> None:
    """When gps_enabled=False, run() never opens a TCP connection."""
    monitor = GPSSpeedMonitor(gps_enabled=False)
    connection_attempted = False

    async def _spy_open(*args, **kwargs):  # noqa: ANN002, ANN003
        nonlocal connection_attempted
        connection_attempted = True
        raise AssertionError("should not be called")

    monkeypatch.setattr(asyncio, "open_connection", _spy_open)
    monkeypatch.setattr("vibesensor.gps_speed._GPS_DISABLED_POLL_S", 0.02)

    task = asyncio.create_task(monitor.run())
    await asyncio.sleep(0.1)

    assert monitor.speed_mps is None
    assert not connection_attempted

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_run_ignores_malformed_json() -> None:
    """Malformed JSON lines are skipped; subsequent valid TPV is processed."""
    async with _gps_server_scenario(b"NOT VALID JSON\n", _tpv_line(7.77)) as monitor:
        await _await_speed(monitor)
        assert monitor.speed_mps == 7.77


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "non_dict_line",
    [
        pytest.param(b'["array", "not", "object"]\n', id="json-array"),
        pytest.param(b'"just a string"\n', id="json-string"),
        pytest.param(b"42\n", id="json-number"),
        pytest.param(b"null\n", id="json-null"),
    ],
)
async def test_run_ignores_non_dict_json(non_dict_line: bytes) -> None:
    """Non-object JSON lines (arrays, strings, numbers, null) are silently skipped."""
    async with _gps_server_scenario(non_dict_line, _tpv_line(9.5)) as monitor:
        await _await_speed(monitor)
        assert monitor.speed_mps == 9.5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tpv_kwargs",
    [
        pytest.param({"speed": 8.8, "mode": 1}, id="mode-below-2"),
        pytest.param({"speed": None, "mode": 3}, id="missing-speed"),
        pytest.param({"speed": float("nan"), "mode": 3}, id="non-finite-speed"),
    ],
)
async def test_run_rejects_invalid_tpv_speed(tpv_kwargs: dict[str, object]) -> None:
    """TPV messages with invalid speed/mode must not update speed_mps."""
    async with _gps_server_scenario(_tpv_line(**tpv_kwargs)) as monitor:
        await asyncio.sleep(0.15)
        assert monitor.speed_mps is None


@pytest.mark.asyncio
async def test_run_ignores_tpv_speed_with_zero_coordinates_and_keeps_last_update_ts() -> None:
    """mode=3 TPV with zero coordinates still updates speed."""
    async with _gps_server_scenario(
        _tpv_line(8.0, lat=54.6872, lon=25.2797),
        _tpv_line(13.0, lat=0.0, lon=0.0),
    ) as monitor:
        await _await_speed(monitor)
        await asyncio.sleep(0.1)
        assert monitor.speed_mps == 13.0
        assert monitor.last_update_ts is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("eph", "eps"),
    [(-0.1, 0.1), (0.1, -0.1)],
)
async def test_run_ignores_tpv_speed_with_negative_uncertainty(eph: float, eps: float) -> None:
    """mode=3 TPV with negative eph/eps still updates speed."""
    async with _gps_server_scenario(_tpv_line(8.8, mode=3, eph=eph, eps=eps)) as monitor:
        await _await_speed(monitor)
        assert monitor.speed_mps == 8.8
        assert monitor.last_update_ts is not None


@pytest.mark.asyncio
async def test_run_filters_single_zero_speed_drop() -> None:
    async with _gps_server_scenario(
        _tpv_line(12.0, mode=2),
        _tpv_line(0.0, mode=2),
        _tpv_line(12.0, mode=2),
    ) as monitor:
        await asyncio.sleep(0.15)
        assert monitor.speed_mps == 12.0


@pytest.mark.asyncio
async def test_run_accepts_three_consecutive_zero_speed_samples() -> None:
    async with _gps_server_scenario(
        _tpv_line(10.0, mode=2),
        _tpv_line(0.0, mode=2),
        _tpv_line(0.0, mode=2),
        _tpv_line(0.0, mode=2),
    ) as monitor:
        await asyncio.sleep(0.15)
        assert monitor.speed_mps == 0.0
