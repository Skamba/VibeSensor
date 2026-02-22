from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock, patch

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
    registry.note_server_queue_drop.assert_called()
    registry.note_parse_error.assert_not_called()


def test_datagram_queue_backpressure_rate_limits_drop_warnings() -> None:
    registry = Mock()
    processor = Mock()
    proto = DataDatagramProtocol(
        registry=registry,
        processor=processor,
        queue_maxsize=1,
        queue_drop_log_interval_s=10.0,
    )
    pkt = pack_data(
        bytes.fromhex("010203040506"),
        seq=1,
        t0_us=1,
        samples=np.zeros((1, 3), dtype=np.int16),
    )
    proto.datagram_received(pkt, ("127.0.0.1", 10001))
    with patch("vibesensor.udp_data_rx.time.monotonic", side_effect=[100.0, 101.0, 102.0, 115.0]):
        with patch("vibesensor.udp_data_rx.LOGGER.warning") as warning_log:
            proto.datagram_received(pkt, ("127.0.0.1", 10002))
            proto.datagram_received(pkt, ("127.0.0.1", 10003))
            proto.datagram_received(pkt, ("127.0.0.1", 10004))
            proto.datagram_received(pkt, ("127.0.0.1", 10005))

    assert registry.note_server_queue_drop.call_count == 4
    assert warning_log.call_count == 2
    assert warning_log.call_args_list[0].args[0] == (
        "UDP ingest queue full; dropping packet from %s (client=%s)"
    )
    assert "suppressed %d additional drop warnings" in warning_log.call_args_list[1].args[0]
    assert warning_log.call_args_list[1].args[-1] == 2
