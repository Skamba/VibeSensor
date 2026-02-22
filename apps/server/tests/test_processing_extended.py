from __future__ import annotations

import numpy as np
import pytest

from vibesensor.processing import SignalProcessor


def _make_processor(**kwargs) -> SignalProcessor:
    defaults = dict(
        sample_rate_hz=200,
        waveform_seconds=2,
        waveform_display_hz=50,
        fft_n=256,
        spectrum_max_hz=100,
    )
    defaults.update(kwargs)
    return SignalProcessor(**defaults)


# -- ingest: empty samples -----------------------------------------------------


def test_ingest_empty_samples() -> None:
    proc = _make_processor()
    proc.ingest("client1", np.empty((0, 3), dtype=np.float32))
    assert proc.latest_sample_xyz("client1") is None


# -- ingest: malformed shape ---------------------------------------------------


def test_ingest_malformed_shape_dropped() -> None:
    proc = _make_processor()
    # Wrong shape: 1D array
    proc.ingest("client1", np.array([1.0, 2.0, 3.0], dtype=np.float32))
    assert proc.latest_sample_xyz("client1") is None


# -- ingest: accel scaling -----------------------------------------------------


def test_ingest_applies_accel_scale() -> None:
    proc = _make_processor(accel_scale_g_per_lsb=0.5)
    samples = np.array([[2.0, 4.0, 6.0]], dtype=np.float32)
    proc.ingest("client1", samples)
    xyz = proc.latest_sample_xyz("client1")
    assert xyz is not None
    assert abs(xyz[0] - 1.0) < 1e-5  # 2.0 * 0.5
    assert abs(xyz[1] - 2.0) < 1e-5  # 4.0 * 0.5
    assert abs(xyz[2] - 3.0) < 1e-5  # 6.0 * 0.5


# -- ingest: wrap-around -------------------------------------------------------


def test_ingest_wraparound_buffer() -> None:
    proc = _make_processor(sample_rate_hz=10, waveform_seconds=1)
    # Buffer holds 10 samples, push 15
    chunk1 = np.random.randn(15, 3).astype(np.float32)
    proc.ingest("client1", chunk1)
    xyz = proc.latest_sample_xyz("client1")
    assert xyz is not None
    # Latest should be last row of chunk1
    assert abs(xyz[0] - chunk1[-1, 0]) < 1e-5


# -- ingest: sample rate override ----------------------------------------------


def test_ingest_with_sample_rate() -> None:
    proc = _make_processor()
    samples = np.array([[1.0, 2.0, 3.0]], dtype=np.float32)
    proc.ingest("client1", samples, sample_rate_hz=400)
    assert proc.latest_sample_rate_hz("client1") == 400


# -- latest_sample_xyz ---------------------------------------------------------


def test_latest_sample_xyz_missing_client() -> None:
    proc = _make_processor()
    assert proc.latest_sample_xyz("unknown") is None


# -- latest_sample_rate_hz -----------------------------------------------------


def test_latest_sample_rate_hz_missing() -> None:
    proc = _make_processor()
    assert proc.latest_sample_rate_hz("unknown") is None


def test_latest_sample_rate_hz_default_zero() -> None:
    proc = _make_processor()
    samples = np.array([[1.0, 2.0, 3.0]], dtype=np.float32)
    proc.ingest("client1", samples)
    # No explicit sample rate set → returns None (0 is falsy)
    assert proc.latest_sample_rate_hz("client1") is None


# -- spectrum_payload ----------------------------------------------------------


def test_spectrum_payload_missing_client() -> None:
    proc = _make_processor()
    result = proc.spectrum_payload("unknown")
    assert result == {
        "x": [],
        "y": [],
        "z": [],
        "combined_spectrum_amp_g": [],
        "strength_metrics": {},
    }


