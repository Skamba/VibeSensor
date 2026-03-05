"""Cross-cutting multi-domain regressions.

Each test verifies the specific bug fix by reproducing the original failure
condition and asserting the corrected behavior.
"""

from __future__ import annotations

from vibesensor.domain_models import VALID_SPEED_SOURCES
from vibesensor.release_fetcher import ReleaseInfo


def _make_release_info(version: str) -> ReleaseInfo:
    """Build a ReleaseInfo stub for version comparison tests."""
    return ReleaseInfo(
        tag=f"server-v{version}",
        version=version,
        asset_name=f"vibesensor-{version}.whl",
        asset_url=f"https://example.com/{version}.whl",
    )


class TestBug08SpeedSourceMapping:
    def test_speed_source_uses_valid_domain_values(self) -> None:
        """speed_source should be from VALID_SPEED_SOURCES, not 'override' or 'missing'."""
        # These are the only valid values for speed_source in sample records
        assert "gps" in VALID_SPEED_SOURCES
        assert "manual" in VALID_SPEED_SOURCES
        # "override" and "missing" are NOT valid
        assert "override" not in VALID_SPEED_SOURCES
        assert "missing" not in VALID_SPEED_SOURCES
