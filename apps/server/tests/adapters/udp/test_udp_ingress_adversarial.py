"""Focused adversarial coverage for UDP ingress packet handling."""

from __future__ import annotations

import logging
import struct
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from vibesensor.adapters.udp.protocol import DATA_HEADER_BYTES, pack_data, parse_data_ack
from vibesensor.adapters.udp.protocol_validator import MAX_SAMPLE_COUNT
from vibesensor.adapters.udp.udp_data_rx import DataDatagramProtocol
from vibesensor.infra.runtime.registry import DataUpdateResult


def _valid_packet(*, seq: int) -> bytes:
    return pack_data(
        bytes.fromhex("010203040506"),
        seq=seq,
        t0_us=seq * 1_000,
        samples=np.zeros((4, 3), dtype=np.int16),
    )


def _packet_with_oversized_sample_count() -> bytes:
    packet = bytearray(_valid_packet(seq=7))
    struct.pack_into("<H", packet, DATA_HEADER_BYTES - 2, MAX_SAMPLE_COUNT + 1)
    return bytes(packet)


class _FailFirstTransport:
    def __init__(self) -> None:
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self._failed = False

    def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
        if not self._failed:
            self._failed = True
            raise OSError("boom")
        self.sent.append((data, addr))

    def close(self) -> None:
        return None


@pytest.mark.parametrize(
    "packet",
    [
        _valid_packet(seq=3)[:-1],
        _packet_with_oversized_sample_count(),
    ],
    ids=["truncated-data", "oversized-sample-count"],
)
def test_process_datagram_rejects_malformed_or_oversized_packets(
    packet: bytes,
    fake_transport,
) -> None:
    registry = Mock()
    processor = Mock()
    proto = DataDatagramProtocol(registry=registry, processor=processor, queue_maxsize=8)
    proto.connection_made(fake_transport)

    proto._process_datagram(packet, ("127.0.0.1", 12345))

    registry.note_parse_error.assert_called_once_with("010203040506")
    registry.update_from_data.assert_not_called()
    processor.ingest.assert_not_called()
    assert fake_transport.sent == []


@pytest.mark.asyncio
async def test_out_of_order_duplicate_packet_is_acked_but_not_ingested(
    fake_transport,
    drain_queue,
) -> None:
    registry = Mock()
    registry.update_from_data.side_effect = [
        DataUpdateResult(),
        DataUpdateResult(is_duplicate=True),
    ]
    registry.get.return_value = SimpleNamespace(sample_rate_hz=800)
    processor = Mock()
    proto = DataDatagramProtocol(registry=registry, processor=processor, queue_maxsize=8)
    proto.connection_made(fake_transport)

    newest = _valid_packet(seq=42)
    older = _valid_packet(seq=41)
    proto.datagram_received(newest, ("127.0.0.1", 12345))
    proto.datagram_received(older, ("127.0.0.1", 12345))

    await drain_queue(proto)

    assert processor.ingest.call_count == 1
    acked_sequences = [
        parse_data_ack(data).last_seq_received for data, _addr in fake_transport.sent
    ]
    assert acked_sequences == [42, 41]
    assert [call.args[0].seq for call in registry.update_from_data.call_args_list] == [42, 41]


@pytest.mark.asyncio
async def test_ack_send_failure_logs_and_continues_draining_queue(
    caplog: pytest.LogCaptureFixture,
    drain_queue,
) -> None:
    registry = Mock()
    registry.update_from_data.side_effect = [DataUpdateResult(), DataUpdateResult()]
    registry.get.return_value = SimpleNamespace(sample_rate_hz=800)
    processor = Mock()
    transport = _FailFirstTransport()
    proto = DataDatagramProtocol(registry=registry, processor=processor, queue_maxsize=8)
    proto.connection_made(transport)

    proto.datagram_received(_valid_packet(seq=1), ("127.0.0.1", 12345))
    proto.datagram_received(_valid_packet(seq=2), ("127.0.0.1", 12345))

    with caplog.at_level(logging.WARNING, logger="vibesensor.adapters.udp.udp_data_rx"):
        await drain_queue(proto)

    assert processor.ingest.call_count == 2
    assert [parse_data_ack(data).last_seq_received for data, _addr in transport.sent] == [2]
    assert any("failed to send DATA_ACK" in record.message for record in caplog.records)
