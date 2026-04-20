"""Boundary reconstruction regression tests built from canonical test fixtures."""

from __future__ import annotations

import pytest
from test_support import build_speed_sweep_fault_samples, standard_metadata

from vibesensor.adapters.analysis_summary import summarize_sensor_frames
from vibesensor.domain import SpeedProfile
from vibesensor.shared.boundaries.analysis_payloads.reconstruction import (
    test_run_from_summary as _reconstruct,
)
from vibesensor.shared.boundaries.codecs import (
    driving_phase_summary_from_mapping,
    speed_profile_summary_from_mapping,
)
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings


@pytest.fixture(scope="module")
def golden_summary() -> dict:
    """Build a representative summary via the canonical typed diagnostics path."""
    return summarize_sensor_frames(
        run_metadata_from_mapping(standard_metadata()),
        sensor_frames_from_mappings(
            build_speed_sweep_fault_samples(
                speed_start_kmh=40.0,
                speed_end_kmh=120.0,
                fault_sensor="front-left",
                other_sensors=["front-right", "rear-left", "rear-right"],
                n_samples=50,
                fault_amp=0.06,
                fault_vib_db=24.0,
            )
        ),
        include_samples=False,
    )


class TestGoldenFileReconstruction:
    """Reconstruct a canonical summary fixture into the typed test-run model."""

    def test_test_run_from_summary_does_not_raise(self, golden_summary: dict) -> None:
        test_run = _reconstruct(golden_summary)
        assert test_run is not None
        assert test_run.capture.run_id

    def test_speed_profile_reconstructed(self, golden_summary: dict) -> None:
        test_run = _reconstruct(golden_summary)
        if "speed_stats" in golden_summary:
            assert test_run.speed_profile is not None
            assert test_run.speed_profile.sample_count >= 0

    def test_findings_reconstructed(self, golden_summary: dict) -> None:
        test_run = _reconstruct(golden_summary)
        for finding in test_run.findings:
            assert finding.confidence_assessment is not None

    def test_speed_profile_from_boundary_snapshots_matches(self, golden_summary: dict) -> None:
        test_run = _reconstruct(golden_summary)
        raw_speed_stats = golden_summary.get("speed_stats")
        raw_phase_info = golden_summary.get("phase_info", golden_summary.get("phase_summary"))

        if raw_speed_stats is None:
            pytest.skip("No speed_stats in golden summary")

        speed_profile = SpeedProfile.from_stats(
            speed_profile_summary_from_mapping(raw_speed_stats),
            driving_phase_summary_from_mapping(raw_phase_info) if raw_phase_info else None,
        )
        assert speed_profile == test_run.speed_profile


class TestRoundTripParity:
    """Round-trip parity tests for boundary snapshot codecs."""

    def test_speed_stats_snapshot_from_mapping_empty(self) -> None:
        snap = speed_profile_summary_from_mapping({})
        assert snap.min_kmh is None
        assert snap.max_kmh is None
        assert snap.steady_speed is False
        assert snap.sample_count == 0

    def test_speed_stats_snapshot_from_mapping_partial(self) -> None:
        snap = speed_profile_summary_from_mapping({"min_kmh": 30, "max_kmh": 80})
        assert snap.min_kmh == 30.0
        assert snap.max_kmh == 80.0
        assert snap.steady_speed is False
        assert snap.sample_count == 0

    def test_phase_summary_snapshot_from_mapping_empty(self) -> None:
        snap = driving_phase_summary_from_mapping({})
        assert snap.has_cruise is False
        assert snap.has_acceleration is False
        assert snap.cruise_pct == 0.0

    def test_phase_summary_derives_flags_from_phase_counts(self) -> None:
        snap = driving_phase_summary_from_mapping(
            {"phase_counts": {"cruise": 10, "acceleration": 5}}
        )
        assert snap.has_cruise is True
        assert snap.has_acceleration is True

    def test_phase_summary_derives_percentages_from_phase_pcts(self) -> None:
        snap = driving_phase_summary_from_mapping(
            {"phase_pcts": {"cruise": 45.0, "idle": 12.0, "speed_unknown": 8.0}}
        )
        assert snap.cruise_pct == pytest.approx(45.0)
        assert snap.idle_pct == pytest.approx(12.0)
        assert snap.speed_unknown_pct == pytest.approx(8.0)

    def test_phase_summary_ignores_legacy_flat_fields_without_canonical_values(self) -> None:
        snap = driving_phase_summary_from_mapping(
            {
                "has_cruise": True,
                "has_acceleration": True,
                "cruise_pct": 45.0,
                "idle_pct": 12.0,
                "speed_unknown_pct": 8.0,
            }
        )
        assert snap.has_cruise is False
        assert snap.has_acceleration is False
        assert snap.cruise_pct == 0.0
        assert snap.idle_pct == 0.0
        assert snap.speed_unknown_pct == 0.0

    def test_speed_profile_from_typed_snapshots_with_empty_inputs(self) -> None:
        speed_profile = SpeedProfile.from_stats(speed_profile_summary_from_mapping({}))
        assert speed_profile.min_kmh == 0.0
        assert speed_profile.max_kmh == 0.0
        assert speed_profile.steady_speed is False
        assert speed_profile.sample_count == 0
        assert speed_profile.cruise_fraction == 0.0
