from __future__ import annotations

from math import pi

import numpy as np
import pytest

from vibesensor.shared.window_quality import score_window_quality, window_quality_with_context


def _sine_samples(*, sample_count: int = 256, amplitude: float = 0.05) -> np.ndarray:
    sample_rate_hz = 256
    t = np.arange(sample_count, dtype=np.float32) / float(sample_rate_hz)
    return np.column_stack(
        [
            amplitude * np.sin(2.0 * pi * 20.0 * t),
            np.zeros(sample_count, dtype=np.float32),
            np.zeros(sample_count, dtype=np.float32),
        ]
    )


def test_window_quality_scores_clean_window_as_usable() -> None:
    sample_count = 256
    samples_g = _sine_samples(sample_count=sample_count)

    quality = score_window_quality(
        expected_sample_count=sample_count,
        returned_sample_count=sample_count,
        coverage_state="full",
        samples_g=samples_g,
        peak_amp_g=0.05,
        noise_floor_amp_g=0.005,
    )

    assert quality.state == "usable"
    assert quality.score > 0.95
    assert quality.shock_broadband_ratio is not None
    assert quality.shock_broadband_ratio < 0.15
    assert quality.reasons == ()


def test_window_quality_marks_dropped_clipped_and_shock_windows_low_quality() -> None:
    sample_count = 256
    clipped = np.zeros((sample_count, 3), dtype=np.int16)
    clipped[:8, 0] = 32767
    impulse = np.zeros((sample_count, 3), dtype=np.float32)
    impulse[128, 0] = 20.0

    dropped = score_window_quality(
        expected_sample_count=sample_count,
        returned_sample_count=96,
        coverage_state="partial",
        coverage_reason="window_crosses_gap",
    )
    clipped_quality = score_window_quality(
        expected_sample_count=sample_count,
        returned_sample_count=sample_count,
        coverage_state="full",
        samples_i16=clipped,
        samples_g=clipped.astype(np.float32) * 0.001,
        peak_amp_g=0.1,
        noise_floor_amp_g=0.01,
    )
    shock = score_window_quality(
        expected_sample_count=sample_count,
        returned_sample_count=sample_count,
        coverage_state="full",
        samples_g=impulse,
        peak_amp_g=0.1,
        noise_floor_amp_g=0.01,
    )

    assert dropped.state == "excluded"
    assert "sample_incomplete" in dropped.reasons
    assert "packet_integrity_gap" in dropped.reasons
    assert clipped_quality.state == "excluded"
    assert "sensor_clipping" in clipped_quality.reasons
    assert shock.state == "excluded"
    assert "shock_transient" in shock.reasons


def test_window_quality_context_downgrades_missing_speed_and_rpm() -> None:
    clean = score_window_quality(
        expected_sample_count=128,
        returned_sample_count=128,
        coverage_state="full",
        peak_amp_g=0.05,
        noise_floor_amp_g=0.005,
    )

    quality = window_quality_with_context(
        clean,
        context_coverage="missing",
        speed_validity="missing",
        rpm_validity="missing",
    )

    assert quality.state == "limited"
    assert quality.context_score < 0.5
    assert "context_unavailable" in quality.reasons


@pytest.mark.parametrize(
    ("samples_g", "expected_state"),
    [
        pytest.param(_sine_samples(), "usable", id="sustained-sine"),
        pytest.param(
            np.pad(
                np.array([[18.0, 0.0, 0.0]], dtype=np.float32),
                ((127, 128), (0, 0)),
            ),
            "excluded",
            id="impulse-only",
        ),
        pytest.param(
            _sine_samples(amplitude=0.04)
            + np.pad(
                np.array([[8.0, 0.0, 0.0]], dtype=np.float32),
                ((127, 128), (0, 0)),
            ),
            "excluded",
            id="sine-plus-impulse",
        ),
        pytest.param(
            np.pad(
                np.array(
                    [
                        [5.0, 0.0, 0.0],
                        [-4.0, 2.0, 0.0],
                        [3.5, -3.0, 1.0],
                        [-5.5, 0.0, 2.0],
                    ],
                    dtype=np.float32,
                ),
                ((40, 212), (0, 0)),
            ),
            "excluded",
            id="repeated-rough-road-bursts",
        ),
    ],
)
def test_window_quality_distinguishes_shock_transients_from_sustained_vibration(
    samples_g: np.ndarray,
    expected_state: str,
) -> None:
    quality = score_window_quality(
        expected_sample_count=samples_g.shape[0],
        returned_sample_count=samples_g.shape[0],
        coverage_state="full",
        samples_g=samples_g,
        peak_amp_g=0.1,
        noise_floor_amp_g=0.01,
    )

    assert quality.state == expected_state
    assert quality.shock_crest_factor is not None
    assert quality.shock_broadband_ratio is not None
    if expected_state == "excluded":
        assert "shock_transient" in quality.reasons
        assert quality.transient_score < 0.25
    else:
        assert "shock_transient" not in quality.reasons
        assert quality.transient_score > 0.90
