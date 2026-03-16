"""Golden-file regression test for boundary reconstruction.

Uses ``examples/sample_complete_run.jsonl`` to verify historical summaries
reconstruct correctly through ``test_run_from_summary`` → domain objects.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vibesensor.domain.snapshots import PhaseSummarySnapshot, SpeedStatsSnapshot
from vibesensor.shared.boundaries.diagnostic_case import (
    speed_profile_from_stats,
)
from vibesensor.shared.boundaries.diagnostic_case import (
    test_run_from_summary as _reconstruct,
)
from vibesensor.use_cases.diagnostics import summarize_run_data

_GOLDEN_FILE = Path(__file__).resolve().parents[5] / "examples" / "sample_complete_run.jsonl"


@pytest.fixture(scope="module")
def golden_summary() -> dict:
    """Load golden JSONL, run through analysis pipeline, return summary."""
    records: list[dict] = []
    with _GOLDEN_FILE.open() as f:
        for line in f:
            records.append(json.loads(line))

    metadata = records[0]
    samples = [r for r in records if r.get("record_type") == "sample"]
    return summarize_run_data(metadata, samples)


class TestGoldenFileReconstruction:
    def test_test_run_from_summary_does_not_raise(self, golden_summary: dict) -> None:
        test_run = _reconstruct(golden_summary)
        assert test_run is not None
        assert test_run.capture.run_id

    def test_speed_profile_reconstructed(self, golden_summary: dict) -> None:
        test_run = _reconstruct(golden_summary)
        # The golden file has speed data, so speed_profile should exist
        if "speed_stats" in golden_summary:
            assert test_run.speed_profile is not None
            assert test_run.speed_profile.sample_count >= 0

    def test_findings_reconstructed(self, golden_summary: dict) -> None:
        test_run = _reconstruct(golden_summary)
        # Every finding must have a confidence assessment after backfill
        for f in test_run.findings:
            assert f.confidence_assessment is not None

    def test_speed_profile_from_typed_snapshots_matches(self, golden_summary: dict) -> None:
        """Typed snapshot construction produces the same SpeedProfile as
        the full test_run_from_summary pipeline."""
        test_run = _reconstruct(golden_summary)
        raw_speed_stats = golden_summary.get("speed_stats")
        raw_phase_info = golden_summary.get("phase_info", golden_summary.get("phase_summary"))

        if raw_speed_stats is None:
            pytest.skip("No speed_stats in golden summary")

        sp = speed_profile_from_stats(
            SpeedStatsSnapshot.from_dict(raw_speed_stats),
            PhaseSummarySnapshot.from_dict(raw_phase_info) if raw_phase_info else None,
        )
        assert sp == test_run.speed_profile


class TestRoundTripParity:
    """Round-trip parity tests for snapshot from_dict factories."""

    def test_speed_stats_snapshot_from_dict_empty(self) -> None:
        snap = SpeedStatsSnapshot.from_dict({})
        assert snap.min_kmh is None
        assert snap.max_kmh is None
        assert snap.steady_speed is False
        assert snap.sample_count == 0

    def test_speed_stats_snapshot_from_dict_partial(self) -> None:
        snap = SpeedStatsSnapshot.from_dict({"min_kmh": 30, "max_kmh": 80})
        assert snap.min_kmh == 30.0
        assert snap.max_kmh == 80.0
        assert snap.steady_speed is False
        assert snap.sample_count == 0

    def test_phase_summary_snapshot_from_dict_empty(self) -> None:
        snap = PhaseSummarySnapshot.from_dict({})
        assert snap.has_cruise is False
        assert snap.has_acceleration is False
        assert snap.cruise_pct == 0.0

    def test_phase_summary_fallback_to_phase_counts(self) -> None:
        """When top-level has_cruise is missing, fall back to phase_counts."""
        snap = PhaseSummarySnapshot.from_dict(
            {
                "phase_counts": {"cruise": 10, "acceleration": 5},
            }
        )
        assert snap.has_cruise is True
        assert snap.has_acceleration is True

    def test_phase_summary_fallback_to_phase_pcts(self) -> None:
        """When top-level cruise_pct is missing, fall back to phase_pcts."""
        snap = PhaseSummarySnapshot.from_dict(
            {
                "phase_pcts": {"cruise": 45.0, "idle": 12.0, "speed_unknown": 8.0},
            }
        )
        assert snap.cruise_pct == pytest.approx(45.0)
        assert snap.idle_pct == pytest.approx(12.0)
        assert snap.speed_unknown_pct == pytest.approx(8.0)

    def test_speed_profile_from_stats_with_empty_snapshots(self) -> None:
        sp = speed_profile_from_stats(SpeedStatsSnapshot())
        assert sp.min_kmh == 0.0
        assert sp.max_kmh == 0.0
        assert sp.steady_speed is False
        assert sp.sample_count == 0
        assert sp.cruise_fraction == 0.0
