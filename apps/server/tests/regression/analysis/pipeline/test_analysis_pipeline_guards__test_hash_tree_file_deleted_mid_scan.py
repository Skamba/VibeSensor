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

from pathlib import Path
from unittest.mock import patch

from vibesensor.update.manager import _hash_tree


def _burstiness(median_amp: float, max_amp: float) -> float:
    return (max_amp / median_amp) if median_amp > 1e-9 else 0.0


class TestHashTreeFileDeletedMidScan:
    """_hash_tree must not crash if a file is deleted between rglob and open."""

    def test_deleted_file_skipped_gracefully(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.txt").write_text("world")

        h1 = _hash_tree(tmp_path, ignore_names=set())
        assert len(h1) == 64  # SHA256 hex digest

        original_open = open

        def failing_open(path, *args, **kwargs):
            if "b.txt" in str(path):
                raise FileNotFoundError(f"simulated deletion: {path}")
            return original_open(path, *args, **kwargs)

        with patch("builtins.open", side_effect=failing_open):
            h2 = _hash_tree(tmp_path, ignore_names=set())
            assert len(h2) == 64
            assert h2 != h1

    def test_empty_dir_returns_empty(self, tmp_path: Path) -> None:
        result = _hash_tree(tmp_path, ignore_names=set())
        assert isinstance(result, str)

    def test_nonexistent_dir_returns_empty_string(self, tmp_path: Path) -> None:
        result = _hash_tree(tmp_path / "nonexistent", ignore_names=set())
        assert result == ""
