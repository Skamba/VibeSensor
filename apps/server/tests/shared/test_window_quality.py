from __future__ import annotations

from math import pi

import numpy as np

from vibesensor.shared.window_quality import score_window_quality, window_quality_with_context


def test_window_quality_scores_clean_window_as_usable() -> None:
    sample_rate_hz = 256
    sample_count = 256
    t = np.arange(sample_count, dtype=np.float32) / float(sample_rate_hz)
    samples_g = np.column_stack(
        [
            0.05 * np.sin(2.0 * pi * 20.0 * t),
            np.zeros(sample_count, dtype=np.float32),
            np.zeros(sample_count, dtype=np.float32),
        ]
    )

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
