"""Domain value-object tests for speed profiles and run suitability."""

from __future__ import annotations

import pytest

from vibesensor.domain.driving_phase_summary import DrivingPhaseSummary
from vibesensor.domain.run_suitability import RunSuitability, SuitabilityCheck
from vibesensor.domain.speed_profile import SpeedProfile
from vibesensor.domain.speed_profile_summary import SpeedProfileSummary
from vibesensor.recording.run_suitability_codec import run_suitability_from_payload
from vibesensor.summary.speed_phase_codecs import driving_phase_summary_from_mapping


class TestSpeedProfile:
    def test_speed_range_kmh(self) -> None:
        sp = SpeedProfile(min_kmh=40.0, max_kmh=80.0)
        assert sp.speed_range_kmh == 40.0

    def test_from_stats_full(self) -> None:
        speed_stats = SpeedProfileSummary(
            min_kmh=30.0,
            max_kmh=90.0,
            mean_kmh=60.0,
            stddev_kmh=15.0,
            steady_speed=True,
            sample_count=500,
        )
        phase_summary = DrivingPhaseSummary(
            has_cruise=True,
            has_acceleration=True,
            cruise_pct=65.0,
            idle_pct=10.0,
            speed_unknown_pct=5.0,
        )
        sp = SpeedProfile.from_stats(speed_stats, phase_summary)
        assert sp.min_kmh == 30.0
        assert sp.max_kmh == 90.0
        assert sp.mean_kmh == 60.0
        assert sp.steady_speed is True
        assert sp.has_cruise is True
        assert sp.has_acceleration is True
        assert sp.cruise_fraction == pytest.approx(0.65)
        assert sp.idle_fraction == pytest.approx(0.10)
        assert sp.speed_unknown_fraction == pytest.approx(0.05)
        assert sp.sample_count == 500

    def test_from_stats_empty(self) -> None:
        sp = SpeedProfile.from_stats(SpeedProfileSummary())
        assert sp.min_kmh == 0.0
        assert sp.max_kmh == 0.0
        assert not sp.steady_speed
        assert not sp.has_acceleration
        assert sp.idle_fraction == 0.0
        assert sp.speed_unknown_fraction == 0.0

    def test_from_stats_no_phase(self) -> None:
        sp = SpeedProfile.from_stats(SpeedProfileSummary(min_kmh=10, max_kmh=50))
        assert sp.has_cruise is False
        assert sp.cruise_fraction == 0.0

    def test_from_stats_reads_phase_fallbacks_from_nested_phase_maps(self) -> None:
        sp = SpeedProfile.from_stats(
            SpeedProfileSummary(
                min_kmh=20,
                max_kmh=60,
                sample_count=50,
            ),
            driving_phase_summary_from_mapping(
                {
                    "phase_counts": {"acceleration": 5, "cruise": 20},
                    "phase_pcts": {"cruise": 40.0, "idle": 15.0, "speed_unknown": 20.0},
                }
            ),
        )
        assert sp.has_cruise is True
        assert sp.has_acceleration is True
        assert sp.cruise_fraction == pytest.approx(0.40)
        assert sp.idle_fraction == pytest.approx(0.15)
        assert sp.speed_unknown_fraction == pytest.approx(0.20)


class TestSuitabilityCheck:
    def test_properties(self) -> None:
        assert SuitabilityCheck(check_key="a", state="pass").passed
        assert not SuitabilityCheck(check_key="a", state="pass").failed
        assert SuitabilityCheck(check_key="a", state="fail").failed
        assert not SuitabilityCheck(check_key="a", state="warn").passed

    @pytest.mark.parametrize(
        "check_key,state,details,expected_key",
        [
            ("SUITABILITY_CHECK_SPEED_VARIATION", "pass", (), "SUITABILITY_SPEED_VARIATION_PASS"),
            ("SUITABILITY_CHECK_SPEED_VARIATION", "warn", (), "SUITABILITY_SPEED_VARIATION_WARN"),
            ("SUITABILITY_CHECK_SENSOR_COVERAGE", "pass", (), "SUITABILITY_SENSOR_COVERAGE_PASS"),
            ("SUITABILITY_CHECK_SENSOR_COVERAGE", "warn", (), "SUITABILITY_SENSOR_COVERAGE_WARN"),
            (
                "SUITABILITY_CHECK_REFERENCE_COMPLETENESS",
                "pass",
                (),
                "SUITABILITY_REFERENCE_COMPLETENESS_PASS",
            ),
            (
                "SUITABILITY_CHECK_REFERENCE_COMPLETENESS",
                "warn",
                (),
                "SUITABILITY_REFERENCE_COMPLETENESS_WARN",
            ),
            (
                "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
                "pass",
                (),
                "SUITABILITY_SATURATION_PASS",
            ),
            (
                "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
                "warn",
                (("sat_count", 3),),
                "SUITABILITY_SATURATION_WARN",
            ),
            ("SUITABILITY_CHECK_FRAME_INTEGRITY", "pass", (), "SUITABILITY_FRAME_INTEGRITY_PASS"),
            (
                "SUITABILITY_CHECK_FRAME_INTEGRITY",
                "warn",
                (("total_dropped", 2), ("total_overflow", 1)),
                "SUITABILITY_FRAME_INTEGRITY_WARN",
            ),
            (
                "SUITABILITY_CHECK_ANALYSIS_SAMPLING",
                "warn",
                (("stride", 4),),
                "SUITABILITY_ANALYSIS_SAMPLING_STRIDE_WARNING",
            ),
        ],
    )
    def test_explanation_i18n_ref(
        self,
        check_key: str,
        state: str,
        details: tuple,
        expected_key: str,
    ) -> None:
        c = SuitabilityCheck(check_key=check_key, state=state, details=details)
        ref = c.explanation_i18n_ref()
        assert isinstance(ref, dict)
        assert ref["_i18n_key"] == expected_key

    @pytest.mark.parametrize(
        ("check_key", "details", "expected_params"),
        [
            pytest.param(
                "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
                (("sat_count", 5),),
                {"sat_count": 5},
                id="saturation-sat-count",
            ),
            pytest.param(
                "SUITABILITY_CHECK_FRAME_INTEGRITY",
                (("total_dropped", 10), ("total_overflow", 3)),
                {"total_dropped": 10, "total_overflow": 3},
                id="frame-integrity-counts",
            ),
            pytest.param(
                "SUITABILITY_CHECK_ANALYSIS_SAMPLING",
                (("stride", 4),),
                {"stride": "4"},
                id="sampling-stride-as-text",
            ),
        ],
    )
    def test_explanation_i18n_ref_includes_warning_params(
        self, check_key: str, details: tuple, expected_params: dict[str, object]
    ) -> None:
        ref = SuitabilityCheck(check_key=check_key, state="warn", details=details)
        ref = ref.explanation_i18n_ref()
        assert isinstance(ref, dict)
        assert {key: ref[key] for key in expected_params} == expected_params

    @pytest.mark.parametrize(
        "check_key",
        [
            pytest.param("SUITABILITY_CHECK_ANALYSIS_SAMPLING", id="stride-without-details"),
            pytest.param("UNKNOWN_CHECK", id="unknown-check-key"),
        ],
    )
    def test_explanation_i18n_ref_empty_without_explanation(self, check_key: str) -> None:
        assert SuitabilityCheck(check_key=check_key, state="warn").explanation_i18n_ref() == ""


