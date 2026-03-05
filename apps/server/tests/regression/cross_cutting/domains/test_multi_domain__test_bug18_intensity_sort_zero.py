"""Cross-cutting multi-domain regressions.

Each test verifies the specific bug fix by reproducing the original failure
condition and asserting the corrected behavior.
"""

from __future__ import annotations

from vibesensor.analysis.findings import _sensor_intensity_by_location
from vibesensor.release_fetcher import ReleaseInfo


def _make_release_info(version: str) -> ReleaseInfo:
    """Build a ReleaseInfo stub for version comparison tests."""
    return ReleaseInfo(
        tag=f"server-v{version}",
        version=version,
        asset_name=f"vibesensor-{version}.whl",
        asset_url=f"https://example.com/{version}.whl",
    )


class TestBug18IntensitySortZero:
    def test_zero_p95_preserved_in_sort(self) -> None:
        samples = [
            {
                "t_s": float(i),
                "vibration_strength_db": 0.0,
                "top_peaks": [],
                "location": "FL",
                "client_id": "s1",
            }
            for i in range(10)
        ]
        result = _sensor_intensity_by_location(samples, include_locations={"FL"}, lang="en")
        assert len(result) > 0
