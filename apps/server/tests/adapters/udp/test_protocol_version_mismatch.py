"""Version-mismatch coverage across UDP packet parsers and datagram protocols."""

from __future__ import annotations

import logging
from unittest.mock import Mock

import numpy as np
import pytest

from vibesensor.adapters.udp.protocol import (
    pack_ack,
    pack_cmd_identify,
    pack_data,
    pack_data_ack,
    pack_hello,
    pack_hello_ack,
    parse_ack,
    parse_cmd,
    parse_data,
    parse_data_ack,
    parse_hello,
    parse_hello_ack,
)
from vibesensor.adapters.udp.protocol_validator import ProtocolVersionMismatch
from vibesensor.adapters.udp.udp_control_tx import ControlDatagramProtocol
from vibesensor.adapters.udp.udp_data_rx import DataDatagramProtocol


@pytest.mark.parametrize(
    ("packet", "parser", "message"),
    [
        (
            pack_hello(bytes.fromhex("aabbccddeeff"), 9010, 800, "node"),
            parse_hello,
            "HELLO version mismatch: expected 1, got 2",
        ),
        (
            pack_data(
                bytes.fromhex("aabbccddeeff"),
                seq=7,
                t0_us=11,
                samples=np.zeros((1, 3), dtype=np.int16),
            ),
            parse_data,
            "DATA version mismatch: expected 1, got 2",
        ),
        (
            pack_cmd_identify(bytes.fromhex("aabbccddeeff"), cmd_seq=9, duration_ms=500),
            parse_cmd,
            "CMD version mismatch: expected 1, got 2",
        ),
        (
            pack_ack(bytes.fromhex("aabbccddeeff"), cmd_seq=5, status=0),
            parse_ack,
            "ACK version mismatch: expected 1, got 2",
        ),
        (
            pack_data_ack(bytes.fromhex("aabbccddeeff"), last_seq_received=42),
            parse_data_ack,
            "DATA_ACK version mismatch: expected 1, got 2",
        ),
        (
            pack_hello_ack(bytes.fromhex("aabbccddeeff")),
            parse_hello_ack,
            "HELLO_ACK version mismatch: expected 1, got 2",
        ),
    ],
    ids=["hello", "data", "cmd", "ack", "data-ack", "hello-ack"],
)
def test_parse_reports_explicit_version_mismatch(
    packet: bytes,
    parser,
    message: str,
) -> None:
    mismatched = bytearray(packet)
    mismatched[1] = 2

    with pytest.raises(ProtocolVersionMismatch, match=message):
        parser(bytes(mismatched))


def test_control_datagram_version_mismatch_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    registry = Mock()
    protocol = ControlDatagramProtocol(registry)
    packet = bytearray(pack_hello(bytes.fromhex("aabbccddeeff"), 9010, 800, "node"))
    packet[1] = 2

    with caplog.at_level(logging.WARNING):
        protocol.datagram_received(bytes(packet), ("127.0.0.1", 54000))

    registry.note_parse_error.assert_called_once_with("aabbccddeeff")
    assert "Control protocol version mismatch" in caplog.text
    assert "expected 1, got 2" in caplog.text


@pytest.mark.asyncio
async def test_data_datagram_version_mismatch_logs_warning(
    caplog: pytest.LogCaptureFixture,
    fake_transport,
    drain_queue,
) -> None:
    registry = Mock()
    processor = Mock()
    proto = DataDatagramProtocol(registry=registry, processor=processor, queue_maxsize=8)
    proto.connection_made(fake_transport)
    packet = bytearray(
        pack_data(
            bytes.fromhex("aabbccddeeff"),
            seq=1,
            t0_us=10,
            samples=np.zeros((1, 3), dtype=np.int16),
        ),
    )
    packet[1] = 2

    with caplog.at_level(logging.WARNING):
        proto.datagram_received(bytes(packet), ("127.0.0.1", 12345))
        await drain_queue(proto)

    registry.note_parse_error.assert_called_once_with("aabbccddeeff")
    registry.update_from_data.assert_not_called()
    processor.ingest.assert_not_called()
    assert fake_transport.sent == []
    assert "DATA version mismatch" in caplog.text
