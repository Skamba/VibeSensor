from __future__ import annotations

from dataclasses import replace
from math import pi

import numpy as np
import pytest

from vibesensor.shared.types.whole_run_analysis import (
    WholeRunWindowDescriptor,
    WholeRunWindowPolicy,
)
from vibesensor.use_cases.diagnostics import post_run_window_features as feature_module
from vibesensor.use_cases.diagnostics.post_run_raw_windows import (
    PostRunRawSensorWindow,
    PostRunRawWindow,
    PostRunRawWindowDataQualityFlag,
)
from vibesensor.use_cases.diagnostics.post_run_stft import (
    PostRunDenseStftResult,
    PostRunStftConfig,
    compute_post_run_dense_stft,
)
from vibesensor.use_cases.diagnostics.post_run_window_features import (
    PostRunWindowFeatureConfig,
    extract_post_run_window_features,
    post_run_window_feature_debug_rows,
)
from vibesensor.vibration_strength import VibrationStrengthMetrics

_RUN_ID = "run-features"
_SAMPLE_RATE_HZ = 64
_FFT_N = 64


def _policy() -> WholeRunWindowPolicy:
    return WholeRunWindowPolicy(
        sample_rate_hz=_SAMPLE_RATE_HZ,
        window_size_samples=_FFT_N,
        stride_samples=32,
        overlap_samples=32,
        feature_interval_s=0.5,
    )


def _window_descriptor(index: int = 0) -> WholeRunWindowDescriptor:
    return WholeRunWindowDescriptor.from_policy(
        window_index=index,
        sample_start=index * 32,
        policy=_policy(),
    )


def _tone(
    freq_hz: float,
    *,
    amplitude: float = 1000.0,
    axis: int = 0,
) -> np.ndarray:
    t = np.arange(_FFT_N, dtype=np.float64) / float(_SAMPLE_RATE_HZ)
    samples = np.zeros((_FFT_N, 3), dtype=np.int16)
    samples[:, axis] = np.round(amplitude * np.sin(2.0 * pi * freq_hz * t)).astype(np.int16)
    return samples


def _raw_window(
    samples: np.ndarray,
    *,
    window_index: int = 0,
    flags: tuple[PostRunRawWindowDataQualityFlag, ...] = (),
    mount_orientation: str | None = "+x,+y,+z",
) -> PostRunRawWindow:
    descriptor = _window_descriptor(window_index)
    sensor = PostRunRawSensorWindow(
        run_id=_RUN_ID,
        client_id="sensor-a",
        location="front_left",
        window=descriptor,
        sample_rate_hz=_SAMPLE_RATE_HZ,
        axis_x_i16=samples[:, 0],
        axis_y_i16=samples[:, 1],
        axis_z_i16=samples[:, 2],
        requested_sample_start=descriptor.sample_start,
        requested_sample_count=descriptor.sample_count,
        returned_sample_start=descriptor.sample_start if samples.size else None,
        returned_sample_count=int(samples.shape[0]),
        data_quality_flags=flags,
        mount_orientation=mount_orientation,
    )
    return PostRunRawWindow(run_id=_RUN_ID, window=descriptor, sensors=(sensor,))


def _stft_result(*windows: PostRunRawWindow) -> PostRunDenseStftResult:
    return compute_post_run_dense_stft(
        windows,
        config=PostRunStftConfig(
            fft_size_samples=_FFT_N,
            spectrum_min_hz=1.0,
            spectrum_max_hz=30.0,
            accel_scale_g_per_lsb=0.001,
        ),
    )


def _feature_for(samples: np.ndarray) -> feature_module.PostRunWindowFeature:
    result = extract_post_run_window_features(_stft_result(_raw_window(samples)))
    assert len(result.features) == 1
    return result.features[0]


def test_window_features_detect_single_tone_axis_and_time_metrics() -> None:
    feature = _feature_for(_tone(8.0, amplitude=1000.0, axis=0))

    assert feature.dominant_freq_hz == pytest.approx(8.0, abs=0.25)
    assert feature.axis_dominance.axis == "x"
    assert feature.axis_dominance.axis_frame == "vehicle"
    assert feature.axis_dominance.ratio is not None
    assert feature.axis_dominance.ratio > 1.6
    assert feature.rms_by_axis_g["x"] == pytest.approx(0.707, abs=0.04)
    assert feature.max_axis_p2p_g == pytest.approx(2.0, abs=0.05)
    assert feature.vibration_strength_db is not None
    assert feature.strength_bucket is not None


def test_window_features_preserve_multi_tone_peak_order() -> None:
    samples = _tone(7.0, amplitude=1200.0)
    samples[:, 0] += _tone(15.0, amplitude=400.0)[:, 0]

    feature = _feature_for(samples)

    assert feature.top_peaks[0]["hz"] == pytest.approx(7.0, abs=0.25)
    assert any(peak["hz"] == pytest.approx(15.0, abs=0.25) for peak in feature.top_peaks[:4])


