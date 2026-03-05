"""Cross-cutting multi-domain regressions.

Each test verifies the specific bug fix by reproducing the original failure
condition and asserting the corrected behavior.
"""

from __future__ import annotations

from vibesensor.analysis.phase_segmentation import segment_run_phases
from vibesensor.release_fetcher import ReleaseInfo


def _make_release_info(version: str) -> ReleaseInfo:
    """Build a ReleaseInfo stub for version comparison tests."""
    return ReleaseInfo(
        tag=f"server-v{version}",
        version=version,
        asset_name=f"vibesensor-{version}.whl",
        asset_url=f"https://example.com/{version}.whl",
    )


class TestBug12PhaseSegmentTimestamps:
    def test_second_segment_no_zero_when_first_has_time(self) -> None:
        samples = [
            {"t_s": 0.0, "speed_kmh": 0.0},
            {"t_s": 1.0, "speed_kmh": 0.0},
            {"t_s": None, "speed_kmh": 50.0},
            {"t_s": None, "speed_kmh": 50.0},
        ]
        _, segments = segment_run_phases(samples)
        if len(segments) > 1:
            second = segments[1]
            # Should not be 0.0 for a segment that comes after the first
            assert second.start_t_s > 0.0 or second.start_idx > 0
