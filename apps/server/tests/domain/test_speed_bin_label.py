"""Speed-bin labels stay well formed for invalid speeds."""

from __future__ import annotations

import pytest

from vibesensor.domain.finding import speed_bin_label


class TestSpeedBinLabelEdgeCases:
    """speed_bin_label must handle NaN, Inf, negative values gracefully."""

    @pytest.mark.parametrize(
        ("kmh", "expected"),
        [
            (float("nan"), "0-10 km/h"),
            (float("inf"), "0-10 km/h"),
            (-5.0, "0-10 km/h"),
            (0.0, "0-10 km/h"),
            (55.0, "50-60 km/h"),
        ],
        ids=["nan", "inf", "negative", "zero", "normal"],
    )
    def test_edge_cases(self, kmh: float, expected: str) -> None:
        assert speed_bin_label(kmh) == expected
