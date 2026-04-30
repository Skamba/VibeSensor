"""UDP data-receiver queueing, duplicate, and reset-handling regression coverage."""

from __future__ import annotations

import asyncio
import time as real_time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import pytest
from test_support.tracing import configured_trace_output, read_trace_output

from vibesensor.adapters.udp.protocol import pack_data
from vibesensor.adapters.udp.udp_data_rx import DataDatagramProtocol
from vibesensor.infra.runtime.registry import DataUpdateResult
from vibesensor.shared.ingest_diagnostics import IngestDiagnosticsCollector


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


@pytest.mark.asyncio
async def test_parse_to_ingest_keeps_representative_sensor_frames_as_read_only_views(
    fake_transport,
    drain_queue,
) -> None:
    registry = Mock()
    registry.update_from_data.side_effect = [
        DataUpdateResult(),
        DataUpdateResult(),
        DataUpdateResult(),
    ]
    registry.get.return_value = SimpleNamespace(sample_rate_hz=800)
    processor = Mock()
    raw_capture_sink = Mock()
    proto = DataDatagramProtocol(
        registry=registry,
        processor=processor,
        raw_capture_sink=raw_capture_sink,
        queue_maxsize=8,
    )
    proto.connection_made(fake_transport)

    frame_samples = 200
    for sensor_index, client_id in enumerate(
        (
            bytes.fromhex("010203040506"),
            bytes.fromhex("112233445566"),
            bytes.fromhex("aabbccddeeff"),
        )
    ):
        samples = (
            np.arange(frame_samples * 3, dtype=np.int16).reshape(frame_samples, 3) + sensor_index
        )
        proto.datagram_received(
            pack_data(client_id, seq=sensor_index + 1, t0_us=100_000, samples=samples),
            ("127.0.0.1", 10001 + sensor_index),
        )

    await drain_queue(proto, timeout=1.0)

    assert processor.ingest.call_count == 3
    assert raw_capture_sink.capture_raw_samples.call_count == 3
    for ingest_call, raw_capture_call in zip(
        processor.ingest.call_args_list,
        raw_capture_sink.capture_raw_samples.call_args_list,
        strict=True,
    ):
        ingest_samples = ingest_call.args[1]
        raw_capture_samples = raw_capture_call.kwargs["samples"]
        assert ingest_samples is raw_capture_samples
        assert ingest_samples.shape == (frame_samples, 3)
        assert ingest_samples.dtype == np.dtype("<i2")
        assert ingest_samples.flags.owndata is False
        assert ingest_samples.flags.writeable is False


@pytest.mark.asyncio
async def test_datagram_queue_backpressure_drops_when_full(
    fake_transport,
    drain_queue,
) -> None:
    registry = Mock()
    registry.update_from_data.return_value = DataUpdateResult()
    registry.get.return_value = SimpleNamespace(sample_rate_hz=800)
    processor = Mock()
    proto = DataDatagramProtocol(registry=registry, processor=processor, queue_maxsize=1)
    proto.connection_made(fake_transport)
    pkt = pack_data(
        bytes.fromhex("010203040506"),
        seq=1,
        t0_us=1,
        samples=np.zeros((1, 3), dtype=np.int16),
    )
    proto.datagram_received(pkt, ("127.0.0.1", 10001))
    proto.datagram_received(pkt, ("127.0.0.1", 10002))
    await drain_queue(proto)
    assert processor.ingest.call_count == 1
    registry.note_server_queue_drop.assert_called_once_with("010203040506")
    registry.note_parse_error.assert_not_called()


def test_ingest_diagnostics_tracks_udp_backpressure() -> None:
    registry = Mock()
    processor = Mock()
    ingest_diagnostics = IngestDiagnosticsCollector()
    proto = DataDatagramProtocol(
        registry=registry,
        processor=processor,
        ingest_diagnostics=ingest_diagnostics,
        queue_maxsize=1,
    )
    client_id = bytes.fromhex("010203040506")
    packet_one = pack_data(
        client_id,
        seq=1,
        t0_us=100_000,
        samples=np.zeros((4, 3), dtype=np.int16),
    )
    packet_two = pack_data(
        client_id,
        seq=2,
        t0_us=200_000,
        samples=np.zeros((4, 3), dtype=np.int16),
    )

    proto.datagram_received(packet_one, ("127.0.0.1", 10001))
    proto.datagram_received(packet_two, ("127.0.0.1", 10002))

    udp_snapshot = ingest_diagnostics.udp_snapshot()
    assert udp_snapshot.queue_max_depth == 1
    assert udp_snapshot.dropped_datagrams == 1