def test_spectrum_payload_has_vibration_strength_db() -> None:
    proc = _make_processor(sample_rate_hz=800, fft_n=256, spectrum_max_hz=200)
    t = np.arange(400, dtype=np.float32) / np.float32(800.0)
    tone = (0.03 * np.sin(2.0 * np.pi * 32.0 * t)).astype(np.float32)
    samples = np.column_stack((tone, tone * 0.8, tone * 0.6)).astype(np.float32)
    proc.ingest("client1", samples, sample_rate_hz=800)
    proc.compute_metrics("client1")

    result = proc.spectrum_payload("client1")
    assert "combined_spectrum_db_above_floor" not in result
    assert "vibration_strength_db" in result["strength_metrics"]
    db = float(result["strength_metrics"]["vibration_strength_db"])
    assert -200.0 < db < 200.0


# -- multi_spectrum_payload ----------------------------------------------------


def test_multi_spectrum_payload_empty() -> None:
    proc = _make_processor()
    result = proc.multi_spectrum_payload([])
    assert result["freq"] == []
    assert result["clients"] == {}


def test_multi_spectrum_payload_returns_per_client_freq_on_mismatch() -> None:
    proc = _make_processor(sample_rate_hz=200, fft_n=128, spectrum_max_hz=100)
    samples = np.random.randn(300, 3).astype(np.float32) * 0.01

    proc.ingest("c1", samples, sample_rate_hz=200)
    proc.ingest("c2", samples, sample_rate_hz=320)
    proc.compute_metrics("c1", sample_rate_hz=200)
    proc.compute_metrics("c2", sample_rate_hz=320)

    result = proc.multi_spectrum_payload(["c1", "c2"])
    assert result["freq"] == []
    assert sorted(result["clients"]) == ["c1", "c2"]
    assert result["clients"]["c1"]["freq"]
    assert result["clients"]["c2"]["freq"]
    assert result["warning"]["code"] == "frequency_bin_mismatch"
    assert "c2" in result["warning"]["client_ids"]


