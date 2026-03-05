"""Cross-cutting multi-domain regressions.

Each test verifies the specific bug fix by reproducing the original failure
condition and asserting the corrected behavior.
"""

from __future__ import annotations

from vibesensor.analysis.test_plan import _weighted_speed_window_label
from vibesensor.release_fetcher import ReleaseInfo


def _make_release_info(version: str) -> ReleaseInfo:
    """Build a ReleaseInfo stub for version comparison tests."""
    return ReleaseInfo(
        tag=f"server-v{version}",
        version=version,
        asset_name=f"vibesensor-{version}.whl",
        asset_url=f"https://example.com/{version}.whl",
    )


class TestBug14UniformSpeedLabel:
    def test_uniform_speed_shows_single_value(self) -> None:
        result = _weighted_speed_window_label([(50.0, 1.0), (50.0, 1.0)])
        assert result == "50 km/h"

    def test_range_shows_range(self) -> None:
        result = _weighted_speed_window_label([(40.0, 1.0), (60.0, 1.0)])
        assert "-" in result
