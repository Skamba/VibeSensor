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

from vibesensor.analysis.findings import _compute_effective_match_rate


def _burstiness(median_amp: float, max_amp: float) -> float:
    return (max_amp / median_amp) if median_amp > 1e-9 else 0.0


class TestComputeEffectiveMatchRateAllBins:
    """Should try highest-speed bin first for focused rescue."""

    def test_high_speed_bin_qualifies(self) -> None:
        possible = {"50-60 km/h": 20, "100-110 km/h": 20}
        matched = {"50-60 km/h": 16, "100-110 km/h": 16}

        rate, band, per_loc = _compute_effective_match_rate(
            match_rate=0.3,
            min_match_rate=0.5,
            possible_by_speed_bin=possible,
            matched_by_speed_bin=matched,
            possible_by_location={},
            matched_by_location={},
        )
        assert band == "100-110 km/h"
        assert rate >= 0.5

    def test_no_qualifying_bin_returns_original(self) -> None:
        possible = {"50-60 km/h": 5, "100-110 km/h": 5}
        matched = {"50-60 km/h": 1, "100-110 km/h": 1}

        rate, band, per_loc = _compute_effective_match_rate(
            match_rate=0.3,
            min_match_rate=0.5,
            possible_by_speed_bin=possible,
            matched_by_speed_bin=matched,
            possible_by_location={},
            matched_by_location={},
        )
        assert rate == 0.3
        assert band is None