def test_window_features_mark_silence_without_dominant_peak() -> None:
    feature = _feature_for(np.zeros((_FFT_N, 3), dtype=np.int16))

    assert feature.dominant_freq_hz is None
    assert feature.vibration_strength_db is None
    assert feature.peak_amp_g is None
    assert feature.top_peaks == ()
    assert "no_dominant_peak" in feature.feature_quality_flags
    assert feature.strength_bucket == "l0"


def test_window_features_keep_noisy_tone_dominant_and_lower_snr() -> None:
    rng = np.random.default_rng(42)
    clean_feature = _feature_for(_tone(11.0, amplitude=1000.0))
    noisy_samples = _tone(11.0, amplitude=250.0)
    noisy_samples = (noisy_samples + rng.normal(0.0, 120.0, size=noisy_samples.shape)).astype(
        np.int16
    )

    noisy_feature = _feature_for(noisy_samples)

    assert noisy_feature.dominant_freq_hz == pytest.approx(11.0, abs=0.75)
    assert noisy_feature.vibration_strength_db is not None
    assert clean_feature.vibration_strength_db is not None
    assert noisy_feature.vibration_strength_db < clean_feature.vibration_strength_db


def test_window_features_frequency_mask_excludes_unusable_ranges() -> None:
    samples = _tone(8.0, amplitude=1200.0)
    samples[:, 0] += _tone(15.0, amplitude=600.0)[:, 0]
    stft = _stft_result(_raw_window(samples))

    result = extract_post_run_window_features(
        stft,
        config=PostRunWindowFeatureConfig(excluded_frequency_ranges_hz=((7.0, 9.0),)),
    )

    assert result.features[0].dominant_freq_hz == pytest.approx(15.0, abs=0.5)


def test_window_features_propagate_quality_flags_from_raw_windows() -> None:
    stft = _stft_result(
        _raw_window(
            _tone(10.0),
            flags=("partial_window", "timestamp_gap", "missing_samples"),
        )
    )

    feature = extract_post_run_window_features(stft).features[0]

    assert feature.coverage_state == "partial"
    assert "partial_window" in feature.feature_quality_flags
    assert "timestamp_gap" in feature.feature_quality_flags
    assert "missing_samples" in feature.feature_quality_flags


def test_window_features_sanitize_invalid_spectrum_values() -> None:
    frame = _stft_result(_raw_window(_tone(9.0))).frames[0]
    invalid_frame = replace(
        frame,
        freq_hz=np.array([1.0, 9.0, np.inf], dtype=np.float32),
        combined_amp_g=np.array([0.0, np.nan, np.inf], dtype=np.float32),
        spectrum_by_axis_amp_g={
            "x": np.array([0.0, np.nan, np.inf], dtype=np.float32),
            "y": np.zeros(3, dtype=np.float32),
            "z": np.zeros(3, dtype=np.float32),
        },
    )

    feature = extract_post_run_window_features((invalid_frame,)).features[0]

    assert "invalid_spectrum_values" in feature.feature_quality_flags
    assert feature.noise_floor_amp_g is not None
    assert np.isfinite(feature.noise_floor_amp_g)
    assert feature.max_axis_rms_g >= 0.0


def test_window_features_use_canonical_strength_function(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[np.ndarray, np.ndarray]] = []

    def fake_strength(**kwargs: object) -> VibrationStrengthMetrics:
        calls.append(
            (
                np.asarray(kwargs["freq_hz"], dtype=np.float32),
                np.asarray(kwargs["combined_spectrum_amp_g_values"], dtype=np.float32),
            )
        )
        return {
            "vibration_strength_db": 12.0,
            "peak_amp_g": 0.25,
            "noise_floor_amp_g": 0.05,
            "strength_bucket": "l1",
            "top_peaks": [
                {
                    "hz": 8.0,
                    "amp": 0.25,
                    "vibration_strength_db": 12.0,
                    "strength_bucket": "l1",
                }
            ],
        }

    monkeypatch.setattr(feature_module, "compute_vibration_strength_db", fake_strength)

    feature = _feature_for(_tone(8.0))

    assert calls
    assert feature.vibration_strength_db == 12.0
    assert feature.peak_amp_g == 0.25
    assert feature.strength_bucket == "l1"


def test_window_features_debug_rows_for_synthetic_run() -> None:
    stft = _stft_result(
        _raw_window(_tone(6.0), window_index=0),
        _raw_window(_tone(12.0, axis=1), window_index=1),
    )
    features = extract_post_run_window_features(stft).features

    rows = post_run_window_feature_debug_rows(features)

    assert [row["window_index"] for row in rows] == [0, 1]
    assert rows[0]["dominant_freq_hz"] == pytest.approx(6.0, abs=0.25)
    assert rows[1]["axis"] == "y"
    assert rows[1]["axis_frame"] == "vehicle"


def test_window_features_suppress_axis_dominance_when_orientation_unknown() -> None:
    stft = _stft_result(_raw_window(_tone(8.0, axis=0), mount_orientation=None))

    feature = extract_post_run_window_features(stft).features[0]

    assert feature.axis_frame == "sensor_local"
    assert feature.axis_dominance.axis is None
    assert "sensor_orientation_unknown" in feature.feature_quality_flags
    assert feature.dominant_freq_hz == pytest.approx(8.0, abs=0.25)
