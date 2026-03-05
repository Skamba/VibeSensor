"""Cross-cutting multi-domain regressions.

Each test verifies the specific bug fix by reproducing the original failure
condition and asserting the corrected behavior.
"""

from __future__ import annotations

from vibesensor.analysis.summary import confidence_label
from vibesensor.release_fetcher import ReleaseInfo


def _make_release_info(version: str) -> ReleaseInfo:
    """Build a ReleaseInfo stub for version comparison tests."""
    return ReleaseInfo(
        tag=f"server-v{version}",
        version=version,
        asset_name=f"vibesensor-{version}.whl",
        asset_url=f"https://example.com/{version}.whl",
    )


class TestBug10ConfidenceLabelNone:
    def test_none_confidence_returns_low(self) -> None:
        label_key, tone, pct_text = confidence_label(None)
        assert label_key == "CONFIDENCE_LOW"
        assert tone == "neutral"
        assert pct_text == "0%"

    def test_zero_confidence_returns_low(self) -> None:
        label_key, tone, pct_text = confidence_label(0.0)
        assert label_key == "CONFIDENCE_LOW"
