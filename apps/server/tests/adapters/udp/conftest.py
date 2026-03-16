"""Shared fixtures and helpers for protocol tests."""

from __future__ import annotations

import asyncio

import pytest


class FakeTransport:
    """Minimal asyncio transport stub for protocol tests."""

    def __init__(self) -> None:
        self.sent: list[tuple[bytes, tuple[str, int]]] = []

    def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
        self.sent.append((data, addr))

    def close(self) -> None:
        pass


@pytest.fixture
def fake_transport() -> FakeTransport:
    """Return a fresh FakeTransport instance."""
    return FakeTransport()


@pytest.fixture
def drain_queue():
    """Return an async callable that drains a DataDatagramProtocol queue."""

    async def _drain(proto, *, timeout: float = 2.0) -> None:
        consumer = asyncio.create_task(proto.process_queue())
        await asyncio.wait_for(proto._queue.join(), timeout=timeout)
        consumer.cancel()
        await asyncio.gather(consumer, return_exceptions=True)

    return _drain
