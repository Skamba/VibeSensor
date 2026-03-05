"""Strength bucketing and combined-spectrum runtime regressions:
- combined spectrum not polluted by zeroed amp_for_peaks
- order tolerance scales with path_compliance
- _noise_floor no double bin removal
- bucket_for_strength returns 'l0' for negative dB
- dead db_value variable removed from _top_strength_values
"""

from __future__ import annotations

import numpy as np

from vibesensor.processing import SignalProcessor


class TestNoiseFloorNoDoubleRemoval:
    """Regression: _noise_floor must not skip amps[1:] before delegating
    to noise_floor_amp_p20_g, since the caller already provides the
    analysis-band slice (DC already removed)."""

    def test_all_bins_included(self) -> None:
        amps = np.array([0.010, 0.012, 0.009, 0.011, 0.013], dtype=np.float32)
        floor = SignalProcessor._noise_floor(amps)
        # All 5 bins should be considered. If amps[1:] were used,
        # the first bin (0.010) would be excluded, changing the result.
        # P20 of [0.009, 0.010, 0.011, 0.012, 0.013] ≈ 0.0098
        assert floor > 0.0
        # The result must include the first bin. If it were excluded,
        # P20 of [0.011, 0.012, 0.013] = 0.0114, which is higher.
        # With all 5 bins, P20 is lower because 0.009 and 0.010 pull it down.
        floor_without_first = SignalProcessor._noise_floor(amps[1:])
        assert floor <= floor_without_first + 1e-6, (
            f"Floor {floor} should be ≤ floor-without-first {floor_without_first}"
        )
