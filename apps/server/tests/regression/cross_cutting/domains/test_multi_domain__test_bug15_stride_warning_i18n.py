"""Cross-cutting multi-domain regressions.

Each test verifies the specific bug fix by reproducing the original failure
condition and asserting the corrected behavior.
"""

from __future__ import annotations

from vibesensor.release_fetcher import ReleaseInfo
from vibesensor.report_i18n import tr


def _make_release_info(version: str) -> ReleaseInfo:
    """Build a ReleaseInfo stub for version comparison tests."""
    return ReleaseInfo(
        tag=f"server-v{version}",
        version=version,
        asset_name=f"vibesensor-{version}.whl",
        asset_url=f"https://example.com/{version}.whl",
    )


class TestBug15StrideWarningI18n:
    def test_i18n_keys_exist(self) -> None:
        result_en = tr("en", "SUITABILITY_CHECK_ANALYSIS_SAMPLING")
        assert result_en == "Analysis sampling"
        result_nl = tr("nl", "SUITABILITY_CHECK_ANALYSIS_SAMPLING")
        assert result_nl == "Analysebemonstering"

    def test_stride_warning_i18n_key(self) -> None:
        result = tr("en", "SUITABILITY_ANALYSIS_SAMPLING_STRIDE_WARNING", stride="4")
        assert "stride 4" in result
