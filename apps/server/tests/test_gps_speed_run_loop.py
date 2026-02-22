"""Tests for GPSSpeedMonitor.run() async loop behavior."""

from __future__ import annotations

import asyncio
import json

import pytest

from vibesensor.gps_speed import GPSSpeedMonitor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tpv_line(
    speed: float,
    *,
    mode: int = 3,
    eph: float | None = None,
    eps: float | None = None,
) -> bytes:
    payload: dict[str, float | int | str] = {"class": "TPV", "speed": speed, "mode": mode}
    if eph is not None:
        payload["eph"] = eph
    if eps is not None:
        payload["eps"] = eps
    return json.dumps(payload).encode() + b"\n"


def _non_tpv_line() -> bytes:
    return json.dumps({"class": "VERSION", "release": "3.25"}).encode() + b"\n"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_parses_tpv_and_updates_speed() -> None:
    """TPV message with speed sets monitor.speed_mps."""
    monitor = GPSSpeedMonitor(gps_enabled=True)

    async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        # Wait for the WATCH command from the client
        await reader.readline()
        writer.write(_tpv_line(25.5))
        await writer.drain()
        # Keep connection open briefly so the client can read
        await asyncio.sleep(0.2)
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(_handler, host="127.0.0.1", port=0)
    host, port = server.sockets[0].getsockname()[:2]
    task = asyncio.create_task(monitor.run(host=host, port=port))

    # Wait until speed is set
    for _ in range(50):
        if monitor.speed_mps is not None:
            break
        await asyncio.sleep(0.05)

    assert monitor.speed_mps == 25.5

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    server.close()
    await server.wait_closed()


@pytest.mark.asyncio
async def test_run_ignores_non_tpv_messages() -> None:
    """Non-TPV messages are skipped; only TPV updates speed."""
    monitor = GPSSpeedMonitor(gps_enabled=True)

    async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()
        writer.write(_non_tpv_line())
        writer.write(_tpv_line(12.3))
        await writer.drain()
        await asyncio.sleep(0.2)
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(_handler, host="127.0.0.1", port=0)
    host, port = server.sockets[0].getsockname()[:2]
    task = asyncio.create_task(monitor.run(host=host, port=port))

    for _ in range(50):
        if monitor.speed_mps is not None:
            break
        await asyncio.sleep(0.05)

    assert monitor.speed_mps == 12.3

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    server.close()
    await server.wait_closed()


@pytest.mark.asyncio
async def test_run_reconnects_on_connection_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """run() retries after ConnectionRefusedError instead of crashing."""
    monitor = GPSSpeedMonitor(gps_enabled=True)
    attempt_count = 0

    async def _failing_open(*args, **kwargs):  # noqa: ANN002, ANN003
        nonlocal attempt_count
        attempt_count += 1
        raise ConnectionRefusedError("mock refused")

    monkeypatch.setattr(asyncio, "open_connection", _failing_open)
    # Shrink reconnect delay so the test doesn't wait long
    monkeypatch.setattr("vibesensor.gps_speed._GPS_RECONNECT_DELAY_S", 0.05)
    monkeypatch.setattr("vibesensor.gps_speed._GPS_RECONNECT_MAX_DELAY_S", 0.1)

    task = asyncio.create_task(monitor.run(host="127.0.0.1", port=9999))
    await asyncio.sleep(0.3)

    assert attempt_count >= 2, f"Expected at least 2 attempts, got {attempt_count}"
    assert monitor.speed_mps is None

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


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
    monkeypatch.setattr("vibesensor.gps_speed._GPS_DISABLED_POLL_S", 0.05)

    task = asyncio.create_task(monitor.run())
    await asyncio.sleep(0.2)

    assert monitor.speed_mps is None
    assert not connection_attempted

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_run_ignores_malformed_json() -> None:
    """Malformed JSON lines are skipped; subsequent valid TPV is processed."""
    monitor = GPSSpeedMonitor(gps_enabled=True)

    async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()
        writer.write(b"NOT VALID JSON\n")
        writer.write(_tpv_line(7.77))
        await writer.drain()
        await asyncio.sleep(0.2)
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(_handler, host="127.0.0.1", port=0)
    host, port = server.sockets[0].getsockname()[:2]
    task = asyncio.create_task(monitor.run(host=host, port=port))

    for _ in range(50):
        if monitor.speed_mps is not None:
            break
        await asyncio.sleep(0.05)

    assert monitor.speed_mps == 7.77

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    server.close()
    await server.wait_closed()


@pytest.mark.asyncio
async def test_run_ignores_tpv_speed_without_3d_fix() -> None:
    """TPV speeds with mode < 3 must not be used."""
    monitor = GPSSpeedMonitor(gps_enabled=True)

    async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()
        writer.write(_tpv_line(8.8, mode=2))
        await writer.drain()
        await asyncio.sleep(0.2)
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(_handler, host="127.0.0.1", port=0)
    host, port = server.sockets[0].getsockname()[:2]
    task = asyncio.create_task(monitor.run(host=host, port=port))
    await asyncio.sleep(0.4)

    assert monitor.speed_mps is None

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    server.close()
    await server.wait_closed()


@pytest.mark.asyncio
async def test_run_ignores_tpv_speed_with_poor_quality_3d_fix() -> None:
    """3D fix with poor quality metrics must not be used."""
    monitor = GPSSpeedMonitor(gps_enabled=True)

    async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()
        writer.write(_tpv_line(6.2, mode=3, eph=90.0, eps=3.2))
        await writer.drain()
        await asyncio.sleep(0.2)
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(_handler, host="127.0.0.1", port=0)
    host, port = server.sockets[0].getsockname()[:2]
    task = asyncio.create_task(monitor.run(host=host, port=port))
    await asyncio.sleep(0.4)

    assert monitor.speed_mps is None

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    server.close()
    await server.wait_closed()