class TestRunSuitability:
    def test_from_checks(self) -> None:
        checks = [
            {"check_key": "speed_variation", "state": "pass", "explanation": "OK"},
            {"check_key": "sample_count", "state": "warn", "explanation": "Marginal"},
            {"check_key": "noise_floor", "state": "fail", "explanation": "Too noisy"},
        ]
        rs = run_suitability_from_payload(checks)
        assert len(rs.checks) == 3
        assert rs.checks[0].check_key == "speed_variation"
        assert rs.checks[1].state == "warn"
        assert rs.checks[2].failed

    def test_evaluate_owns_thresholds_and_semantic_details(self) -> None:
        rs = RunSuitability.evaluate(
            steady_speed=True,
            speed_sufficient=True,
            manual_speed=False,
            sensor_count=2,
            reference_complete=False,
            sat_count=3,
            total_dropped=5,
            total_overflow=1,
        )
        states = {check.check_key: check.state for check in rs.checks}
        assert states == {
            "SUITABILITY_CHECK_SPEED_VARIATION": "warn",
            "SUITABILITY_CHECK_SENSOR_COVERAGE": "warn",
            "SUITABILITY_CHECK_REFERENCE_COMPLETENESS": "warn",
            "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS": "warn",
            "SUITABILITY_CHECK_FRAME_INTEGRITY": "warn",
        }
        details = {check.check_key: check.details_dict for check in rs.checks}
        assert details["SUITABILITY_CHECK_SPEED_VARIATION"] == {"steady_speed": 1}
        assert details["SUITABILITY_CHECK_SATURATION_AND_OUTLIERS"] == {"sat_count": 3}
        assert details["SUITABILITY_CHECK_FRAME_INTEGRITY"] == {
            "total_dropped": 5,
            "total_overflow": 1,
        }

    @pytest.mark.parametrize(
        ("total_dropped", "expected_key"),
        [
            (0, "SUITABILITY_FRAME_INTEGRITY_REPLAY_WARN"),
            (4, "SUITABILITY_FRAME_INTEGRITY_WARN"),
        ],
    )
    def test_incomplete_raw_replay_fails_frame_integrity(
        self, total_dropped: int, expected_key: str
    ) -> None:
        rs = RunSuitability.evaluate(
            steady_speed=False,
            speed_sufficient=True,
            manual_speed=False,
            sensor_count=3,
            reference_complete=True,
            sat_count=0,
            total_dropped=total_dropped,
            total_overflow=0,
        ).with_incomplete_raw_replay(partial=34, missing=0, gaps=2, overlaps=2)
        (frame,) = (c for c in rs.checks if c.check_key == "SUITABILITY_CHECK_FRAME_INTEGRITY")
        ref = frame.explanation_i18n_ref()

        assert frame.state == "warn"
        assert isinstance(ref, dict)
        assert ref["_i18n_key"] == expected_key
        assert ref["total_dropped"] == total_dropped
        assert [c.state for c in rs.checks if c is not frame] == ["pass"] * 4

    def test_from_checks_empty(self) -> None:
        rs = run_suitability_from_payload([])
        assert rs.checks == ()

    def test_from_checks_canonical_key(self) -> None:
        rs = run_suitability_from_payload([{"check_key": "speed_profile", "state": "pass"}])
        assert rs.checks[0].check_key == "speed_profile"
