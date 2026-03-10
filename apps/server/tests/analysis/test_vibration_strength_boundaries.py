"""Boundary tests for compute_vibration_strength_db.

Covers edge cases: all-zero input, flat spectrum, NaN values, single-bin,
very large spectrum, and no-peak-above-threshold scenarios.
"""

from __future__ import annotations

import math

import pytest

from vibesensor.core.vibration_strength import (
    compute_vibration_strength_db,
    vibration_strength_db_scalar,
)

_NAN = float("nan")


class TestComputeVibrationStrengthBoundaries:
    @pytest.mark.smoke
    def test_empty_input(self) -> None:
        result = compute_vibration_strength_db(
            freq_hz=[],
            combined_spectrum_amp_g_values=[],
        )
        assert result["vibration_strength_db"] == 0.0
        assert result["top_peaks"] == []

    def test_all_zero_amplitude(self) -> None:
        result = compute_vibration_strength_db(
            freq_hz=[1.0, 2.0, 3.0, 4.0, 5.0],
            combined_spectrum_amp_g_values=[0.0, 0.0, 0.0, 0.0, 0.0],
        )
        assert math.isfinite(result["vibration_strength_db"])
        assert result["peak_amp_g"] == 0.0
        assert "strength_bucket" in result

    @pytest.mark.parametrize(
        ("label", "freq_hz", "amp"),
        [
            pytest.param(
                "flat_spectrum",
                [float(i) for i in range(100)],
                [0.01] * 100,
                id="flat_spectrum",
            ),
            pytest.param("single_bin", [10.0], [0.05], id="single_bin"),
            pytest.param("two_bins", [1.0, 2.0], [0.01, 0.05], id="two_bins"),
            pytest.param(
                "mismatched_lengths",
                [1.0, 2.0, 3.0],
                [0.01, 0.05],
                id="mismatched_lengths",
            ),
            pytest.param(
                "negative_amplitudes",
                [1.0, 2.0, 3.0, 4.0, 5.0],
                [-0.01, -0.05, 0.01, -0.02, 0.0],
                id="negative_amplitudes",
            ),
        ],
    )
    def test_degenerate_input_yields_finite_db(
        self,
        label: str,
        freq_hz: list[float],
        amp: list[float],
    ) -> None:
        """Degenerate / edge-case inputs must produce a finite dB value."""
        result = compute_vibration_strength_db(
            freq_hz=freq_hz,
            combined_spectrum_amp_g_values=amp,
        )
        assert math.isfinite(result["vibration_strength_db"]), f"{label}: dB not finite"
        assert "strength_bucket" in result, f"{label}: missing strength_bucket"

    @pytest.mark.smoke
    def test_clear_peak(self) -> None:
        """One clear peak in the middle: should produce positive dB."""
        freq = [float(i) for i in range(20)]
        amp = [0.001] * 20
        amp[10] = 0.10  # strong peak
        result = compute_vibration_strength_db(
            freq_hz=freq,
            combined_spectrum_amp_g_values=amp,
        )
        assert result["vibration_strength_db"] > 0.0
        assert len(result["top_peaks"]) >= 1
        assert result["top_peaks"][0]["hz"] == 10.0
        assert "strength_bucket" in result

    def test_large_spectrum(self) -> None:
        """Large spectrum (1000 bins) should complete without issues."""
        freq = [float(i) for i in range(1000)]
        amp = [0.001] * 1000
        amp[500] = 0.20  # one strong peak
        result = compute_vibration_strength_db(
            freq_hz=freq,
            combined_spectrum_amp_g_values=amp,
        )
        assert result["vibration_strength_db"] > 0.0
        assert len(result["top_peaks"]) >= 1


# -- vibration_strength_db_scalar direct tests --------------------------------


class TestVibrationStrengthDbScalar:
    """Direct unit tests for the dB scalar computation."""

    def test_equal_peak_and_floor_returns_near_zero(self) -> None:
        """When peak == floor, dB should be ~0."""
        db = vibration_strength_db_scalar(peak_band_rms_amp_g=0.01, floor_amp_g=0.01)
        assert abs(db) < 0.5

    def test_large_peak_gives_positive_db(self) -> None:
        db = vibration_strength_db_scalar(peak_band_rms_amp_g=1.0, floor_amp_g=0.001)
        assert db > 30.0

    def test_zero_floor_zero_peak_returns_finite(self) -> None:
        db = vibration_strength_db_scalar(peak_band_rms_amp_g=0.0, floor_amp_g=0.0)
        assert math.isfinite(db)
        assert abs(db) < 0.01

    @pytest.mark.parametrize(
        ("peak", "floor", "kwargs"),
        [
            pytest.param(_NAN, 0.01, {}, id="nan_peak"),
            pytest.param(0.01, _NAN, {}, id="nan_floor"),
            pytest.param(-0.5, -0.3, {}, id="negative_inputs"),
        ],
    )
    def test_invalid_inputs_return_finite(self, peak: float, floor: float, kwargs: dict) -> None:
        """NaN or negative inputs must still yield a finite dB value."""
        db = vibration_strength_db_scalar(peak_band_rms_amp_g=peak, floor_amp_g=floor, **kwargs)
        assert math.isfinite(db)

    def test_custom_epsilon(self) -> None:
        db = vibration_strength_db_scalar(peak_band_rms_amp_g=0.0, floor_amp_g=0.0, epsilon_g=1e-6)
        assert math.isfinite(db)
        assert abs(db) < 0.01
