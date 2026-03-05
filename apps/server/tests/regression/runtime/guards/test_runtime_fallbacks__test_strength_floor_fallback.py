"""Runtime fallback and error-guard regressions.

Covers strength_floor_amp_g fallback, wheel_focus_from_location,
store_analysis_error guard, and i18n formatting.
"""

from __future__ import annotations

import math

from vibesensor_core.vibration_strength import (
    strength_floor_amp_g,
    vibration_strength_db_scalar,
)


class TestStrengthFloorFallback:
    """Regression: strength_floor_amp_g must not return 0.0 when all bins
    are within peak exclusion zones, since 0.0 floor produces ~140 dB."""

    def test_all_bins_excluded_falls_back_to_p20(self) -> None:
        """When every bin is excluded by peaks, fall back to P20 noise floor."""
        # 5 bins, one dominant peak in the center.  With exclusion_hz=10.0
        # every bin falls within the exclusion zone around the peak.
        freq = [5.0, 6.0, 7.0, 8.0, 9.0]
        amps = [0.001, 0.002, 0.1, 0.002, 0.001]
        peak_indexes = [2]  # peak at 7 Hz

        floor = strength_floor_amp_g(
            freq_hz=freq,
            combined_spectrum_amp_g=amps,
            peak_indexes=peak_indexes,
            exclusion_hz=10.0,  # excludes everything
            min_hz=5.0,
            max_hz=9.0,
        )
        # Should NOT be 0.0 — must fall back to P20
        assert floor > 0.0, "Floor must not be 0.0 when all bins are excluded"

        # Verify the dB value is sane (not 140+)
        db = vibration_strength_db_scalar(
            peak_band_rms_amp_g=0.1,
            floor_amp_g=floor,
        )
        assert db < 80, f"Expected sane dB (<80), got {db}"
        assert math.isfinite(db)

    def test_normal_case_unchanged(self) -> None:
        """When bins survive exclusion, the original median behavior is used."""
        freq = [5.0, 6.0, 7.0, 8.0, 9.0]
        amps = [0.001, 0.002, 0.1, 0.002, 0.001]
        peak_indexes = [2]  # peak at 7 Hz

        floor = strength_floor_amp_g(
            freq_hz=freq,
            combined_spectrum_amp_g=amps,
            peak_indexes=peak_indexes,
            exclusion_hz=0.5,  # only excludes 7 Hz ± 0.5
            min_hz=5.0,
            max_hz=9.0,
        )
        assert floor > 0.0
        # Should be the median of [0.001, 0.002, 0.002, 0.001]
        expected_median = (0.001 + 0.002) / 2  # sorted: [0.001, 0.001, 0.002, 0.002]
        assert abs(floor - expected_median) < 1e-6
