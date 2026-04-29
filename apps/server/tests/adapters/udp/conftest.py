"""Shared fixtures and helpers for protocol tests."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest

from vibesensor.adapters.udp.udp_data_rx import DataDatagramProtocol


class FakeTransport:
    """Minimal asyncio transport stub for protocol tests."""

    def __init__(self) -> None:
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.closed = False

    def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
        self.sent.append((data, addr))

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_transport() -> FakeTransport:
    """Return a fresh FakeTransport instance."""
    return FakeTransport()


@pytest.fixture
def drain_queue() -> Callable[[DataDatagramProtocol], Awaitable[None]]:
    """Return an async callable that drains queued work via the public consumer loop.

    The protocol exposes ``process_queue()`` but no public "drained" signal, so
    tests use ``Queue.join()`` only as scheduling coordination while asserting on
    observable ingest/ack/diagnostic effects instead of queue internals.
    """

    async def _drain(proto: DataDatagramProtocol, *, timeout: float = 2.0) -> None:
        consumer = asyncio.create_task(proto.process_queue())
        await asyncio.wait_for(proto._queue.join(), timeout=timeout)
        consumer.cancel()
        await asyncio.gather(consumer, return_exceptions=True)

    return _drain
