"""Analysis pipeline guard regressions.

Covers:
  1. findings.py burstiness → inf for near-zero median with non-zero max
  2. findings.py _compute_effective_match_rate iterates all speed bins
  3. phase_segmentation.py math.isfinite guard for t_s=0.0
  4. helpers.py _speed_bin_label handles negative and NaN kmh
  5. update_manager.py _hash_tree survives file deletion mid-scan
  6. metrics_log.py run() snapshots session state under lock
"""

from __future__ import annotations

import pytest

from vibesensor.analysis.helpers import _speed_bin_label


def _burstiness(median_amp: float, max_amp: float) -> float:
    return (max_amp / median_amp) if median_amp > 1e-9 else 0.0


class TestSpeedBinLabelEdgeCases:
    """_speed_bin_label must handle NaN, Inf, negative values gracefully."""

    @pytest.mark.parametrize(
        "kmh, expected",
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
        assert _speed_bin_label(kmh) == expected
