from __future__ import annotations

import math
from math import pi
from typing import cast

import numpy as np

from vibesensor.infra.processing.buffers import ClientBuffer
from vibesensor.infra.processing.compute import SignalMetricsComputer
from vibesensor.infra.processing.models import DebugSpectrumRequest, ProcessorConfig
from vibesensor.infra.processing.payload import (
    build_debug_spectrum_payload,
    build_intake_stats_payload,
    build_time_alignment_payload,
)


def _config(fft_n: int = 256) -> ProcessorConfig:
    return ProcessorConfig(
        sample_rate_hz=200,
        waveform_seconds=2,
        waveform_display_hz=50,
        fft_n=fft_n,
        spectrum_min_hz=0.0,
        spectrum_max_hz=100.0,
        accel_scale_g_per_lsb=None,
    )


def test_build_debug_spectrum_payload_returns_insufficient_samples_error() -> None:
    config = _config(fft_n=512)
    request = DebugSpectrumRequest(
        client_id="c1",
        sample_rate_hz=200,
        count=0,
        fft_block=None,
    )
    metrics = SignalMetricsComputer(config)

    result = build_debug_spectrum_payload(request, config, metrics)

    assert result == {"error": "insufficient samples", "count": 0, "fft_n": 512}


def test_build_debug_spectrum_payload_returns_debug_metadata() -> None:
    config = _config(fft_n=256)
    metrics = SignalMetricsComputer(config)
    t = np.arange(config.fft_n, dtype=np.float32) / config.sample_rate_hz
    signal = 0.02 * np.sin(2.0 * pi * 20.0 * t)
    fft_block = np.column_stack([signal, signal * 0.5, signal * 0.25]).T.astype(np.float32)
    request = DebugSpectrumRequest(
        client_id="c1",
        sample_rate_hz=config.sample_rate_hz,
        count=config.fft_n,
        fft_block=fft_block,
    )

    result = build_debug_spectrum_payload(request, config, metrics)

    assert "error" not in result
    assert result["client_id"] == "c1"
    assert result["fft_n"] == config.fft_n
    assert result["window"] == "hann"
    assert result["freq_bins"] > 0
    assert result["freq_resolution_hz"] == config.sample_rate_hz / config.fft_n
    assert math.isfinite(result["vibration_strength_db"])
    assert len(result["top_bins_by_amplitude"]) <= 10
    assert len(result["raw_stats"]["mean_g"]) == 3
    assert len(result["detrended_std_g"]) == 3


def test_build_intake_stats_payload_adds_worker_pool_stats() -> None:
    base_stats = {
        "total_ingested_samples": 10,
        "total_compute_calls": 2,
        "last_compute_duration_s": 0.1,
        "last_compute_all_duration_s": 0.2,
        "last_ingest_duration_s": 0.05,
    }
    worker_pool_stats = {
        "active_workers": 1,
        "total_tasks": 7,
    }

    payload = build_intake_stats_payload(base_stats, worker_pool_stats)

    assert payload["total_ingested_samples"] == 10
    assert payload["worker_pool"] == worker_pool_stats
    assert "worker_pool" not in base_stats


def test_build_time_alignment_payload_handles_overlap_and_exclusions() -> None:
    buf1 = cast(ClientBuffer, object())
    buf2 = cast(ClientBuffer, object())
    buffers = {"s1": buf1, "s2": buf2}

    def _analysis_time_range(buf: ClientBuffer) -> tuple[float, float, bool] | None:
        if buf is buf1:
            return (10.0, 12.0, True)
        if buf is buf2:
            return (11.0, 13.0, False)
        return None

    payload = build_time_alignment_payload(
        buffers,
        ["s1", "missing", "s2"],
        analysis_time_range_fn=_analysis_time_range,
    )

    assert payload["sensors_included"] == ["s1", "s2"]
    assert payload["sensors_excluded"] == ["missing"]
    assert payload["aligned"] is False
    assert payload["clock_synced"] is False
    assert payload["shared_window"] is not None
    assert payload["shared_window"]["duration_s"] == 1.0
    assert payload["overlap_ratio"] == 0.3333


def test_build_time_alignment_payload_single_sensor_is_trivially_aligned() -> None:
    buf = cast(ClientBuffer, object())

    payload = build_time_alignment_payload(
        {"s1": buf},
        ["s1"],
        analysis_time_range_fn=lambda _: (5.0, 7.0, True),
    )

    assert payload["aligned"] is True
    assert payload["clock_synced"] is True
    assert payload["shared_window"] is None
    assert payload["overlap_ratio"] == 1.0
