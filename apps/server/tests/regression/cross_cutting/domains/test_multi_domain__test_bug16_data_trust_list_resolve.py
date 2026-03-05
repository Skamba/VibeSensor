"""Cross-cutting multi-domain regressions.

Each test verifies the specific bug fix by reproducing the original failure
condition and asserting the corrected behavior.
"""

from __future__ import annotations

from vibesensor.analysis.report_data_builder import _resolve_i18n
from vibesensor.release_fetcher import ReleaseInfo


def _make_release_info(version: str) -> ReleaseInfo:
    """Build a ReleaseInfo stub for version comparison tests."""
    return ReleaseInfo(
        tag=f"server-v{version}",
        version=version,
        asset_name=f"vibesensor-{version}.whl",
        asset_url=f"https://example.com/{version}.whl",
    )


class TestBug16DataTrustListResolve:
    def test_list_explanation_is_resolved(self) -> None:
        # A list of i18n refs should be resolved, not stringified as "[{...}]"
        value = [
            {"_i18n_key": "SOURCE_WHEEL_TIRE"},
            {"_i18n_key": "SOURCE_ENGINE"},
        ]
        result = _resolve_i18n("en", value)
        assert "[" not in result  # Should not contain raw list representation
        assert isinstance(result, str)
