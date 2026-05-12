"""UDP data-receiver queueing, duplicate, and reset-handling regression coverage."""

from __future__ import annotations

import asyncio
import time as real_time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest
from test_support.tracing import configured_trace_output, read_trace_output

from vibesensor.adapters.udp.protocol import pack_data
from vibesensor.adapters.udp.udp_data_rx import DataDatagramProtocol
from vibesensor.infra.runtime.registry import DataUpdateResult
from vibesensor.shared.ingest_diagnostics import IngestDiagnosticsCollector


class RecordingRegistry:
    def __init__(
        self,
        *,
        results: list[DataUpdateResult] | None = None,
        sample_rate_hz: int | None = 800,
        update_error: Exception | None = None,
    ) -> None:
        self._results = list(results or [])
        self._sample_rate_hz = sample_rate_hz
        self._update_error = update_error
        self.update_calls: list[tuple[object, tuple[str, int], float]] = []
        self.queue_drops: list[str | None] = []
        self.parse_errors: list[str | None] = []

    def update_from_data(self, msg, addr: tuple[str, int], now_ts: float) -> DataUpdateResult:
        self.update_calls.append((msg, addr, now_ts))
        if self._update_error is not None:
            raise self._update_error
        if self._results:
            return self._results.pop(0)
        return DataUpdateResult()

    def get(self, _client_id: str):
        return SimpleNamespace(sample_rate_hz=self._sample_rate_hz)

    def note_server_queue_drop(self, client_id: str | None) -> None:
        self.queue_drops.append(client_id)

    def note_parse_error(self, client_id: str | None) -> None:
        self.parse_errors.append(client_id)


class RecordingProcessor:
    def __init__(self) -> None:
        self.ingested: list[tuple[str, np.ndarray, int | None, int]] = []
        self.flushed: list[str] = []

    def ingest(
        self,
        client_id: str,
        samples: np.ndarray,
        *,
        sample_rate_hz: int | None,
        t0_us: int,
    ) -> None:
        self.ingested.append((client_id, samples, sample_rate_hz, t0_us))

    def flush_client_buffer(self, client_id: str) -> None:
        self.flushed.append(client_id)


class RecordingRawCaptureSink:
    def __init__(self) -> None:
        self.captured: list[tuple[str, int | None, int, np.ndarray]] = []
        self.late_losses: list[str] = []

    def capture_raw_samples(
        self,
        *,
        client_id: str,
        sample_rate_hz: int | None,
        t0_us: int,
        samples: np.ndarray,
    ) -> None:
        self.captured.append((client_id, sample_rate_hz, t0_us, samples))

    def note_late_packet_loss(self, *, client_id: str) -> None:
        self.late_losses.append(client_id)


@pytest.mark.asyncio
async def test_datagram_received_queues_work_before_processing(fake_transport, drain_queue) -> None:
    registry = RecordingRegistry()
    processor = RecordingProcessor()
    proto = DataDatagramProtocol(registry=registry, processor=processor, queue_maxsize=8)
    proto.connection_made(fake_transport)
    pkt = pack_data(
        bytes.fromhex("010203040506"),
        seq=1,
        t0_us=123,
        samples=np.zeros((4, 3), dtype=np.int16),
    )

    proto.datagram_received(pkt, ("127.0.0.1", 12345))
    assert processor.ingested == []

    await drain_queue(proto, timeout=1.0)
    assert len(processor.ingested) == 1


@pytest.mark.asyncio
async def test_parse_to_ingest_keeps_representative_sensor_frames_as_read_only_views(
    fake_transport,
    drain_queue,
) -> None:
    registry = RecordingRegistry(
        results=[
            DataUpdateResult(),
            DataUpdateResult(),
            DataUpdateResult(),
        ],
    )
    processor = RecordingProcessor()
    raw_capture_sink = RecordingRawCaptureSink()
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

    assert len(processor.ingested) == 3
    assert len(raw_capture_sink.captured) == 3
    for ingest_record, raw_capture_record in zip(
        processor.ingested,
        raw_capture_sink.captured,
        strict=True,
    ):
        ingest_samples = ingest_record[1]
        raw_capture_samples = raw_capture_record[3]
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
    registry = RecordingRegistry()
    processor = RecordingProcessor()
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
    assert len(processor.ingested) == 1
    assert registry.queue_drops == ["010203040506"]
    assert registry.parse_errors == []


