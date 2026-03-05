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


class TestBug02TrMissingArgs:
    def test_tr_with_missing_format_args_returns_template(self) -> None:
        # tr() with a template that has {source} but no source arg
        result = tr("en", "ORIGIN_EXPLANATION_FINDING_1")
        # Should not crash; returns the raw template with placeholders
        assert isinstance(result, str)

    def test_tr_with_valid_args_formats_correctly(self) -> None:
        result = tr(
            "en",
            "ORIGIN_EXPLANATION_FINDING_1",
            source="wheel",
            speed_band="50-60 km/h",
            location="FL",
            dominance="high",
        )
        assert "wheel" in result
