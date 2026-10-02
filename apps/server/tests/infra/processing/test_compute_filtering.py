"""Ensure compute filtering reuses or isolates FFT inputs without double filtering."""

from __future__ import annotations

import numpy as np

from vibesensor.infra.processing.compute import SignalMetricsComputer
from vibesensor.infra.processing.models import MetricsSnapshot, ProcessorConfig
from vibesensor.vibration_strength import empty_vibration_strength_metrics


def _config(*, fft_n: int) -> ProcessorConfig:
    return ProcessorConfig(
        sample_rate_hz=800,
        waveform_seconds=8,
        waveform_display_hz=100,
        fft_n=fft_n,
        spectrum_min_hz=5.0,
        spectrum_max_hz=200.0,
        accel_scale_g_per_lsb=None,
    )


def _empty_fft_result() -> dict[str, object]:
    return {
        "freq_slice": np.array([], dtype=np.float32),
        "spectrum_by_axis": {},
        "combined_amp": np.array([], dtype=np.float32),
        "strength_metrics": empty_vibration_strength_metrics(),
        "axis_peaks": {"x": [], "y": [], "z": []},
    }


def test_compute_reuses_filtered_time_window_for_fft(monkeypatch) -> None:
    metrics = SignalMetricsComputer(_config(fft_n=4))
    time_window = np.arange(24, dtype=np.float32).reshape(3, 8)
    snapshot = MetricsSnapshot(
        client_id="client-1",
        sample_rate_hz=800,
        ingest_generation=1,
        time_window=time_window,
        fft_block=time_window[:, -4:].copy(),
    )
    filtered_time_window = np.full((3, 8), 7.0, dtype=np.float32)
    fft_calls: list[tuple[np.ndarray, bool]] = []

    def _fake_medfilt3(block: np.ndarray) -> np.ndarray:
        np.testing.assert_array_equal(block, time_window)
        return filtered_time_window

    def _fake_compute_fft_spectrum(
        fft_block: np.ndarray,
        sample_rate_hz: int,
        **kwargs: object,
    ) -> dict[str, object]:
        fft_calls.append((fft_block.copy(), bool(kwargs["spike_filter_enabled"])))
        return _empty_fft_result()

    monkeypatch.setattr("vibesensor.infra.processing.compute.medfilt3", _fake_medfilt3)
    monkeypatch.setattr(
        "vibesensor.shared.fft_analysis.compute_fft_spectrum",
        _fake_compute_fft_spectrum,
    )

    result = metrics.compute(snapshot)

    assert result.has_fft_data is True
    assert len(fft_calls) == 1
    np.testing.assert_array_equal(fft_calls[0][0], filtered_time_window[:, -4:])
    assert fft_calls[0][1] is False


def test_compute_filters_short_fft_block_only_once(monkeypatch) -> None:
    metrics = SignalMetricsComputer(_config(fft_n=4))
    time_window = np.arange(6, dtype=np.float32).reshape(3, 2)
    fft_block = np.arange(12, dtype=np.float32).reshape(3, 4)
    snapshot = MetricsSnapshot(
        client_id="client-1",
        sample_rate_hz=800,
        ingest_generation=1,
        time_window=time_window,
        fft_block=fft_block,
    )
    filtered_time_window = np.full((3, 2), 3.0, dtype=np.float32)
    filtered_fft_block = np.full((3, 4), 9.0, dtype=np.float32)
    fft_calls: list[tuple[np.ndarray, bool]] = []
    seen_shapes: list[tuple[int, int]] = []

    def _fake_medfilt3(block: np.ndarray) -> np.ndarray:
        seen_shapes.append(block.shape)
        if block.shape == time_window.shape:
            return filtered_time_window
        np.testing.assert_array_equal(block, fft_block)
        return filtered_fft_block

    def _fake_compute_fft_spectrum(
        fft_input: np.ndarray,
        sample_rate_hz: int,
        **kwargs: object,
    ) -> dict[str, object]:
        fft_calls.append((fft_input.copy(), bool(kwargs["spike_filter_enabled"])))
        return _empty_fft_result()

    monkeypatch.setattr("vibesensor.infra.processing.compute.medfilt3", _fake_medfilt3)
    monkeypatch.setattr(
        "vibesensor.shared.fft_analysis.compute_fft_spectrum",
        _fake_compute_fft_spectrum,
    )

    result = metrics.compute(snapshot)

    assert result.has_fft_data is True
    assert seen_shapes == [fft_block.shape]
    assert len(fft_calls) == 1
    np.testing.assert_array_equal(fft_calls[0][0], filtered_fft_block)
    assert fft_calls[0][1] is False


def test_compute_reuses_single_square_call_for_rms_and_combined_metrics(
    monkeypatch,
) -> None:
    metrics = SignalMetricsComputer(_config(fft_n=4))
    time_window = np.array(
        [
            [1.0, 3.0, 5.0, 7.0],
            [2.0, 4.0, 6.0, 8.0],
            [0.5, 1.5, 2.5, 3.5],
        ],
        dtype=np.float32,
    )
    snapshot = MetricsSnapshot(
        client_id="client-1",
        sample_rate_hz=800,
        ingest_generation=1,
        time_window=time_window,
        fft_block=None,
    )
    square_calls = 0
    original_square = np.square

    def counting_square(*args: object, **kwargs: object) -> np.ndarray:
        nonlocal square_calls
        square_calls += 1
        return original_square(*args, **kwargs)

    monkeypatch.setattr("vibesensor.infra.processing.compute.np.square", counting_square)

    result = metrics.compute(snapshot)

    assert square_calls == 1
    assert result.metrics["x"]["rms"] > 0.0
    assert result.metrics["combined"]["vib_mag_rms"] > 0.0
    assert result.metrics["combined"]["processing_profile"] == "live_display"
    assert result.metrics["combined"]["filter_chain"] == ["median_3_sample_time_domain"]


def test_compute_fft_spectrum_reuses_cached_strength_range_mask(monkeypatch) -> None:
    metrics = SignalMetricsComputer(_config(fft_n=8))
    block = np.zeros((3, 8), dtype=np.float32)
    seen_masks: list[np.ndarray] = []

    def _fake_compute_fft_spectrum(
        fft_block: np.ndarray,
        sample_rate_hz: int,
        **kwargs: object,
    ) -> dict[str, object]:
        del fft_block, sample_rate_hz
        seen_masks.append(kwargs["strength_range_mask"])
        return _empty_fft_result()

    monkeypatch.setattr(
        "vibesensor.shared.fft_analysis.compute_fft_spectrum",
        _fake_compute_fft_spectrum,
    )

    metrics.compute_fft_spectrum(block, 800, spike_filter_enabled=False)
    metrics.compute_fft_spectrum(block, 800, spike_filter_enabled=False)

    assert len(seen_masks) == 2
    assert seen_masks[0] is seen_masks[1]
    assert seen_masks[0].dtype == np.bool_
    assert np.all(seen_masks[0])