def test_ingest_diagnostics_tracks_udp_backpressure() -> None:
    registry = RecordingRegistry()
    processor = RecordingProcessor()
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
    registry = RecordingRegistry(results=[DataUpdateResult(), DataUpdateResult()])
    processor = RecordingProcessor()
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


def test_datagram_queue_backpressure_rate_limits_drop_warnings(
    caplog: pytest.LogCaptureFixture,
) -> None:
    registry = RecordingRegistry()
    processor = RecordingProcessor()
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

    caplog.set_level("WARNING", logger="vibesensor.adapters.udp.udp_data_rx")
    with patch(
        "vibesensor.adapters.udp.udp_data_rx.time.monotonic",
        side_effect=_fake_monotonic,
    ):
        proto.datagram_received(pkt, ("127.0.0.1", 10002))
        proto.datagram_received(pkt, ("127.0.0.1", 10003))
        proto.datagram_received(pkt, ("127.0.0.1", 10004))
        proto.datagram_received(pkt, ("127.0.0.1", 10005))

    assert registry.queue_drops == ["010203040506"] * 4
    warnings = [
        record.message
        for record in caplog.records
        if "UDP ingest queue full; dropping packet" in record.message
    ]
    assert len(warnings) == 2
    assert "client=010203040506" in warnings[0]
    assert "suppressed 2 additional drop warnings" in warnings[1]


def test_datagram_received_ignores_empty_and_non_data_packets() -> None:
    registry = RecordingRegistry()
    processor = RecordingProcessor()
    proto = DataDatagramProtocol(registry=registry, processor=processor, queue_maxsize=4)

    proto.datagram_received(b"", ("127.0.0.1", 10001))
    proto.datagram_received(b"\x01not-data", ("127.0.0.1", 10001))

    assert registry.queue_drops == []
    assert registry.parse_errors == []
    assert registry.update_calls == []
    assert processor.ingested == []


@pytest.mark.asyncio
async def test_process_queue_propagates_unexpected_exception(
    fake_transport,
) -> None:
    registry = RecordingRegistry(update_error=RuntimeError("boom"))
    processor = RecordingProcessor()
    proto = DataDatagramProtocol(registry=registry, processor=processor, queue_maxsize=8)
    proto.connection_made(fake_transport)

    cid = bytes.fromhex("aabbccddeeff")
    pkt = pack_data(cid, seq=1, t0_us=100, samples=np.zeros((4, 3), dtype=np.int16))

    proto.datagram_received(pkt, ("127.0.0.1", 12345))

    consumer = asyncio.create_task(proto.process_queue())
    with pytest.raises(RuntimeError, match="boom"):
        await asyncio.wait_for(consumer, timeout=1.0)
    assert processor.ingested == []


@pytest.mark.asyncio
async def test_process_queue_propagates_parse_bug(
    fake_transport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = RecordingRegistry()
    processor = RecordingProcessor()
    proto = DataDatagramProtocol(registry=registry, processor=processor, queue_maxsize=8)
    proto.connection_made(fake_transport)

    def raise_runtime_error(_data: bytes):
        raise RuntimeError("parse bug")

    monkeypatch.setattr("vibesensor.adapters.udp.udp_data_rx.parse_data", raise_runtime_error)

    proto.datagram_received(b"\x02\x01", ("127.0.0.1", 12345))
    consumer = asyncio.create_task(proto.process_queue())
    with pytest.raises(RuntimeError, match="parse bug"):
        await asyncio.wait_for(consumer, timeout=1.0)

    assert registry.parse_errors == []


@pytest.mark.asyncio
async def test_reset_detected_flushes_buffer_before_ingest(
    fake_transport,
    drain_queue,
) -> None:
    registry = RecordingRegistry(
        results=[DataUpdateResult(reset_detected=True)],
        sample_rate_hz=1600,
    )
    processor = RecordingProcessor()
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

    assert processor.flushed == ["010203040506"]
    assert len(processor.ingested) == 1
    assert len(fake_transport.sent) == 1


@pytest.mark.asyncio
async def test_process_queue_exports_trace_span(
    fake_transport,
    drain_queue,
    tmp_path: Path,
) -> None:
    registry = RecordingRegistry(
        results=[DataUpdateResult(reset_detected=True)],
        sample_rate_hz=1600,
    )
    processor = RecordingProcessor()
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