@pytest.mark.asyncio
async def test_ingest_diagnostics_tracks_client_timing(
    fake_transport,
    drain_queue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = Mock()
    registry.update_from_data.side_effect = [DataUpdateResult(), DataUpdateResult()]
    registry.get.return_value = SimpleNamespace(sample_rate_hz=800)
    processor = Mock()
    ingest_diagnostics = IngestDiagnosticsCollector()
    proto = DataDatagramProtocol(
        registry=registry,
        processor=processor,
        ingest_diagnostics=ingest_diagnostics,
        queue_maxsize=8,
    )
    proto.connection_made(fake_transport)
    client_id = bytes.fromhex("010203040506")
    packet_one = pack_data(
        client_id,
        seq=1,
        t0_us=100_000,
        samples=np.zeros((4, 3), dtype=np.int16),
    )
    packet_two = pack_data(
        client_id,
        seq=2,
        t0_us=200_000,
        samples=np.zeros((4, 3), dtype=np.int16),
    )

    monotonic_ticks = iter([10.000, 10.030, 10.010, 10.020, 10.050, 10.080])
    monkeypatch.setattr(
        "vibesensor.adapters.udp.udp_data_rx.time",
        SimpleNamespace(
            monotonic=lambda: next(monotonic_ticks, 10.080),
            time=real_time.time,
        ),
    )

    proto.datagram_received(packet_one, ("127.0.0.1", 10001))
    proto.datagram_received(packet_two, ("127.0.0.1", 10001))
    await drain_queue(proto)

    udp_snapshot = ingest_diagnostics.udp_snapshot()
    client_snapshot = ingest_diagnostics.client_snapshots()["010203040506"]
    assert udp_snapshot.processed_datagrams == 2
    assert udp_snapshot.max_packet_queue_age_ms == pytest.approx(20.0, abs=0.001)
    assert udp_snapshot.max_ack_latency_ms == pytest.approx(50.0, abs=0.001)
    assert client_snapshot.processed_packets == 2
    assert client_snapshot.processed_samples == 8
    assert client_snapshot.estimated_ingest_hz == pytest.approx(66.667, abs=0.001)
    assert client_snapshot.last_packet_queue_age_ms == pytest.approx(20.0, abs=0.001)
    assert client_snapshot.last_ack_latency_ms == pytest.approx(50.0, abs=0.001)


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
    monotonic_ticks = iter([0.0, 100.0, 0.0, 101.0, 0.0, 102.0, 0.0, 115.0])

    def _fake_monotonic() -> float:
        return next(monotonic_ticks, 116.0)

    with (
        patch(
            "vibesensor.adapters.udp.udp_data_rx.time.monotonic",
            side_effect=_fake_monotonic,
        ),
        patch("vibesensor.adapters.udp.udp_data_rx.LOGGER.warning") as warning_log,
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

    registry.note_server_queue_drop.assert_not_called()
    registry.note_parse_error.assert_not_called()
    registry.update_from_data.assert_not_called()
    processor.ingest.assert_not_called()


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


@pytest.mark.asyncio
async def test_process_queue_propagates_unexpected_exception(
    fake_transport,
) -> None:
    registry = Mock()
    registry.update_from_data.side_effect = RuntimeError("boom")
    processor = Mock()
    proto = DataDatagramProtocol(registry=registry, processor=processor, queue_maxsize=8)
    proto.connection_made(fake_transport)

    cid = bytes.fromhex("aabbccddeeff")
    pkt = pack_data(cid, seq=1, t0_us=100, samples=np.zeros((4, 3), dtype=np.int16))

    proto.datagram_received(pkt, ("127.0.0.1", 12345))

    consumer = asyncio.create_task(proto.process_queue())
    with pytest.raises(RuntimeError, match="boom"):
        await asyncio.wait_for(consumer, timeout=1.0)
    assert processor.ingest.call_count == 0


@pytest.mark.asyncio
async def test_malformed_data_packet_marks_registry_and_skips_ack(
    fake_transport,
    drain_queue,
) -> None:
    registry = Mock()
    processor = Mock()
    proto = DataDatagramProtocol(registry=registry, processor=processor, queue_maxsize=8)
    proto.connection_made(fake_transport)

    proto.datagram_received(b"\x02\x01", ("127.0.0.1", 12345))
    await drain_queue(proto)

    registry.note_parse_error.assert_called_once()
    registry.update_from_data.assert_not_called()
    processor.ingest.assert_not_called()
    assert fake_transport.sent == []


@pytest.mark.asyncio
async def test_process_queue_propagates_parse_bug(
    fake_transport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = Mock()
    processor = Mock()
    proto = DataDatagramProtocol(registry=registry, processor=processor, queue_maxsize=8)
    proto.connection_made(fake_transport)

    def raise_runtime_error(_data: bytes):
        raise RuntimeError("parse bug")

    monkeypatch.setattr("vibesensor.adapters.udp.udp_data_rx.parse_data", raise_runtime_error)

    proto.datagram_received(b"\x02\x01", ("127.0.0.1", 12345))
    consumer = asyncio.create_task(proto.process_queue())
    with pytest.raises(RuntimeError, match="parse bug"):
        await asyncio.wait_for(consumer, timeout=1.0)

    registry.note_parse_error.assert_not_called()


@pytest.mark.asyncio
async def test_reset_detected_flushes_buffer_before_ingest(
    fake_transport,
    drain_queue,
) -> None:
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
    proto.datagram_received(pkt, ("127.0.0.1", 12345))
    await drain_queue(proto)

    processor.flush_client_buffer.assert_called_once_with("010203040506")
    processor.ingest.assert_called_once()
    assert len(fake_transport.sent) == 1


@pytest.mark.asyncio
async def test_process_queue_exports_trace_span(
    fake_transport,
    drain_queue,
    tmp_path: Path,
) -> None:
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

    with configured_trace_output(tmp_path) as trace_path:
        proto.datagram_received(pkt, ("127.0.0.1", 12345))
        await drain_queue(proto)

    span = next(
        item for item in read_trace_output(trace_path) if item["name"] == "udp.data.dispatch"
    )
    assert span["kind"] == "consumer"
    assert span["attributes"]["vibesensor.client_id"] == "010203040506"
    assert span["attributes"]["vibesensor.sample_count"] == 2
    assert span["attributes"]["vibesensor.reset_detected"] is True
