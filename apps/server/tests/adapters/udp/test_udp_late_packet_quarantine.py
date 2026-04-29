"""Late UDP DATA packets stay out of the live ring buffer."""

from __future__ import annotations

from unittest.mock import Mock, patch

import numpy as np
import pytest

from vibesensor.adapters.udp.protocol import HelloMessage, pack_data, parse_data_ack
from vibesensor.adapters.udp.udp_data_rx import DataDatagramProtocol
from vibesensor.infra.processing import SignalProcessor
from vibesensor.infra.runtime.registry import ClientRegistry

_CLIENT_ID = bytes.fromhex("aabbccddeeff")
_ADDR = ("127.0.0.1", 12345)


def _make_processor() -> SignalProcessor:
    return SignalProcessor(
        sample_rate_hz=800,
        waveform_seconds=8,
        waveform_display_hz=100,
        fft_n=1024,
        spectrum_max_hz=200,
    )


def _wave_chunk(freq_hz: float) -> np.ndarray:
    time_axis = np.arange(1024, dtype=np.float64) / 800.0
    wave = np.round(1200.0 * np.sin(2.0 * np.pi * freq_hz * time_axis)).astype(np.int16)
    zeros = np.zeros(1024, dtype=np.int16)
    return np.column_stack([wave, zeros, zeros])


@pytest.mark.asyncio
async def test_late_packet_is_quarantined_to_raw_capture_only(
    fake_transport,
    drain_queue,
) -> None:
    registry = ClientRegistry()
    registry.update_from_hello(
        HelloMessage(
            client_id=_CLIENT_ID,
            control_port=9010,
            sample_rate_hz=800,
            name="node-1",
            firmware_version="fw",
        ),
        _ADDR,
        now=1.0,
    )
    processor = _make_processor()
    raw_capture_sink = Mock()
    proto = DataDatagramProtocol(
        registry=registry,
        processor=processor,
        raw_capture_sink=raw_capture_sink,
        queue_maxsize=8,
    )
    proto.connection_made(fake_transport)

    first = pack_data(_CLIENT_ID, seq=0, t0_us=1_000_000, samples=_wave_chunk(50.0))
    newest = pack_data(_CLIENT_ID, seq=2, t0_us=2_280_000, samples=_wave_chunk(120.0))
    late = pack_data(_CLIENT_ID, seq=1, t0_us=1_640_000, samples=_wave_chunk(30.0))

    with patch.object(processor, "ingest", wraps=processor.ingest) as ingest_spy:
        proto.datagram_received(first, _ADDR)
        proto.datagram_received(newest, _ADDR)
        await drain_queue(proto)
        metrics_before = processor.compute_metrics("aabbccddeeff", sample_rate_hz=800)
        latest_before = processor.latest_sample_xyz("aabbccddeeff")

        proto.datagram_received(late, _ADDR)
        await drain_queue(proto)
        metrics_after = processor.compute_metrics("aabbccddeeff", sample_rate_hz=800)
        latest_after = processor.latest_sample_xyz("aabbccddeeff")

    peaks_before = metrics_before.get("combined", {}).get("peaks", [])
    peaks_after = metrics_after.get("combined", {}).get("peaks", [])
    assert any(abs(float(peak["hz"]) - 120.0) < 2.0 for peak in peaks_before)
    assert any(abs(float(peak["hz"]) - 120.0) < 2.0 for peak in peaks_after)
    assert not any(abs(float(peak["hz"]) - 30.0) < 2.0 for peak in peaks_after)
    assert latest_before == latest_after
    assert ingest_spy.call_count == 2
    assert raw_capture_sink.capture_raw_samples.call_count == 3
    raw_capture_sink.note_late_packet_loss.assert_called_once_with(client_id="aabbccddeeff")
    assert [parse_data_ack(data).last_seq_received for data, _addr in fake_transport.sent] == [
        0,
        2,
        1,
    ]

    record = registry.get("aabbccddeeff")
    assert record is not None
    assert record.frames_total == 2
    assert record.frames_dropped == 1
    assert record.last_seq == 2
    assert record.last_t0_us == 2_280_000
