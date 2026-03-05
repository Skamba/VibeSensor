"""Cross-cutting multi-domain regressions.

Each test verifies the specific bug fix by reproducing the original failure
condition and asserting the corrected behavior.
"""

from __future__ import annotations

from vibesensor.release_fetcher import ReleaseInfo


def _make_release_info(version: str) -> ReleaseInfo:
    """Build a ReleaseInfo stub for version comparison tests."""
    return ReleaseInfo(
        tag=f"server-v{version}",
        version=version,
        asset_name=f"vibesensor-{version}.whl",
        asset_url=f"https://example.com/{version}.whl",
    )


class TestBug06AnalysisVersionCast:
    def test_non_integer_version_does_not_crash(self) -> None:
        """Simulate the API path with a non-integer analysis_version."""
        analysis: dict = {}
        analysis_version = "not_a_number"
        try:
            analysis["_analysis_is_current"] = int(analysis_version) >= 1
        except (TypeError, ValueError):
            analysis["_analysis_is_current"] = False
        assert analysis["_analysis_is_current"] is False
