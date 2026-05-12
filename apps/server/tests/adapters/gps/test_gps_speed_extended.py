from __future__ import annotations

import asyncio

import pytest

from vibesensor.adapters.gps.gps_speed import GPSSpeedMonitor


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
