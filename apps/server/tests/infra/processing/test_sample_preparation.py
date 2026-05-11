"""Focused tests for processing sample-preparation seams."""

from __future__ import annotations

import numpy as np
import pytest

from vibesensor.infra.processing.buffer_mutations import ClientBufferMutator
from vibesensor.infra.processing.buffers import ClientBuffer
from vibesensor.infra.processing.fft_preparation import prepare_fft_windows
from vibesensor.infra.processing.models import MetricsSnapshot, ProcessorConfig
from vibesensor.infra.processing.sample_validation import normalize_sample_chunk
from vibesensor.infra.processing.snapshot_window_preparation import prepare_snapshot_windows


def _config(**overrides: object) -> ProcessorConfig:
    base = {
        "sample_rate_hz": 200,
        "waveform_seconds": 2,
        "waveform_display_hz": 50,
        "fft_n": 4,
        "spectrum_min_hz": 0.0,
        "spectrum_max_hz": 100.0,
        "accel_scale_g_per_lsb": None,
    }
    base.update(overrides)
    return ProcessorConfig(**base)


def test_normalize_sample_chunk_scales_to_float32() -> None:
    raw = np.array([[2, 4, 6]], dtype=np.int16)

    chunk = normalize_sample_chunk(
        client_id="sensor-1",
        samples=raw,
        accel_scale_g_per_lsb=0.5,
    )

    assert chunk is not None
    assert chunk.dtype == np.float32
    np.testing.assert_allclose(chunk, np.array([[1.0, 2.0, 3.0]], dtype=np.float32))


def test_normalize_sample_chunk_drops_malformed_shape(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING", logger="vibesensor.infra.processing.sample_validation"):
        chunk = normalize_sample_chunk(
            client_id="sensor-bad",
            samples=np.array([1.0, 2.0, 3.0], dtype=np.float32),
            accel_scale_g_per_lsb=None,
        )

    assert chunk is None
    assert "Dropping malformed sample chunk for sensor-bad with shape (3,)" in caplog.text


def test_prepare_snapshot_windows_reuses_fft_block_for_short_time_window() -> None:
    config = _config(sample_rate_hz=8, waveform_seconds=1, fft_n=4)
    mutator = ClientBufferMutator(config)
    buf = ClientBuffer(data=np.arange(36, dtype=np.float32).reshape(3, 12), capacity=12)
    buf.count = 12
    buf.write_idx = 0

    prepared = prepare_snapshot_windows(
        buf=buf,
        config=config,
        buffer_mutator=mutator,
        sample_rate_hz=2,
    )

    assert prepared.time_window.shape == (3, 2)
    assert prepared.fft_block is not None
    assert prepared.fft_block.shape == (3, 4)
    assert np.shares_memory(prepared.time_window, prepared.fft_block)
    np.testing.assert_array_equal(prepared.time_window, prepared.fft_block[:, -2:])


def test_prepare_fft_windows_filters_and_detrends_time_window() -> None:
    block = np.array(
        [
            [1.0, 1.0, 9.0, 1.0, 1.0],
            [2.0, 2.0, 2.0, 2.0, 2.0],
            [0.0, 1.0, 0.0, 1.0, 0.0],
        ],
        dtype=np.float32,
    )
    snapshot = MetricsSnapshot(
        client_id="sensor-fft",
        sample_rate_hz=200,
        ingest_generation=1,
        time_window=block,
        fft_block=None,
    )

    prepared = prepare_fft_windows(snapshot)

    expected_filtered = np.array(
        [
            [1.0, 1.0, 1.0, 1.0, 1.0],
            [2.0, 2.0, 2.0, 2.0, 2.0],
            [0.0, 0.0, 1.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    np.testing.assert_allclose(prepared.time_window, expected_filtered)
    assert prepared.fft_input is None
    np.testing.assert_allclose(
        np.mean(prepared.time_window_detrended, axis=1),
        np.zeros(3),
        atol=1e-7,
    )
