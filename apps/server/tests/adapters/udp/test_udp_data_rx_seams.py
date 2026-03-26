"""Focused seam coverage for UDP data-message parsing and dispatch helpers."""

from __future__ import annotations

from unittest.mock import Mock

import numpy as np
import pytest

from vibesensor.adapters.udp.protocol import DataMessage
from vibesensor.adapters.udp.udp_data_rx import DataDatagramProtocol


def test_parse_data_message_marks_registry_on_protocol_error(fake_transport) -> None:
    registry = Mock()
    processor = Mock()
    proto = DataDatagramProtocol(registry=registry, processor=processor, queue_maxsize=8)
    proto.connection_made(fake_transport)

    result = proto._parse_data_message(b"\x02\x01", ("127.0.0.1", 12345))

    assert result is None
    registry.note_parse_error.assert_called_once()
    registry.update_from_data.assert_not_called()
    assert fake_transport.sent == []


def test_dispatch_data_message_logs_processing_error_without_parse_step(
    fake_transport,
    caplog: pytest.LogCaptureFixture,
) -> None:
    registry = Mock()
    registry.update_from_data.side_effect = ValueError("boom")
    processor = Mock()
    proto = DataDatagramProtocol(registry=registry, processor=processor, queue_maxsize=8)
    proto.connection_made(fake_transport)
    msg = DataMessage(
        client_id=bytes.fromhex("aabbccddeeff"),
        seq=1,
        t0_us=100,
        sample_count=4,
        samples=np.zeros((4, 3), dtype=np.int16),
    )

    with caplog.at_level("WARNING", logger="vibesensor.adapters.udp.udp_data_rx"):
        proto._dispatch_data_message(msg, ("127.0.0.1", 12345))

    registry.update_from_data.assert_called_once()
    processor.ingest.assert_not_called()
    assert "client=aabbccddeeff" in caplog.text
