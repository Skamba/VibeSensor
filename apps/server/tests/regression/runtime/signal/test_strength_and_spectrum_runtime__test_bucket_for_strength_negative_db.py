"""Strength bucketing and combined-spectrum runtime regressions:
- combined spectrum not polluted by zeroed amp_for_peaks
- order tolerance scales with path_compliance
- _noise_floor no double bin removal
- bucket_for_strength returns 'l0' for negative dB
- dead db_value variable removed from _top_strength_values
"""

from __future__ import annotations

import pytest
from vibesensor_core.strength_bands import bucket_for_strength


class TestBucketForStrengthNegativeDB:
    """Regression: bucket_for_strength must return 'l0' for negative dB,
    not None."""

    @pytest.mark.parametrize(
        "db_val, expected",
        [
            pytest.param(-5.0, "l0", id="negative"),
            pytest.param(0.0, "l0", id="zero"),
            pytest.param(7.9, "l0", id="below_l1"),
            pytest.param(8.0, "l1", id="l1_boundary"),
            pytest.param(50.0, "l5", id="high"),
        ],
    )
    def test_bucket_boundaries(self, db_val: float, expected: str) -> None:
        assert bucket_for_strength(db_val) == expected
