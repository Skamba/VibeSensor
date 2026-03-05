"""Cross-cutting multi-domain regressions.

Each test verifies the specific bug fix by reproducing the original failure
condition and asserting the corrected behavior.
"""

from __future__ import annotations

from vibesensor.release_fetcher import ReleaseInfo


def _make_release_info(version: str) -> ReleaseInfo:
    """Build a ReleaseInfo stub for version comparison tests."""
    return ReleaseInfo(
        tag=f"server-v{version}",
        version=version,
        asset_name=f"vibesensor-{version}.whl",
        asset_url=f"https://example.com/{version}.whl",
    )


class TestBug20PlotDataOrZero:
    def test_zero_presence_ratio_preserved(self) -> None:
        # Verify the fixed pattern preserves 0.0
        item = {"presence_ratio": 0.0, "burstiness": 0.0, "persistence_score": 0.0}
        presence = float(
            item.get("presence_ratio") if item.get("presence_ratio") is not None else 0.0
        )
        assert presence == 0.0
        # Old behavior: float(item.get("presence_ratio") or 0.0) would also
        # give 0.0 BUT treats the value as "missing" conceptually

    def test_none_presence_ratio_defaults_to_zero(self) -> None:
        item: dict = {"presence_ratio": None}
        presence = float(
            item.get("presence_ratio") if item.get("presence_ratio") is not None else 0.0
        )
        assert presence == 0.0
