"""Boundary reconstruction regression tests built from canonical test fixtures."""

from __future__ import annotations

import pytest
from test_support import build_speed_sweep_fault_samples, standard_metadata

from vibesensor.domain import SpeedProfile
from vibesensor.domain.snapshots import DrivingPhaseSummary, SpeedProfileSummary
from vibesensor.shared.boundaries.diagnostic_case import (
    test_run_from_summary as _reconstruct,
)
from vibesensor.use_cases.diagnostics import summarize_run_data


@pytest.fixture(scope="module")
def golden_summary() -> dict:
    """Build a representative summary via shared synthetic scenario builders."""
    return summarize_run_data(
        standard_metadata(),
        build_speed_sweep_fault_samples(
            speed_start_kmh=40.0,
            speed_end_kmh=120.0,
            fault_sensor="front-left",
            other_sensors=["front-right", "rear-left", "rear-right"],
            n_samples=50,
            fault_amp=0.06,
            fault_vib_db=24.0,
        ),
        include_samples=False,
    )


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

        sp = SpeedProfile.from_stats(
            SpeedProfileSummary.from_dict(raw_speed_stats),
            DrivingPhaseSummary.from_dict(raw_phase_info) if raw_phase_info else None,
        )
        assert sp == test_run.speed_profile


class TestRoundTripParity:
    """Round-trip parity tests for snapshot from_dict factories."""

    def test_speed_stats_snapshot_from_dict_empty(self) -> None:
        snap = SpeedProfileSummary.from_dict({})
        assert snap.min_kmh is None
        assert snap.max_kmh is None
        assert snap.steady_speed is False
        assert snap.sample_count == 0

    def test_speed_stats_snapshot_from_dict_partial(self) -> None:
        snap = SpeedProfileSummary.from_dict({"min_kmh": 30, "max_kmh": 80})
        assert snap.min_kmh == 30.0
        assert snap.max_kmh == 80.0
        assert snap.steady_speed is False
        assert snap.sample_count == 0

    def test_phase_summary_snapshot_from_dict_empty(self) -> None:
        snap = DrivingPhaseSummary.from_dict({})
        assert snap.has_cruise is False
        assert snap.has_acceleration is False
        assert snap.cruise_pct == 0.0

    def test_phase_summary_fallback_to_phase_counts(self) -> None:
        """When top-level has_cruise is missing, fall back to phase_counts."""
        snap = DrivingPhaseSummary.from_dict(
            {
                "phase_counts": {"cruise": 10, "acceleration": 5},
            }
        )
        assert snap.has_cruise is True
        assert snap.has_acceleration is True

    def test_phase_summary_fallback_to_phase_pcts(self) -> None:
        """When top-level cruise_pct is missing, fall back to phase_pcts."""
        snap = DrivingPhaseSummary.from_dict(
            {
                "phase_pcts": {"cruise": 45.0, "idle": 12.0, "speed_unknown": 8.0},
            }
        )
        assert snap.cruise_pct == pytest.approx(45.0)
        assert snap.idle_pct == pytest.approx(12.0)
        assert snap.speed_unknown_pct == pytest.approx(8.0)

    def test_speed_profile_from_typed_snapshots_with_empty_inputs(self) -> None:
        sp = SpeedProfile.from_stats(SpeedProfileSummary())
        assert sp.min_kmh == 0.0
        assert sp.max_kmh == 0.0
        assert sp.steady_speed is False
        assert sp.sample_count == 0
        assert sp.cruise_fraction == 0.0
