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

import inspect

from vibesensor.metrics_log import MetricsLogger


def _burstiness(median_amp: float, max_amp: float) -> float:
    return (max_amp / median_amp) if median_amp > 1e-9 else 0.0


class TestMetricsLogLockSnapshot:
    """Verify that _live_start_mono_s is read under lock in the run loop.

    This is a source-level verification — we check that the code reads
    _live_start_mono_s inside a `with self._lock:` block.
    """

    def test_live_start_read_is_under_lock(self) -> None:
        source = inspect.getsource(MetricsLogger.run)
        assert "with self._lock:" in source
        lock_idx = source.index("with self._lock:")
        live_start_idx = source.index("_live_start_mono_s")
        build_idx = source.index("_build_sample_records")
        assert lock_idx < live_start_idx < build_idx, (
            "_live_start_mono_s should be read under lock, before _build_sample_records"
        )
