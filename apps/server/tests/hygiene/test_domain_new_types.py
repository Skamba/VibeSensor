"""Construction tests for typed domain concepts and their boundary codecs."""

from __future__ import annotations

import dataclasses

import pytest

from vibesensor.domain import (
    DrivingPhase,
    DrivingPhaseInterval,
    LocationIntensitySummary,
    OrderMatchObservation,
    PhaseIntensitySummary,
    StrengthBucketDistribution,
)
from vibesensor.shared.boundaries.summary_fields.hotspot import (
    location_intensity_summary_from_mapping,
)
from vibesensor.shared.boundaries.summary_fields.order_match import (
    order_match_observation_from_mapping,
)

# ---------------------------------------------------------------------------
# OrderMatchObservation
# ---------------------------------------------------------------------------


class TestOrderMatchObservation:
    def test_construction(self) -> None:
        obs = OrderMatchObservation(
            predicted_hz=100.0,
            matched_hz=102.0,
            rel_error=0.02,
            amp=0.5,
            location="front_left",
            t_s=1.5,
            speed_kmh=60.0,
        )
        assert obs.predicted_hz == 100.0
        assert obs.matched_hz == 102.0
        assert obs.location == "front_left"

    def test_frozen(self) -> None:
        obs = OrderMatchObservation(
            predicted_hz=100.0, matched_hz=100.0, rel_error=0.0, amp=1.0, location="x"
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            obs.amp = 2.0

    def test_has_slots(self) -> None:
        assert hasattr(OrderMatchObservation, "__slots__")

    def test_is_close_match(self) -> None:
        close = OrderMatchObservation(
            predicted_hz=100.0, matched_hz=104.0, rel_error=0.04, amp=1.0, location="x"
        )
        assert close.is_close_match
        far = OrderMatchObservation(
            predicted_hz=100.0, matched_hz=110.0, rel_error=0.10, amp=1.0, location="x"
        )
        assert not far.is_close_match

    def test_frequency_error_hz(self) -> None:
        obs = OrderMatchObservation(
            predicted_hz=100.0, matched_hz=105.0, rel_error=0.05, amp=1.0, location="x"
        )
        assert obs.frequency_error_hz == 5.0

    def test_invalid_predicted_hz_rejected(self) -> None:
        with pytest.raises(ValueError, match="predicted_hz"):
            OrderMatchObservation(
                predicted_hz=0.0, matched_hz=100.0, rel_error=0.0, amp=1.0, location="x"
            )

    def test_negative_rel_error_rejected(self) -> None:
        with pytest.raises(ValueError, match="rel_error"):
            OrderMatchObservation(
                predicted_hz=100.0, matched_hz=100.0, rel_error=-0.1, amp=1.0, location="x"
            )

    def test_boundary_codec_from_mapping(self) -> None:
        raw = {
            "predicted_hz": 100.0,
            "matched_hz": 102.0,
            "rel_error": 0.02,
            "amp": 0.5,
            "location": "front_left",
            "t_s": 1.5,
            "speed_kmh": 60.0,
            "phase": "cruise",
        }
        obs = order_match_observation_from_mapping(raw)
        assert obs.predicted_hz == 100.0
        assert obs.phase == "cruise"
        assert obs.t_s == 1.5

    def test_boundary_codec_missing_optional_keys(self) -> None:
        raw = {
            "predicted_hz": 100.0,
            "matched_hz": 100.0,
            "rel_error": 0.0,
            "amp": 1.0,
            "location": "x",
        }
        obs = order_match_observation_from_mapping(raw)
        assert obs.t_s is None
        assert obs.speed_kmh is None
        assert obs.phase is None


# ---------------------------------------------------------------------------
# DrivingPhaseInterval
# ---------------------------------------------------------------------------


class TestDrivingPhaseInterval:
    def test_construction(self) -> None:
        interval = DrivingPhaseInterval(
            phase=DrivingPhase.CRUISE,
            start_t_s=10.0,
            end_t_s=20.0,
            speed_min_kmh=50.0,
            speed_max_kmh=60.0,
            has_fault_evidence=True,
        )
        assert interval.phase is DrivingPhase.CRUISE
        assert interval.has_fault_evidence is True

    def test_frozen(self) -> None:
        interval = DrivingPhaseInterval(phase=DrivingPhase.IDLE)
        with pytest.raises(dataclasses.FrozenInstanceError):
            interval.phase = DrivingPhase.CRUISE

    def test_has_slots(self) -> None:
        assert hasattr(DrivingPhaseInterval, "__slots__")

    def test_duration_s(self) -> None:
        interval = DrivingPhaseInterval(phase=DrivingPhase.CRUISE, start_t_s=10.0, end_t_s=20.0)
        assert interval.duration_s == 10.0

    def test_duration_s_none(self) -> None:
        interval = DrivingPhaseInterval(phase=DrivingPhase.CRUISE)
        assert interval.duration_s is None

    def test_temporal_ordering_invariant(self) -> None:
        with pytest.raises(ValueError, match="start_t_s"):
            DrivingPhaseInterval(phase=DrivingPhase.CRUISE, start_t_s=20.0, end_t_s=10.0)


# ---------------------------------------------------------------------------
# LocationIntensitySummary
# ---------------------------------------------------------------------------


class TestLocationIntensitySummary:
    def test_construction(self) -> None:
        summary = LocationIntensitySummary(
            location="front_left",
            sample_count=100,
            sample_coverage_ratio=0.95,
            usable_sample_count=80,
            usable_sample_coverage_ratio=0.80,
            mean_intensity_db=12.5,
            p95_intensity_db=18.0,
            max_intensity_db=22.0,
            strength_bucket_distribution=StrengthBucketDistribution(
                total=100,
                counts={"l0": 10, "l1": 50, "l2": 40},
                percent_time_l0=10.0,
                percent_time_l1=50.0,
                percent_time_l2=40.0,
            ),
        )
        assert summary.location == "front_left"
        assert summary.sample_count == 100
        assert summary.diagnostic_sample_count == 80
        assert summary.mean_intensity_db == 12.5

    def test_frozen(self) -> None:
        summary = LocationIntensitySummary(location="x")
        with pytest.raises(dataclasses.FrozenInstanceError):
            summary.location = "y"

    def test_has_slots(self) -> None:
        assert hasattr(LocationIntensitySummary, "__slots__")

    def test_negative_sample_count_rejected(self) -> None:
        with pytest.raises(ValueError, match="sample_count"):
            LocationIntensitySummary(location="x", sample_count=-1)

    def test_invalid_coverage_ratio_rejected(self) -> None:
        with pytest.raises(ValueError, match="sample_coverage_ratio"):
            LocationIntensitySummary(location="x", sample_coverage_ratio=1.5)

    def test_invalid_usable_coverage_ratio_rejected(self) -> None:
        with pytest.raises(ValueError, match="usable_sample_coverage_ratio"):
            LocationIntensitySummary(location="x", usable_sample_coverage_ratio=1.5)

    def test_boundary_codec_from_mapping(self) -> None:
        raw = {
            "location": "rear_axle",
            "partial_coverage": True,
            "samples": 50,
            "sample_coverage_ratio": 0.8,
            "sample_coverage_warning": False,
            "mean_intensity_db": 10.0,
            "p50_intensity_db": 9.0,
            "p95_intensity_db": 15.0,
            "max_intensity_db": 20.0,
            "dropped_frames_delta": 0.0,
            "queue_overflow_drops_delta": None,
            "strength_bucket_distribution": {
                "total": 5,
                "counts": {"l0": 5},
                "percent_time_l0": 100.0,
            },
            "phase_intensity": {
                "cruise": {
                    "count": 2,
                    "mean_intensity_db": 12.0,
                    "max_intensity_db": 14.0,
                },
            },
        }
        summary = location_intensity_summary_from_mapping(raw)
        assert summary.location == "rear_axle"
        assert summary.partial_coverage is True
        assert summary.sample_count == 50  # from "samples" key
        assert summary.p95_intensity_db == 15.0
        assert summary.strength_bucket_distribution.total == 5
        assert summary.phase_intensity == {
            "cruise": PhaseIntensitySummary(
                count=2,
                mean_intensity_db=12.0,
                max_intensity_db=14.0,
            ),
        }

    def test_boundary_codec_prefers_sample_count_key(self) -> None:
        raw = {"location": "x", "sample_count": 42, "sample_coverage_ratio": 0.5}
        summary = location_intensity_summary_from_mapping(raw)
        assert summary.sample_count == 42

    def test_default_strength_bucket_distribution(self) -> None:
        summary = LocationIntensitySummary(location="x")
        assert summary.strength_bucket_distribution == StrengthBucketDistribution()
