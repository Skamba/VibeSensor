"""Cross-cutting multi-domain regressions.

Each test verifies the specific bug fix by reproducing the original failure
condition and asserting the corrected behavior.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from vibesensor.release_fetcher import ReleaseInfo, ServerReleaseFetcher


def _make_release_info(version: str) -> ReleaseInfo:
    """Build a ReleaseInfo stub for version comparison tests."""
    return ReleaseInfo(
        tag=f"server-v{version}",
        version=version,
        asset_name=f"vibesensor-{version}.whl",
        asset_url=f"https://example.com/{version}.whl",
    )


class TestBug05ReleaseVersionComparison:
    def test_downgrade_returns_none(self) -> None:
        fetcher = ServerReleaseFetcher.__new__(ServerReleaseFetcher)
        fetcher.find_latest_release = MagicMock(return_value=_make_release_info("2024.1.0"))
        result = fetcher.check_update_available("2025.6.0")
        assert result is None

    def test_upgrade_returns_release(self) -> None:
        fetcher = ServerReleaseFetcher.__new__(ServerReleaseFetcher)
        fetcher.find_latest_release = MagicMock(return_value=_make_release_info("2026.1.0"))
        result = fetcher.check_update_available("2025.6.0")
        assert result is not None
        assert result.version == "2026.1.0"
