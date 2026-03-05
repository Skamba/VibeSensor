"""Cross-cutting multi-domain regressions.

Each test verifies the specific bug fix by reproducing the original failure
condition and asserting the corrected behavior.
"""

from __future__ import annotations

from vibesensor.release_fetcher import ReleaseInfo
from vibesensor.runlog import as_float_or_none


def _make_release_info(version: str) -> ReleaseInfo:
    """Build a ReleaseInfo stub for version comparison tests."""
    return ReleaseInfo(
        tag=f"server-v{version}",
        version=version,
        asset_name=f"vibesensor-{version}.whl",
        asset_url=f"https://example.com/{version}.whl",
    )


class TestBug19FloorAmpZero:
    def test_zero_floor_amp_preserved(self) -> None:
        sample = {"strength_floor_amp_g": 0.0}
        _floor_raw = as_float_or_none(sample.get("strength_floor_amp_g"))
        floor_amp = _floor_raw if _floor_raw is not None else 0.0
        assert floor_amp == 0.0
        # Key: the value came from the sample, not the default
        assert _floor_raw == 0.0
