"""Tests for GPSSpeedMonitor.run() async loop behavior."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import pytest
from test_support.polling import async_wait_until

from vibesensor.speed.gps_speed import GPSSpeedMonitor

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


async def _await_condition(
    description: str,
    predicate,
    *,
    timeout_s: float = 2.5,
) -> None:
    assert await async_wait_until(predicate, timeout_s=timeout_s), (
        f"Timed out waiting for {description}"
    )


_END_OF_SCRIPT_REV = "end-of-test-script"


def _end_of_script_line() -> bytes:
    """VERSION sentinel: once ``device_info`` reflects it, every prior line was ingested."""
    return json.dumps({"class": "VERSION", "rev": _END_OF_SCRIPT_REV}).encode() + b"\n"


@asynccontextmanager
async def _gps_server_scenario(*lines: bytes) -> AsyncIterator[GPSSpeedMonitor]:
    """Run the monitor against a mock gpsd that sends *lines*, yielding once all are ingested.

    Like a real gpsd, the mock keeps the connection open after sending, so the
    monitor's state stays at the result of the last line instead of being
    cleared by a disconnect (and the monitor never re-connects mid-test).
    """
    monitor = GPSSpeedMonitor(gps_enabled=True)
    handler_tasks: set[asyncio.Task[None]] = set()
    connection_count = 0

    async def _serve_client(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            await reader.readline()
            writer.writelines([*lines, _end_of_script_line()])
            await writer.drain()
            # Hold the connection until the monitor disconnects at teardown.
            with suppress(ConnectionResetError):
                await reader.read()
        finally:
            writer.close()
            with suppress(ConnectionResetError, BrokenPipeError):
                await writer.wait_closed()

    def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal connection_count
        connection_count += 1
        task = asyncio.create_task(_serve_client(reader, writer))
        handler_tasks.add(task)
        task.add_done_callback(handler_tasks.discard)

    server = await asyncio.start_server(_handler, host="127.0.0.1", port=0)
    host, port = server.sockets[0].getsockname()[:2]
    task = asyncio.create_task(monitor.run(host=host, port=port))
    try:
        await _await_condition(
            "GPS run loop to ingest every scripted gpsd line",
            lambda: monitor.device_info == f"gpsd {_END_OF_SCRIPT_REV}",
            timeout_s=5.0,
        )
        assert connection_count == 1
        yield monitor
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        server.close()
        if handler_tasks:
            done, pending = await asyncio.wait(handler_tasks, timeout=1.0)
            if pending:
                for pending_task in pending:
                    pending_task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
        await server.wait_closed()


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
        assert monitor.speed_mps == expected_speed


@pytest.mark.asyncio
async def test_run_ignores_non_tpv_messages() -> None:
    """Non-TPV messages are skipped; only TPV updates speed."""
    async with _gps_server_scenario(_non_tpv_line(), _tpv_line(12.3)) as monitor:
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
    monkeypatch.setattr(
        "vibesensor.speed.gps_transport_lifecycle.GPS_RECONNECT_DELAY_S",
        0.02,
    )
    monkeypatch.setattr(
        "vibesensor.speed.gps_transport_lifecycle.GPS_RECONNECT_MAX_DELAY_S",
        0.04,
    )
    caplog.set_level("WARNING")

    task = asyncio.create_task(monitor.run(host="127.0.0.1", port=9999))
    try:
        await asyncio.wait_for(enough_attempts.wait(), timeout=5.0)
        await _await_condition(
            "GPS reconnect error state after refused connections",
            lambda: (
                attempt_count >= 2
                and monitor.last_error == "mock refused"
                and 0.02 <= monitor.current_reconnect_delay <= 0.04
            ),
            timeout_s=5.0,
        )

        assert attempt_count >= 2, f"Expected at least 2 attempts, got {attempt_count}"
        assert monitor.speed_mps is None
        assert monitor.last_error == "mock refused"
        assert 0.02 <= monitor.current_reconnect_delay <= 0.04

        task.cancel()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=5.0)

        assert "GPS connection lost, retrying" in caplog.text
        reconnect_records = [
            record for record in caplog.records if "GPS connection lost, retrying" in record.message
        ]
        assert reconnect_records
        assert all(record.exc_info is None for record in reconnect_records)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_run_does_not_swallow_processing_programming_errors() -> None:
    monitor = GPSSpeedMonitor(gps_enabled=True)

    def _raise_bug(tpv: object) -> None:
        raise RuntimeError("bug")

    monitor._transport._apply_tpv = _raise_bug  # type: ignore[assignment]

    async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()
        writer.write(_tpv_line(12.3))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(_handler, host="127.0.0.1", port=0)
    host, port = server.sockets[0].getsockname()[:2]
    task = asyncio.create_task(monitor.run(host=host, port=port))

    try:
        with pytest.raises(RuntimeError, match="bug"):
            await asyncio.wait_for(task, timeout=1.0)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_run_resets_speed_on_disconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    """speed_mps becomes None when the server closes the connection."""
    monitor = GPSSpeedMonitor(gps_enabled=True)
    disconnect = asyncio.Event()

    async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()
        writer.write(_tpv_line(42.0))
        await writer.drain()
        await disconnect.wait()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(_handler, host="127.0.0.1", port=0)
    host, port = server.sockets[0].getsockname()[:2]

    # Shrink reconnect delay so the reconnect path runs quickly
    monkeypatch.setattr(
        "vibesensor.speed.gps_transport_lifecycle.GPS_RECONNECT_DELAY_S",
        0.05,
    )

    task = asyncio.create_task(monitor.run(host=host, port=port))
    try:
        await _await_condition(
            "GPS speed to update before server disconnect",
            lambda: monitor.speed_mps == 42.0,
        )

        # Stop accepting first so the reconnect after EOF is refused, then
        # close the open connection: EOF clears the speed.
        server.close()
        disconnect.set()
        await server.wait_closed()

        await _await_condition(
            "GPS speed to clear after disconnect and failed reconnect",
            lambda: monitor.speed_mps is None and monitor.last_error is not None,
            timeout_s=5.0,
        )
    finally:
        server.close()
        disconnect.set()
        await server.wait_closed()
        if not task.done():
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
    monkeypatch.setattr(
        "vibesensor.speed.gps_transport_lifecycle.GPS_DISABLED_POLL_S",
        0.02,
    )
    original_sleep = asyncio.sleep
    disabled_poll_seen = asyncio.Event()

    async def _spy_sleep(delay: float) -> None:
        if delay == 0.02:
            disabled_poll_seen.set()
        await original_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", _spy_sleep)

    task = asyncio.create_task(monitor.run())
    try:
        await asyncio.wait_for(disabled_poll_seen.wait(), timeout=1.0)

        assert monitor.speed_mps is None
        assert not connection_attempted
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_run_ignores_malformed_json() -> None:
    """Malformed JSON lines are skipped; subsequent valid TPV is processed."""
    async with _gps_server_scenario(b"NOT VALID JSON\n", _tpv_line(7.77)) as monitor:
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
        assert monitor.last_fix_mode == int(tpv_kwargs.get("mode", 3))
        assert monitor.speed_mps is None


@pytest.mark.asyncio
async def test_run_ignores_tpv_speed_with_zero_coordinates_and_keeps_last_update_ts() -> None:
    """mode=3 TPV with zero coordinates still updates speed."""
    async with _gps_server_scenario(
        _tpv_line(8.0, lat=54.6872, lon=25.2797),
        _tpv_line(13.0, lat=0.0, lon=0.0),
    ) as monitor:
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
        assert monitor.speed_mps == 8.8
        assert monitor.last_update_ts is not None


@pytest.mark.asyncio
async def test_run_filters_single_zero_speed_drop() -> None:
    async with _gps_server_scenario(
        _tpv_line(12.0, mode=2),
        _tpv_line(0.0, mode=2),
        _tpv_line(12.0, mode=2),
    ) as monitor:
        assert monitor.speed_mps == 12.0
        assert monitor._zero_speed_streak == 0


@pytest.mark.asyncio
async def test_run_accepts_three_consecutive_zero_speed_samples() -> None:
    async with _gps_server_scenario(
        _tpv_line(10.0, mode=2),
        _tpv_line(0.0, mode=2),
        _tpv_line(0.0, mode=2),
        _tpv_line(0.0, mode=2),
    ) as monitor:
        assert monitor.speed_mps == 0.0
        assert monitor._zero_speed_streak == 3
