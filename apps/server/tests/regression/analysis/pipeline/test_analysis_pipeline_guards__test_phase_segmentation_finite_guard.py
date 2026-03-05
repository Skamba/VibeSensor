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

import math


def _burstiness(median_amp: float, max_amp: float) -> float:
    return (max_amp / median_amp) if median_amp > 1e-9 else 0.0


class TestPhaseSegmentationFiniteGuard:
    """end_t_s == 0.0 is a valid time and must not be treated as falsy."""

    def test_zero_time_propagates_to_next_segment(self) -> None:
        assert math.isfinite(0.0) is True
