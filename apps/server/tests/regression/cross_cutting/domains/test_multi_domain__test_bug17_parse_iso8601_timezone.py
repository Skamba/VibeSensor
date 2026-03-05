"""Cross-cutting multi-domain regressions.

Each test verifies the specific bug fix by reproducing the original failure
condition and asserting the corrected behavior.
"""

from __future__ import annotations

from datetime import UTC

import pytest

from vibesensor.release_fetcher import ReleaseInfo
from vibesensor.runlog import parse_iso8601


def _make_release_info(version: str) -> ReleaseInfo:
    """Build a ReleaseInfo stub for version comparison tests."""
    return ReleaseInfo(
        tag=f"server-v{version}",
        version=version,
        asset_name=f"vibesensor-{version}.whl",
        asset_url=f"https://example.com/{version}.whl",
    )


class TestBug17ParseIso8601Timezone:
    def test_naive_string_gets_utc(self) -> None:
        dt = parse_iso8601("2024-01-01 12:00:00")
        assert dt is not None
        assert dt.tzinfo is not None  # Should NOT be naive

    def test_aware_string_keeps_timezone(self) -> None:
        dt = parse_iso8601("2024-01-01T12:00:00+02:00")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_z_suffix_parsed_as_utc(self) -> None:
        dt = parse_iso8601("2024-01-01T12:00:00Z")
        assert dt is not None
        assert dt.tzinfo == UTC

    def test_naive_and_aware_can_be_subtracted(self) -> None:
        dt1 = parse_iso8601("2024-01-01 12:00:00")
        dt2 = parse_iso8601("2024-01-01T13:00:00Z")
        assert dt1 is not None and dt2 is not None
        # This should NOT raise TypeError about naive vs aware
        diff = (dt2 - dt1).total_seconds()
        assert diff == pytest.approx(3600.0)
