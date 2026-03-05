"""Cross-cutting multi-domain regressions.

Each test verifies the specific bug fix by reproducing the original failure
condition and asserting the corrected behavior.
"""

from __future__ import annotations

import pytest

from vibesensor.analysis.summary import _compute_run_timing
from vibesensor.release_fetcher import ReleaseInfo


def _make_release_info(version: str) -> ReleaseInfo:
    """Build a ReleaseInfo stub for version comparison tests."""
    return ReleaseInfo(
        tag=f"server-v{version}",
        version=version,
        asset_name=f"vibesensor-{version}.whl",
        asset_url=f"https://example.com/{version}.whl",
    )


class TestBug01ComputeRunTimingTimedelta:
    def test_end_ts_from_samples_uses_timedelta(self) -> None:
        meta = {"start_time_utc": "2024-01-01T12:00:00Z"}
        samples = [{"t_s": 0.0}, {"t_s": 300.0}]
        _, start, end, duration = _compute_run_timing(meta, samples, "test")
        assert start is not None
        assert end is not None
        assert (end - start).total_seconds() == pytest.approx(300.0)
        assert duration == pytest.approx(300.0)