def test_multi_spectrum_payload_compares_freq_axes_without_np_asarray(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _make_processor(sample_rate_hz=200, fft_n=128, spectrum_max_hz=100)
    samples = np.random.randn(300, 3).astype(np.float32) * 0.01

    proc.ingest("c1", samples, sample_rate_hz=200)
    proc.ingest("c2", samples, sample_rate_hz=200)
    proc.compute_metrics("c1", sample_rate_hz=200)
    proc.compute_metrics("c2", sample_rate_hz=200)

    def _fail_asarray(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("np.asarray should not be used in multi_spectrum_payload")

    monkeypatch.setattr("vibesensor.processing.np.asarray", _fail_asarray)

    result = proc.multi_spectrum_payload(["c1", "c2"])
    assert sorted(result["clients"]) == ["c1", "c2"]
    assert result["freq"]


# -- selected_payload ----------------------------------------------------------


def test_selected_payload_missing_client() -> None:
    proc = _make_processor()
    result = proc.selected_payload("unknown")
    assert result["client_id"] == "unknown"
    assert result["waveform"] == {}
    assert result["spectrum"] == {}
    assert result["metrics"] == {}


def test_selected_payload_waveform_respects_configured_window() -> None:
    """Waveform serialization should be bounded by `waveform_seconds` at client sample rate.

    Returning the full ring buffer leaks stale data when the configured display window is
    shorter than buffered history. The selected payload must slice to the configured window
    before decimation so UI time spans stay consistent.
    """
    proc = _make_processor(sample_rate_hz=100, waveform_seconds=2, waveform_display_hz=25)
    samples = np.random.randn(400, 3).astype(np.float32) * 0.01
    proc.ingest("client1", samples, sample_rate_hz=50)

    result = proc.selected_payload("client1")
    waveform = result["waveform"]
    expected_window_samples = 2 * 50
    expected_step = max(1, 50 // 25)
    expected_points = expected_window_samples // expected_step

    assert len(waveform["t"]) == expected_points
    assert waveform["t"][-1] == pytest.approx(0.0)
    assert waveform["t"][1] - waveform["t"][0] == pytest.approx(expected_step / 50.0)


def test_waveform_window_respects_seconds_for_each_client_sample_rate() -> None:
    proc = _make_processor(sample_rate_hz=100, waveform_seconds=2, waveform_display_hz=25)
    low_sr = np.random.randn(400, 3).astype(np.float32) * 0.01
    high_sr = np.random.randn(1200, 3).astype(np.float32) * 0.01
    proc.ingest("c-low", low_sr, sample_rate_hz=50)
    proc.ingest("c-high", high_sr, sample_rate_hz=300)

    low_payload = proc.selected_payload("c-low")
    high_payload = proc.selected_payload("c-high")

    low_t = low_payload["waveform"]["t"]
    high_t = high_payload["waveform"]["t"]
    assert low_t[-1] == pytest.approx(0.0)
    assert high_t[-1] == pytest.approx(0.0)
    assert low_t[0] == pytest.approx(-1.96, abs=0.05)
    assert high_t[0] == pytest.approx(-2.0, abs=0.05)


# -- compute_metrics -----------------------------------------------------------


def test_compute_metrics_missing_client() -> None:
    proc = _make_processor()
    result = proc.compute_metrics("unknown")
    assert result == {}


def test_compute_metrics_with_data() -> None:
    proc = _make_processor(sample_rate_hz=200, fft_n=64)
    # Push enough samples for FFT
    samples = np.random.randn(100, 3).astype(np.float32) * 0.01
    proc.ingest("client1", samples)
    metrics = proc.compute_metrics("client1")
    assert "x" in metrics
    assert "y" in metrics
    assert "z" in metrics
    assert "combined" in metrics
    assert metrics["x"]["rms"] > 0


# -- _smooth_spectrum edge cases -----------------------------------------------


def test_smooth_spectrum_empty() -> None:
    result = SignalProcessor._smooth_spectrum(np.array([], dtype=np.float32))
    assert result.size == 0


def test_smooth_spectrum_small_array() -> None:
    arr = np.array([1.0, 2.0], dtype=np.float32)
    result = SignalProcessor._smooth_spectrum(arr, bins=5)
    # Array smaller than kernel → returns copy
    assert result.size == 2


def test_smooth_spectrum_single_bin() -> None:
    arr = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    result = SignalProcessor._smooth_spectrum(arr, bins=1)
    np.testing.assert_array_equal(result, arr)


# -- _noise_floor edge cases ---------------------------------------------------


def test_noise_floor_empty() -> None:
    assert SignalProcessor._noise_floor(np.array([], dtype=np.float32)) == 0.0


def test_noise_floor_all_nan() -> None:
    arr = np.array([float("nan"), float("nan"), float("nan")], dtype=np.float32)
    assert SignalProcessor._noise_floor(arr) == 0.0


def test_noise_floor_single_element() -> None:
    result = SignalProcessor._noise_floor(np.array([5.0], dtype=np.float32))
    assert result == 5.0


# -- evict_clients -------------------------------------------------------------


def test_evict_clients() -> None:
    proc = _make_processor()
    samples = np.array([[1.0, 2.0, 3.0]], dtype=np.float32)
    proc.ingest("keep", samples)
    proc.ingest("evict", samples)
    proc.evict_clients({"keep"})
    assert proc.latest_sample_xyz("keep") is not None
    assert proc.latest_sample_xyz("evict") is None


# -- _top_peaks edge cases -----------------------------------------------------


def test_top_peaks_empty() -> None:
    result = SignalProcessor._top_peaks(np.array([]), np.array([]))
    assert result == []


def test_top_peaks_with_data() -> None:
    freqs = np.linspace(0, 100, 64, dtype=np.float32)
    # Create a broad peak (several bins high) so smoothing doesn't flatten it
    amps = np.zeros(64, dtype=np.float32)
    for i in range(8, 13):
        amps[i] = 1.0
    amps[10] = 2.0  # Peak center
    peaks = SignalProcessor._top_peaks(freqs, amps, top_n=3, smoothing_bins=3)
    assert len(peaks) >= 1
    assert peaks[0]["amp"] > 0


# -- compute_all ---------------------------------------------------------------


def test_compute_all() -> None:
    proc = _make_processor(sample_rate_hz=200, fft_n=64)
    samples = np.random.randn(100, 3).astype(np.float32) * 0.01
    proc.ingest("c1", samples)
    proc.ingest("c2", samples)
    result = proc.compute_all(["c1", "c2"])
    assert "c1" in result
    assert "c2" in result
    assert result["c1"]["x"]["rms"] > 0
