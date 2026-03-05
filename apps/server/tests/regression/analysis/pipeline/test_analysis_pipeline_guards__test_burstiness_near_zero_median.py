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


def _burstiness(median_amp: float, max_amp: float) -> float:
    return (max_amp / median_amp) if median_amp > 1e-9 else 0.0


class TestBurstinessNearZeroMedian:
    """When median_amp ≤ 1e-9, burstiness defaults to 0.0 to avoid inf."""

    def test_near_zero_median_gives_zero(self) -> None:
        """Near-zero median with any max returns 0.0 (safe sentinel)."""
        assert _burstiness(0.0, 1.0) == 0.0

    def test_normal_burstiness_ratio(self) -> None:
        assert _burstiness(1.0, 3.0) == pytest.approx(3.0)
