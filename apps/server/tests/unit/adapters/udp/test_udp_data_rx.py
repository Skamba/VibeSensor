from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import pytest

from vibesensor.adapters.udp.data_rx import DataDatagramProtocol
from vibesensor.adapters.udp.protocol import pack_data
from vibesensor.infra.runtime.registry import DataUpdateResult


@pytest.mark.asyncio
async def test_datagram_received_queues_work_before_processing(fake_transport, drain_queue) -> None:
    registry = Mock()
    registry.update_from_data.return_value = DataUpdateResult()
    registry.get.return_value = SimpleNamespace(sample_rate_hz=800)
    processor = Mock()
    proto = DataDatagramProtocol(registry=registry, processor=processor, queue_maxsize=8)
    proto.connection_made(fake_transport)
    pkt = pack_data(
        bytes.fromhex("010203040506"),
        seq=1,
        t0_us=123,
        samples=np.zeros((4, 3), dtype=np.int16),
    )

    proto.datagram_received(pkt, ("127.0.0.1", 12345))
    assert processor.ingest.call_count == 0

    await drain_queue(proto, timeout=1.0)
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
    with (
        patch(
            "vibesensor.adapters.udp.data_rx.time.monotonic",
            side_effect=[100.0, 101.0, 102.0, 115.0],
        ),
        patch("vibesensor.adapters.udp.data_rx.LOGGER.warning") as warning_log,
    ):
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


def test_datagram_received_ignores_empty_and_non_data_packets() -> None:
    registry = Mock()
    processor = Mock()
    proto = DataDatagramProtocol(registry=registry, processor=processor, queue_maxsize=4)

    proto.datagram_received(b"", ("127.0.0.1", 10001))
    proto.datagram_received(b"\x01not-data", ("127.0.0.1", 10001))

    assert proto._queue.qsize() == 0
    registry.note_server_queue_drop.assert_not_called()
    registry.note_parse_error.assert_not_called()


@pytest.mark.asyncio
async def test_duplicate_data_still_sends_ack_but_skips_ingest(fake_transport, drain_queue) -> None:
    """A duplicate DATA frame should be ACKed but NOT ingested."""
    registry = Mock()
    # First call: new frame; second call: duplicate
    registry.update_from_data.side_effect = [
        DataUpdateResult(),
        DataUpdateResult(is_duplicate=True),
    ]
    registry.get.return_value = SimpleNamespace(sample_rate_hz=800)
    processor = Mock()

    proto = DataDatagramProtocol(registry=registry, processor=processor, queue_maxsize=8)
    proto.connection_made(fake_transport)

    cid = bytes.fromhex("010203040506")
    pkt = pack_data(cid, seq=42, t0_us=100_000, samples=np.zeros((4, 3), dtype=np.int16))

    # Send same packet twice
    proto.datagram_received(pkt, ("127.0.0.1", 12345))
    proto.datagram_received(pkt, ("127.0.0.1", 12345))

    await drain_queue(proto)

    # Ingest should be called only once (for the non-duplicate)
    assert processor.ingest.call_count == 1
    # ACK should be sent for both (2 DATA_ACK packets)
    assert len(fake_transport.sent) == 2


@pytest.mark.asyncio
async def test_process_datagram_logs_client_id_on_error(fake_transport, drain_queue) -> None:
    """Exception in processing should log the client ID without crashing."""
    registry = Mock()
    registry.update_from_data.side_effect = RuntimeError("boom")
    processor = Mock()
    proto = DataDatagramProtocol(registry=registry, processor=processor, queue_maxsize=8)
    proto.connection_made(fake_transport)

    cid = bytes.fromhex("aabbccddeeff")
    pkt = pack_data(cid, seq=1, t0_us=100, samples=np.zeros((4, 3), dtype=np.int16))

    proto.datagram_received(pkt, ("127.0.0.1", 12345))

    await drain_queue(proto, timeout=1.0)

    # Should not crash – the error is caught and logged
    assert processor.ingest.call_count == 0


def test_process_datagram_parse_error_marks_registry_and_skips_ack(fake_transport) -> None:
    registry = Mock()
    processor = Mock()
    proto = DataDatagramProtocol(registry=registry, processor=processor, queue_maxsize=8)
    proto.connection_made(fake_transport)

    proto._process_datagram(b"\x02\x01", ("127.0.0.1", 12345))

    registry.note_parse_error.assert_called_once()
    registry.update_from_data.assert_not_called()
    assert fake_transport.sent == []


def test_process_datagram_reset_detected_flushes_buffer_before_ingest(fake_transport) -> None:
    registry = Mock()
    registry.update_from_data.return_value = DataUpdateResult(reset_detected=True)
    registry.get.return_value = SimpleNamespace(sample_rate_hz=1600)
    processor = Mock()
    proto = DataDatagramProtocol(registry=registry, processor=processor, queue_maxsize=8)
    proto.connection_made(fake_transport)

    pkt = pack_data(
        bytes.fromhex("010203040506"),
        seq=10,
        t0_us=321,
        samples=np.zeros((2, 3), dtype=np.int16),
    )
    proto._process_datagram(pkt, ("127.0.0.1", 12345))

    processor.flush_client_buffer.assert_called_once_with("010203040506")
    processor.ingest.assert_called_once()
    assert len(fake_transport.sent) == 1
