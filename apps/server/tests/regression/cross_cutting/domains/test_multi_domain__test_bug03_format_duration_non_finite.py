"""Cross-cutting multi-domain regressions.

Each test verifies the specific bug fix by reproducing the original failure
condition and asserting the corrected behavior.
"""

from __future__ import annotations

import pytest

from vibesensor.analysis.helpers import _format_duration
from vibesensor.release_fetcher import ReleaseInfo


def _make_release_info(version: str) -> ReleaseInfo:
    """Build a ReleaseInfo stub for version comparison tests."""
    return ReleaseInfo(
        tag=f"server-v{version}",
        version=version,
        asset_name=f"vibesensor-{version}.whl",
        asset_url=f"https://example.com/{version}.whl",
    )


class TestBug03FormatDurationNonFinite:
    @pytest.mark.parametrize("value", [float("inf"), float("nan")])
    def test_non_finite_returns_zero(self, value: float) -> None:
        assert _format_duration(value) == "00:00.0"

    def test_normal_value_formats_correctly(self) -> None:
        assert _format_duration(125.3) == "02:05.3"
