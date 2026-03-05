"""Cross-cutting multi-domain regressions.

Each test verifies the specific bug fix by reproducing the original failure
condition and asserting the corrected behavior.
"""

from __future__ import annotations

import pytest

from vibesensor.analysis.report_data_builder import _order_label_human
from vibesensor.release_fetcher import ReleaseInfo


def _make_release_info(version: str) -> ReleaseInfo:
    """Build a ReleaseInfo stub for version comparison tests."""
    return ReleaseInfo(
        tag=f"server-v{version}",
        version=version,
        asset_name=f"vibesensor-{version}.whl",
        asset_url=f"https://example.com/{version}.whl",
    )


class TestBug11OrderLabelCaseInsensitive:
    @pytest.mark.parametrize("label", ["1x Wheel", "2x ENGINE"])
    def test_case_insensitive_match(self, label: str) -> None:
        result = _order_label_human("en", label)
        assert "order" in result.lower()
