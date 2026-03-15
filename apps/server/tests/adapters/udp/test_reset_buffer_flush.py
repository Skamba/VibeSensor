"""Tests for FFT buffer flush on ESP32 sensor reset detection (issue #295)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from vibesensor.adapters.persistence.history_db import HistoryDB
from vibesensor.adapters.udp.protocol import DataMessage, pack_data
from vibesensor.adapters.udp.udp_data_rx import DataDatagramProtocol
from vibesensor.infra.processing import SignalProcessor
from vibesensor.infra.runtime.registry import ClientRegistry, DataUpdateResult, HelloMessage

# ---------------------------------------------------------------------------
# Unit: SignalProcessor.flush_client_buffer
# ---------------------------------------------------------------------------


def _make_processor(**kwargs) -> SignalProcessor:
    defaults = {
        "sample_rate_hz": 800,
        "waveform_seconds": 8,
        "waveform_display_hz": 100,
        "fft_n": 1024,
        "spectrum_max_hz": 200,
    }
    defaults.update(kwargs)
    return SignalProcessor(**defaults)


def test_flush_client_buffer_resets_count_and_write_idx() -> None:
    proc = _make_processor()
    _rng = np.random.default_rng(42)
    samples = _rng.standard_normal((500, 3)).astype(np.float32)
    proc.ingest("c1", samples, sample_rate_hz=800)

    buf = proc._store.buffers["c1"]
    assert buf.count == 500
    assert buf.write_idx == 500

    proc.flush_client_buffer("c1")

    assert buf.count == 0
    assert buf.write_idx == 0
    assert buf.latest_metrics == {}
    assert buf.latest_spectrum == {}
    assert buf.latest_strength_metrics["vibration_strength_db"] == 0.0
    # Data array should be zeroed
    assert np.all(buf.data == 0.0)


def test_flush_unknown_client_is_safe() -> None:
    proc = _make_processor()
    # Should not raise
    proc.flush_client_buffer("nonexistent")


def test_fft_waits_for_new_samples_after_flush() -> None:
    """After a flush the FFT should not be produced until fft_n new samples arrive."""
    fft_n = 1024
    proc = _make_processor(fft_n=fft_n)

    # Ingest enough for FFT
    _rng = np.random.default_rng(42)
    samples = _rng.standard_normal((fft_n, 3)).astype(np.float32)
    proc.ingest("c1", samples, sample_rate_hz=800)
    metrics = proc.compute_metrics("c1", sample_rate_hz=800)
    # Should have spectrum data
    assert metrics.get("combined", {}).get("peaks") is not None

    # Flush
    proc.flush_client_buffer("c1")

    # Ingest fewer than fft_n samples
    partial = np.random.default_rng(43).standard_normal((fft_n // 2, 3)).astype(np.float32)
    proc.ingest("c1", partial, sample_rate_hz=800)
    proc.compute_metrics("c1", sample_rate_hz=800)
    buf = proc._store.buffers["c1"]
    assert buf.count == fft_n // 2
    # Should NOT have spectrum peaks because count < fft_n
    assert buf.latest_spectrum == {}


def test_no_pre_reset_samples_contaminate_post_reset_fft() -> None:
    """Ensure pre-reset samples are gone and FFT is clean after flush + refill."""
    fft_n = 1024
    proc = _make_processor(fft_n=fft_n)

    # Ingest a strong 50 Hz signal (pre-reset)
    t = np.arange(fft_n, dtype=np.float64) / 800
    signal_50hz = (0.5 * np.sin(2 * np.pi * 50 * t)).astype(np.float32)
    zeros = np.zeros(fft_n, dtype=np.float32)
    pre_reset = np.stack([signal_50hz, zeros, zeros], axis=1)
    proc.ingest("c1", pre_reset, sample_rate_hz=800)

    pre_metrics = proc.compute_metrics("c1", sample_rate_hz=800)
    pre_peaks = pre_metrics.get("x", {}).get("peaks", [])
    assert any(abs(p["hz"] - 50.0) < 2.0 for p in pre_peaks), "Pre-reset should detect 50 Hz"

    # --- Sensor reset ---
    proc.flush_client_buffer("c1")

    # Ingest a pure 120 Hz signal (post-reset) — completely different
    signal_120hz = (0.5 * np.sin(2 * np.pi * 120 * t)).astype(np.float32)
    zeros = np.zeros(fft_n, dtype=np.float32)
    post_reset = np.stack([signal_120hz, zeros, zeros], axis=1)
    proc.ingest("c1", post_reset, sample_rate_hz=800)

    post_metrics = proc.compute_metrics("c1", sample_rate_hz=800)
    post_peaks = post_metrics.get("x", {}).get("peaks", [])
    # Should see 120 Hz, NOT 50 Hz residual
    assert any(abs(p["hz"] - 120.0) < 2.0 for p in post_peaks), "Post-reset should detect 120 Hz"
    # No residual 50 Hz peak
    assert not any(abs(p["hz"] - 50.0) < 2.0 for p in post_peaks), (
        "50 Hz should be gone after flush"
    )


# ---------------------------------------------------------------------------
# Shared constants / fixtures for registry reset tests
# ---------------------------------------------------------------------------

_CLIENT_ID = bytes.fromhex("aabbccddeeff")
_SAMPLES = np.zeros((200, 3), dtype=np.int16)
_ADDR = ("10.4.0.2", 50000)


def _data_msg(seq: int, t0_us: int) -> DataMessage:
    return DataMessage(
        client_id=_CLIENT_ID,
        seq=seq,
        t0_us=t0_us,
        sample_count=200,
        samples=_SAMPLES,
    )


@pytest.fixture
def registry_ctx(tmp_path):
    """Registry pre-registered with a single client."""
    db = HistoryDB(tmp_path / "history.db")
    registry = ClientRegistry(db=db)
    registry.update_from_hello(
        HelloMessage(
            client_id=_CLIENT_ID,
            control_port=9010,
            sample_rate_hz=800,
            name="node",
            firmware_version="fw",
        ),
        ("10.4.0.2", 9010),
        now=1.0,
    )
    return registry


# ---------------------------------------------------------------------------
# Unit: registry.update_from_data returns reset flag
# ---------------------------------------------------------------------------


def test_registry_update_from_data_returns_true_on_reset(registry_ctx) -> None:
    result1 = registry_ctx.update_from_data(_data_msg(5000, 1_000_000), _ADDR, now=2.0)
    assert result1.reset_detected is False

    result2 = registry_ctx.update_from_data(_data_msg(10, 1_250_000), _ADDR, now=3.0)
    assert result2.reset_detected is True


def test_registry_update_from_data_returns_false_on_normal_seq(registry_ctx) -> None:
    r1 = registry_ctx.update_from_data(_data_msg(100, 100_000), _ADDR, now=2.0)
    r2 = registry_ctx.update_from_data(_data_msg(101, 200_000), _ADDR, now=3.0)
    assert r1.reset_detected is False
    assert r2.reset_detected is False


# ---------------------------------------------------------------------------
# Integration: UDP handler flushes buffer on reset
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_udp_handler_flushes_buffer_on_sensor_reset(fake_transport, drain_queue) -> None:
    """Integration: when registry detects reset, processor buffer is flushed."""
    registry = Mock()
    processor = Mock()

    # First call: normal (no reset), second call: reset detected
    registry.update_from_data.side_effect = [
        DataUpdateResult(),
        DataUpdateResult(reset_detected=True),
    ]
    registry.get.return_value = SimpleNamespace(sample_rate_hz=800)

    proto = DataDatagramProtocol(registry=registry, processor=processor, queue_maxsize=8)
    proto.connection_made(fake_transport)

    cid = bytes.fromhex("010203040506")
    pkt1 = pack_data(cid, seq=5000, t0_us=100_000, samples=np.zeros((4, 3), dtype=np.int16))
    pkt2 = pack_data(cid, seq=10, t0_us=200_000, samples=np.zeros((4, 3), dtype=np.int16))

    proto.datagram_received(pkt1, ("127.0.0.1", 12345))
    proto.datagram_received(pkt2, ("127.0.0.1", 12345))

    await drain_queue(proto)

    # processor.ingest called twice
    assert processor.ingest.call_count == 2
    # flush_client_buffer called once (on the reset packet)
    assert processor.flush_client_buffer.call_count == 1
    flushed_client_id = processor.flush_client_buffer.call_args[0][0]
    assert flushed_client_id == cid.hex()


@pytest.mark.asyncio
async def test_udp_handler_no_flush_on_normal_data(fake_transport, drain_queue) -> None:
    """No buffer flush when there is no reset."""
    registry = Mock()
    processor = Mock()
    registry.update_from_data.return_value = DataUpdateResult()
    registry.get.return_value = SimpleNamespace(sample_rate_hz=800)

    proto = DataDatagramProtocol(registry=registry, processor=processor, queue_maxsize=8)
    proto.connection_made(fake_transport)

    cid = bytes.fromhex("010203040506")
    pkt = pack_data(cid, seq=100, t0_us=100_000, samples=np.zeros((4, 3), dtype=np.int16))
    proto.datagram_received(pkt, ("127.0.0.1", 12345))

    await drain_queue(proto)

    assert processor.ingest.call_count == 1
    assert processor.flush_client_buffer.call_count == 0
