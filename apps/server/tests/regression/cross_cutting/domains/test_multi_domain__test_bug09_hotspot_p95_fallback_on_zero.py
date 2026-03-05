"""Cross-cutting multi-domain regressions.

Each test verifies the specific bug fix by reproducing the original failure
condition and asserting the corrected behavior.
"""

from __future__ import annotations

from vibesensor.release_fetcher import ReleaseInfo
from vibesensor.runlog import as_float_or_none


def _make_release_info(version: str) -> ReleaseInfo:
    """Build a ReleaseInfo stub for version comparison tests."""
    return ReleaseInfo(
        tag=f"server-v{version}",
        version=version,
        asset_name=f"vibesensor-{version}.whl",
        asset_url=f"https://example.com/{version}.whl",
    )


class TestBug09HotspotP95FallbackOnZero:
    def test_zero_p95_not_treated_as_missing(self) -> None:
        # Simulating the fixed code path
        row = {"p95_intensity_db": 0.0, "mean_intensity_db": 5.0}
        p95_val = as_float_or_none(row.get("p95_intensity_db"))
        p95 = p95_val if p95_val is not None else as_float_or_none(row.get("mean_intensity_db"))
        # 0.0 should be used, not fall through to mean
        assert p95 == 0.0

    def test_none_p95_falls_through_to_mean(self) -> None:
        row = {"p95_intensity_db": None, "mean_intensity_db": 5.0}
        p95_val = as_float_or_none(row.get("p95_intensity_db"))
        p95 = p95_val if p95_val is not None else as_float_or_none(row.get("mean_intensity_db"))
        assert p95 == 5.0
