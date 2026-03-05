"""Cross-cutting multi-domain regressions.

Each test verifies the specific bug fix by reproducing the original failure
condition and asserting the corrected behavior.
"""

from __future__ import annotations

import pytest

from vibesensor.analysis.helpers import _speed_bin_label
from vibesensor.release_fetcher import ReleaseInfo


def _make_release_info(version: str) -> ReleaseInfo:
    """Build a ReleaseInfo stub for version comparison tests."""
    return ReleaseInfo(
        tag=f"server-v{version}",
        version=version,
        asset_name=f"vibesensor-{version}.whl",
        asset_url=f"https://example.com/{version}.whl",
    )


class TestBug04SpeedBinLabelNonFinite:
    @pytest.mark.parametrize("value", [float("nan"), float("inf")])
    def test_non_finite_returns_fallback(self, value: float) -> None:
        assert _speed_bin_label(value) == "0-10 km/h"

    def test_normal_value_works(self) -> None:
        assert _speed_bin_label(55.0) == "50-60 km/h"
