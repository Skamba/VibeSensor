from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from vibesensor.protocol import pack_data
from vibesensor.udp_data_rx import DataDatagramProtocol


class _FakeTransport:
    def __init__(self) -> None:
        self.sent: list[tuple[bytes, tuple[str, int]]] = []

    def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
        self.sent.append((data, addr))


@pytest.mark.asyncio
async def test_datagram_received_queues_work_before_processing() -> None:
    registry = Mock()
    registry.get.return_value = SimpleNamespace(sample_rate_hz=800)
    processor = Mock()
    proto = DataDatagramProtocol(registry=registry, processor=processor, queue_maxsize=8)
    proto.connection_made(_FakeTransport())
    pkt = pack_data(
        bytes.fromhex("010203040506"),
        seq=1,
        t0_us=123,
        samples=np.zeros((4, 3), dtype=np.int16),
    )

    proto.datagram_received(pkt, ("127.0.0.1", 12345))
    assert processor.ingest.call_count == 0

    consumer = asyncio.create_task(proto.process_queue())
    await asyncio.wait_for(proto._queue.join(), timeout=1.0)
    consumer.cancel()
    await asyncio.gather(consumer, return_exceptions=True)
    assert processor.ingest.call_count == 1


def test_datagram_queue_backpressure_drops_when_full() -> None:
    registry = Mock()
    processor = Mock()
    proto = DataDatagramProtocol(registry=registry, processor=processor, queue_maxsize=1)
    pkt = pack_data(
        bytes.fromhex("010203040506"),
        seq=1,
        t0_us=1,
        samples=np.zeros((1, 3), dtype=np.int16),
    )
    proto.datagram_received(pkt, ("127.0.0.1", 10001))
    proto.datagram_received(pkt, ("127.0.0.1", 10002))
    assert proto._queue.qsize() == 1
    registry.note_parse_error.assert_called()
