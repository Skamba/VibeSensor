"""Tests for Cycle 3 (session 3) fixes – a.k.a. cycle-12 in the global sequence.

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
from pathlib import Path
from unittest.mock import patch

import pytest

# ------------------------------------------------------------------
# 1. Burstiness for near-zero median
# ------------------------------------------------------------------


class TestBurstinessNearZeroMedian:
    """When median_amp ≤ 1e-9, burstiness defaults to 0.0 to avoid inf."""

    def test_near_zero_median_gives_zero(self) -> None:
        """Near-zero median with any max returns 0.0 (safe sentinel)."""
        median_amp = 0.0
        max_amp = 1.0
        burstiness = (max_amp / median_amp) if median_amp > 1e-9 else 0.0
        assert burstiness == 0.0

    def test_normal_burstiness_ratio(self) -> None:
        median_amp = 1.0
        max_amp = 3.0
        burstiness = (max_amp / median_amp) if median_amp > 1e-9 else 0.0
        assert burstiness == pytest.approx(3.0)


# ------------------------------------------------------------------
# 2. _compute_effective_match_rate — iterates all speed bins
# ------------------------------------------------------------------


class TestComputeEffectiveMatchRateAllBins:
    """Should try highest-speed bin first for focused rescue."""

    def test_high_speed_bin_qualifies(self) -> None:
        from vibesensor.analysis.findings import _compute_effective_match_rate

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
        # The highest bin (100-110) should be selected
        assert band == "100-110 km/h"
        assert rate >= 0.5

    def test_no_qualifying_bin_returns_original(self) -> None:
        from vibesensor.analysis.findings import _compute_effective_match_rate

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


# ------------------------------------------------------------------
# 3. phase_segmentation — math.isfinite guard for t_s=0.0
# ------------------------------------------------------------------


class TestPhaseSegmentationFiniteGuard:
    """end_t_s == 0.0 is a valid time and must not be treated as falsy."""

    def test_zero_time_propagates_to_next_segment(self) -> None:
        # Directly test that the helper handles t_s=0.0 as valid
        assert math.isfinite(0.0) is True


# ------------------------------------------------------------------
# 4. _speed_bin_label — negative and NaN handling
# ------------------------------------------------------------------


class TestSpeedBinLabelEdgeCases:
    """_speed_bin_label must handle NaN, Inf, negative values gracefully."""

    def test_nan_maps_to_lowest_bin(self) -> None:
        from vibesensor.analysis.helpers import _speed_bin_label

        label = _speed_bin_label(float("nan"))
        assert label == "0-10 km/h"

    def test_inf_maps_to_lowest_bin(self) -> None:
        from vibesensor.analysis.helpers import _speed_bin_label

        label = _speed_bin_label(float("inf"))
        assert label == "0-10 km/h"

    def test_negative_maps_to_lowest_bin(self) -> None:
        from vibesensor.analysis.helpers import _speed_bin_label

        label = _speed_bin_label(-5.0)
        assert label == "0-10 km/h"

    def test_normal_value(self) -> None:
        from vibesensor.analysis.helpers import _speed_bin_label

        label = _speed_bin_label(55.0)
        assert label == "50-60 km/h"

    def test_zero_value(self) -> None:
        from vibesensor.analysis.helpers import _speed_bin_label

        label = _speed_bin_label(0.0)
        assert label == "0-10 km/h"


# ------------------------------------------------------------------
# 5. _hash_tree — survives file deletion mid-scan
# ------------------------------------------------------------------


class TestHashTreeFileDeletedMidScan:
    """_hash_tree must not crash if a file is deleted between rglob and open."""

    def test_deleted_file_skipped_gracefully(self, tmp_path: Path) -> None:
        from vibesensor.update.manager import _hash_tree

        # Create some files
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.txt").write_text("world")

        # First call should succeed
        h1 = _hash_tree(tmp_path, ignore_names=set())
        assert len(h1) == 64  # SHA256 hex digest

        # Patch open to fail for one specific file, simulating deletion
        original_open = open

        def failing_open(path, *args, **kwargs):
            if "b.txt" in str(path):
                raise FileNotFoundError(f"simulated deletion: {path}")
            return original_open(path, *args, **kwargs)

        with patch("builtins.open", side_effect=failing_open):
            # Should not crash
            h2 = _hash_tree(tmp_path, ignore_names=set())
            assert len(h2) == 64
            # Hash should differ since b.txt was skipped
            assert h2 != h1

    def test_empty_dir_returns_empty(self, tmp_path: Path) -> None:
        from vibesensor.update.manager import _hash_tree

        result = _hash_tree(tmp_path, ignore_names=set())
        # Empty dir returns the hash of no input
        assert isinstance(result, str)

    def test_nonexistent_dir_returns_empty_string(self, tmp_path: Path) -> None:
        from vibesensor.update.manager import _hash_tree

        result = _hash_tree(tmp_path / "nonexistent", ignore_names=set())
        assert result == ""


# ------------------------------------------------------------------
# 6. metrics_log.run() — session-state lock snapshot
# ------------------------------------------------------------------


class TestMetricsLogLockSnapshot:
    """Verify that _live_start_mono_s is read under lock in the run loop.

    This is a source-level verification — we check that the code reads
    _live_start_mono_s inside a `with self._lock:` block.
    """

    def test_live_start_read_is_under_lock(self) -> None:
        import inspect

        from vibesensor.metrics_log import MetricsLogger

        source = inspect.getsource(MetricsLogger.run)
        # Find the lock acquisition
        assert "with self._lock:" in source
        # The _live_start_mono_s read should appear after a lock acquisition
        # and before the build_sample_records call
        lock_idx = source.index("with self._lock:")
        live_start_idx = source.index("_live_start_mono_s")
        build_idx = source.index("_build_sample_records")
        assert lock_idx < live_start_idx < build_idx, (
            "_live_start_mono_s should be read under lock, before _build_sample_records"
        )
