from __future__ import annotations

import numpy as np
import pytest

from vibesensor.processing import MAX_CLIENT_SAMPLE_RATE_HZ, SignalProcessor
from vibesensor.processing.fft import noise_floor, smooth_spectrum, top_peaks
from vibesensor.vibration_strength import compute_vibration_strength_db


def _make_processor(**kwargs) -> SignalProcessor:
    defaults = {
        "sample_rate_hz": 200,
        "waveform_seconds": 2,
        "waveform_display_hz": 50,
        "fft_n": 256,
        "spectrum_max_hz": 100,
    }
    defaults.update(kwargs)
    return SignalProcessor(**defaults)


def _random_samples(n: int, *, seed: int = 42, scale: float = 0.01) -> np.ndarray:
    return (np.random.default_rng(seed).standard_normal((n, 3)) * scale).astype(np.float32)


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
    _rng = np.random.default_rng(42)
    chunk1 = _rng.standard_normal((15, 3)).astype(np.float32)
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


def test_ingest_clamps_excessive_sample_rate() -> None:
    proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
    samples = _random_samples(10)
    proc.ingest("client1", samples, sample_rate_hz=250_000)
    assert proc.latest_sample_rate_hz("client1") == MAX_CLIENT_SAMPLE_RATE_HZ
    assert proc._store.buffers["client1"].capacity == MAX_CLIENT_SAMPLE_RATE_HZ * 2


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
    assert result["combined_spectrum_amp_g"] == []
    assert result["strength_metrics"]["vibration_strength_db"] == 0.0


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


@pytest.mark.parametrize(
    ("proc_kw", "method_name", "n_samples", "sr"),
    [
        pytest.param(
            {"sample_rate_hz": 400, "fft_n": 128, "spectrum_max_hz": 150},
            "spectrum_payload",
            300,
            400,
            id="spectrum",
        ),
    ],
)
def test_payload_reuses_cached_conversion(
    monkeypatch: pytest.MonkeyPatch,
    proc_kw: dict,
    method_name: str,
    n_samples: int,
    sr: int,
) -> None:
    proc = _make_processor(**proc_kw)
    samples = _random_samples(n_samples)
    proc.ingest("client1", samples, sample_rate_hz=sr)
    proc.compute_metrics("client1")
    payload_fn = getattr(proc, method_name)
    first = payload_fn("client1")

    def _fail_float_list(*_a, **_kw):  # type: ignore[no-untyped-def]
        raise AssertionError(f"float_list should not be called for cached {method_name}")

    monkeypatch.setattr(
        "vibesensor.processing.payload.float_list",
        _fail_float_list,
    )
    second = payload_fn("client1")
    assert second is first


# -- multi_spectrum_payload ----------------------------------------------------


def test_multi_spectrum_payload_empty() -> None:
    proc = _make_processor()
    result = proc.multi_spectrum_payload([])
    assert result["freq"] == []
    assert result["clients"] == {}


def test_multi_spectrum_payload_returns_per_client_freq_on_mismatch() -> None:
    proc = _make_processor(sample_rate_hz=200, fft_n=128, spectrum_max_hz=100)
    samples = _random_samples(300)

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
    samples = _random_samples(300)

    proc.ingest("c1", samples, sample_rate_hz=200)
    proc.ingest("c2", samples, sample_rate_hz=200)
    proc.compute_metrics("c1", sample_rate_hz=200)
    proc.compute_metrics("c2", sample_rate_hz=200)

    def _fail_asarray(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("np.asarray should not be used in multi_spectrum_payload")

    monkeypatch.setattr("vibesensor.processing.payload.np.asarray", _fail_asarray)

    result = proc.multi_spectrum_payload(["c1", "c2"])
    assert sorted(result["clients"]) == ["c1", "c2"]
    assert result["freq"]


# -- compute_metrics -----------------------------------------------------------


def test_compute_metrics_missing_client() -> None:
    proc = _make_processor()
    result = proc.compute_metrics("unknown")
    assert result == {}


def test_compute_metrics_with_data() -> None:
    proc = _make_processor(sample_rate_hz=200, fft_n=64)
    # Push enough samples for FFT
    samples = _random_samples(100)
    proc.ingest("client1", samples)
    metrics = proc.compute_metrics("client1")
    assert "x" in metrics
    assert "y" in metrics
    assert "z" in metrics
    assert "combined" in metrics
    assert metrics["x"]["rms"] > 0


# -- _smooth_spectrum edge cases -----------------------------------------------


def test_smooth_spectrum_empty() -> None:
    result = smooth_spectrum(np.array([], dtype=np.float32))
    assert result.size == 0


def test_smooth_spectrum_small_array() -> None:
    arr = np.array([1.0, 2.0], dtype=np.float32)
    result = smooth_spectrum(arr, bins=5)
    # Array smaller than kernel → returns copy
    assert result.size == 2


def test_smooth_spectrum_single_bin() -> None:
    arr = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    result = smooth_spectrum(arr, bins=1)
    np.testing.assert_array_equal(result, arr)


# -- _noise_floor edge cases ---------------------------------------------------


@pytest.mark.parametrize(
    ("arr", "expected"),
    [
        pytest.param(np.array([], dtype=np.float32), 0.0, id="empty"),
        pytest.param(np.array([float("nan")] * 3, dtype=np.float32), 0.0, id="all_nan"),
        pytest.param(np.array([5.0], dtype=np.float32), 5.0, id="single_element"),
    ],
)
def test_noise_floor_edge_cases(arr: np.ndarray, expected: float) -> None:
    assert noise_floor(arr) == expected


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
    result = top_peaks(np.array([]), np.array([]))
    assert result == []


def test_top_peaks_with_data() -> None:
    freqs = np.linspace(0, 100, 64, dtype=np.float32)
    # Create a broad peak (several bins high) so smoothing doesn't flatten it
    amps = np.zeros(64, dtype=np.float32)
    for i in range(8, 13):
        amps[i] = 1.0
    amps[10] = 2.0  # Peak center
    peaks = top_peaks(freqs, amps, top_n=3, smoothing_bins=3)
    assert len(peaks) >= 1
    assert peaks[0]["amp"] > 0


def test_top_peaks_dominant_frequency_aligns_with_strength_metrics() -> None:
    freqs = np.linspace(0, 100, 128, dtype=np.float32)
    amps = np.zeros(128, dtype=np.float32)
    amps[35] = 2.0
    amps[74] = 1.6
    peaks = top_peaks(freqs, amps, top_n=1, smoothing_bins=1)
    strength = compute_vibration_strength_db(
        freq_hz=freqs.tolist(),
        combined_spectrum_amp_g_values=amps.tolist(),
        top_n=1,
    )
    assert peaks
    assert strength["top_peaks"]
    assert peaks[0]["hz"] == pytest.approx(float(strength["top_peaks"][0]["hz"]))


# -- compute_all ---------------------------------------------------------------


def test_compute_all() -> None:
    proc = _make_processor(sample_rate_hz=200, fft_n=64)
    samples = _random_samples(100)
    proc.ingest("c1", samples)
    proc.ingest("c2", samples)
    result = proc.compute_all(["c1", "c2"])
    assert "c1" in result
    assert "c2" in result
    assert result["c1"]["x"]["rms"] > 0
