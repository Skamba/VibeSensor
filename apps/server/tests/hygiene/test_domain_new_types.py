"""Construction tests for typed domain concepts and their boundary codecs."""

from __future__ import annotations

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
    @pytest.mark.parametrize(
        ("rel_error", "expected"),
        [
            pytest.param(0.0, True, id="exact"),
            pytest.param(0.05, True, id="threshold-inclusive"),
            pytest.param(0.0501, False, id="above-threshold"),
        ],
    )
    def test_is_close_match_uses_inclusive_five_percent_threshold(
        self,
        rel_error: float,
        expected: bool,
    ) -> None:
        obs = OrderMatchObservation(
            predicted_hz=100.0,
            matched_hz=100.0 * (1.0 + rel_error),
            rel_error=rel_error,
            amp=1.0,
            location="front_left",
        )

        assert obs.is_close_match is expected

    @pytest.mark.parametrize(
        ("matched_hz", "expected_error"),
        [
            pytest.param(105.0, 5.0, id="above-predicted"),
            pytest.param(95.0, 5.0, id="below-predicted"),
        ],
    )
    def test_frequency_error_hz_is_absolute(
        self,
        matched_hz: float,
        expected_error: float,
    ) -> None:
        obs = OrderMatchObservation(
            predicted_hz=100.0,
            matched_hz=matched_hz,
            rel_error=0.05,
            amp=1.0,
            location="front_left",
        )
        assert obs.frequency_error_hz == expected_error

    @pytest.mark.parametrize(
        ("overrides", "message"),
        [
            pytest.param({"predicted_hz": 0.0}, "predicted_hz", id="zero-predicted"),
            pytest.param({"rel_error": -0.1}, "rel_error", id="negative-rel-error"),
        ],
    )
    def test_invalid_frequency_contract_rejected(
        self,
        overrides: dict[str, float],
        message: str,
    ) -> None:
        payload = {
            "predicted_hz": 100.0,
            "matched_hz": 100.0,
            "rel_error": 0.0,
            "amp": 1.0,
        }
        payload.update(overrides)
        with pytest.raises(ValueError, match=message):
            OrderMatchObservation(
                predicted_hz=payload["predicted_hz"],
                matched_hz=payload["matched_hz"],
                rel_error=payload["rel_error"],
                amp=payload["amp"],
                location="front_left",
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
        assert obs == OrderMatchObservation(
            predicted_hz=100.0,
            matched_hz=102.0,
            rel_error=0.02,
            amp=0.5,
            location="front_left",
            t_s=1.5,
            speed_kmh=60.0,
            phase="cruise",
        )

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
    @pytest.mark.parametrize(
        ("start_t_s", "end_t_s", "expected_duration"),
        [
            pytest.param(10.0, 20.0, 10.0, id="bounded"),
            pytest.param(10.0, 10.0, 0.0, id="zero-length"),
            pytest.param(None, 20.0, None, id="missing-start"),
            pytest.param(10.0, None, None, id="missing-end"),
        ],
    )
    def test_duration_s(
        self,
        start_t_s: float | None,
        end_t_s: float | None,
        expected_duration: float | None,
    ) -> None:
        interval = DrivingPhaseInterval(
            phase=DrivingPhase.CRUISE,
            start_t_s=start_t_s,
            end_t_s=end_t_s,
            speed_min_kmh=70.0,
            speed_max_kmh=75.0,
            has_fault_evidence=True,
        )

        assert interval.duration_s == expected_duration
        assert interval.phase is DrivingPhase.CRUISE
        assert interval.speed_min_kmh == 70.0
        assert interval.speed_max_kmh == 75.0
        assert interval.has_fault_evidence is True

    def test_temporal_ordering_invariant(self) -> None:
        with pytest.raises(ValueError, match="start_t_s"):
            DrivingPhaseInterval(phase=DrivingPhase.CRUISE, start_t_s=20.0, end_t_s=10.0)


# ---------------------------------------------------------------------------
# LocationIntensitySummary
# ---------------------------------------------------------------------------


class TestLocationIntensitySummary:
    def test_diagnostic_fields_prefer_usable_sample_metrics(self) -> None:
        summary = LocationIntensitySummary(
            location="front_left",
            sample_count=100,
            sample_coverage_ratio=0.9,
            sample_coverage_warning=False,
            usable_sample_count=80,
            usable_sample_coverage_ratio=0.75,
            usable_sample_coverage_warning=True,
        )
        assert summary.diagnostic_sample_count == 80
        assert summary.diagnostic_sample_coverage_ratio == 0.75
        assert summary.diagnostic_sample_coverage_warning is True

    def test_diagnostic_fields_fall_back_to_raw_sample_metrics(self) -> None:
        summary = LocationIntensitySummary(
            location="front_left",
            sample_count=100,
            sample_coverage_ratio=0.9,
            sample_coverage_warning=True,
        )

        assert summary.diagnostic_sample_count == 100
        assert summary.diagnostic_sample_coverage_ratio == 0.9
        assert summary.diagnostic_sample_coverage_warning is True

    @pytest.mark.parametrize(
        ("overrides", "message"),
        [
            pytest.param({"sample_count": -1}, "sample_count", id="negative-samples"),
            pytest.param({"usable_sample_count": -1}, "usable_sample_count", id="negative-usable"),
            pytest.param(
                {"sample_coverage_ratio": 1.5},
                "sample_coverage_ratio",
                id="sample-coverage-high",
            ),
            pytest.param(
                {"usable_sample_coverage_ratio": -0.1},
                "usable_sample_coverage_ratio",
                id="usable-coverage-low",
            ),
        ],
    )
    def test_invalid_sample_contract_rejected(
        self,
        overrides: dict[str, int | float],
        message: str,
    ) -> None:
        with pytest.raises(ValueError, match=message):
            LocationIntensitySummary(location="front_left", **overrides)

    def test_boundary_codec_from_mapping(self) -> None:
        raw = {
            "location": "rear_axle",
            "partial_coverage": True,
            "samples": 50,
            "sample_coverage_ratio": 0.8,
            "sample_coverage_warning": False,
            "usable_sample_count": 42,
            "usable_sample_coverage_ratio": 0.7,
            "usable_sample_coverage_warning": True,
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
        assert summary.usable_sample_count == 42
        assert summary.diagnostic_sample_count == 42
        assert summary.diagnostic_sample_coverage_ratio == 0.7
        assert summary.diagnostic_sample_coverage_warning is True
        assert summary.p95_intensity_db == 15.0
        assert summary.strength_bucket_distribution == StrengthBucketDistribution(
            total=5,
            counts={"l0": 5},
            percent_time_l0=100.0,
        )
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
        assert summary.phase_intensity is None
