"""Domain value-object tests for speed profiles and run suitability."""

from __future__ import annotations

import pytest

from vibesensor.domain import (
    DrivingPhaseSummary,
    RunSuitability,
    SpeedProfile,
    SuitabilityCheck,
)
from vibesensor.domain.speed_profile_summary import SpeedProfileSummary
from vibesensor.shared.boundaries.codecs import driving_phase_summary_from_mapping
from vibesensor.shared.boundaries.runs.suitability import run_suitability_from_payload


class TestSpeedProfile:
    def test_defaults(self) -> None:
        sp = SpeedProfile()
        assert sp.min_kmh == 0.0
        assert sp.max_kmh == 0.0
        assert not sp.steady_speed
        assert not sp.has_cruise
        assert not sp.has_acceleration
        assert sp.cruise_fraction == 0.0
        assert sp.idle_fraction == 0.0
        assert sp.speed_unknown_fraction == 0.0

    def test_speed_range_kmh(self) -> None:
        sp = SpeedProfile(min_kmh=40.0, max_kmh=80.0)
        assert sp.speed_range_kmh == 40.0

    def test_is_adequate_for_diagnosis(self) -> None:
        assert SpeedProfile(sample_count=100, max_kmh=60.0).is_adequate_for_diagnosis
        assert not SpeedProfile(sample_count=5, max_kmh=60.0).is_adequate_for_diagnosis
        assert not SpeedProfile(sample_count=100, max_kmh=3.0).is_adequate_for_diagnosis

    def test_has_steady_cruise(self) -> None:
        assert SpeedProfile(has_cruise=True, cruise_fraction=0.5).has_steady_cruise
        assert not SpeedProfile(has_cruise=True, cruise_fraction=0.1).has_steady_cruise
        assert not SpeedProfile(has_cruise=False, cruise_fraction=0.5).has_steady_cruise

    def test_known_speed_fraction(self) -> None:
        assert SpeedProfile(speed_unknown_fraction=0.25).known_speed_fraction == pytest.approx(0.75)

    def test_driving_fraction(self) -> None:
        assert SpeedProfile(idle_fraction=0.2).driving_fraction == pytest.approx(0.8)

    def test_has_speed_variation_uses_acceleration_or_nonsteady_range(self) -> None:
        assert SpeedProfile(has_acceleration=True, steady_speed=True).has_speed_variation
        assert SpeedProfile(min_kmh=40.0, max_kmh=80.0, steady_speed=False).has_speed_variation
        assert not SpeedProfile(min_kmh=40.0, max_kmh=80.0, steady_speed=True).has_speed_variation

    def test_supports_variable_speed_diagnosis_requires_adequate_data(self) -> None:
        assert SpeedProfile(
            sample_count=100,
            max_kmh=80.0,
            has_acceleration=True,
        ).supports_variable_speed_diagnosis
        assert not SpeedProfile(
            sample_count=5,
            max_kmh=80.0,
            has_acceleration=True,
        ).supports_variable_speed_diagnosis

    def test_supports_steady_state_diagnosis_uses_cruise_or_steady_motion(self) -> None:
        assert SpeedProfile(
            sample_count=100,
            max_kmh=80.0,
            has_cruise=True,
            cruise_fraction=0.4,
        ).supports_steady_state_diagnosis
        assert SpeedProfile(
            sample_count=100,
            max_kmh=80.0,
            steady_speed=True,
            idle_fraction=0.1,
        ).supports_steady_state_diagnosis
        assert not SpeedProfile(
            sample_count=5,
            max_kmh=80.0,
            steady_speed=True,
            idle_fraction=0.1,
        ).supports_steady_state_diagnosis

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
        assert sp.known_speed_fraction == pytest.approx(0.95)
        assert sp.driving_fraction == pytest.approx(0.90)
        assert sp.supports_variable_speed_diagnosis
        assert sp.supports_steady_state_diagnosis
        assert sp.sample_count == 500

    def test_from_stats_empty(self) -> None:
        sp = SpeedProfile.from_stats(SpeedProfileSummary())
        assert sp.min_kmh == 0.0
        assert sp.max_kmh == 0.0
        assert not sp.steady_speed
        assert not sp.has_acceleration
        assert sp.known_speed_fraction == 1.0
        assert sp.driving_fraction == 1.0

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
        assert SuitabilityCheck(check_key="a", state="warn").is_warning

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

    def test_explanation_i18n_ref_saturation_warn_includes_sat_count(self) -> None:
        c = SuitabilityCheck(
            check_key="SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
            state="warn",
            details=(("sat_count", 5),),
        )
        ref = c.explanation_i18n_ref()
        assert isinstance(ref, dict)
        assert ref["sat_count"] == 5

    def test_explanation_i18n_ref_frame_integrity_warn_includes_counts(self) -> None:
        c = SuitabilityCheck(
            check_key="SUITABILITY_CHECK_FRAME_INTEGRITY",
            state="warn",
            details=(("total_dropped", 10), ("total_overflow", 3)),
        )
        ref = c.explanation_i18n_ref()
        assert isinstance(ref, dict)
        assert ref["total_dropped"] == 10
        assert ref["total_overflow"] == 3

    def test_explanation_i18n_ref_stride_includes_stride(self) -> None:
        c = SuitabilityCheck(
            check_key="SUITABILITY_CHECK_ANALYSIS_SAMPLING",
            state="warn",
            details=(("stride", 4),),
        )
        ref = c.explanation_i18n_ref()
        assert isinstance(ref, dict)
        assert ref["stride"] == "4"

    def test_explanation_i18n_ref_stride_no_details_returns_empty(self) -> None:
        c = SuitabilityCheck(
            check_key="SUITABILITY_CHECK_ANALYSIS_SAMPLING",
            state="warn",
        )
        assert c.explanation_i18n_ref() == ""

    def test_explanation_i18n_ref_unknown_key_returns_empty(self) -> None:
        c = SuitabilityCheck(check_key="UNKNOWN_CHECK", state="warn")
        assert c.explanation_i18n_ref() == ""


class TestRunSuitability:
    def test_overall_pass(self) -> None:
        rs = RunSuitability(
            checks=(
                SuitabilityCheck(check_key="a", state="pass"),
                SuitabilityCheck(check_key="b", state="pass"),
            )
        )
        assert rs.overall == "pass"
        assert rs.is_usable
        assert not rs.has_warnings

    def test_overall_caution(self) -> None:
        rs = RunSuitability(
            checks=(
                SuitabilityCheck(check_key="a", state="pass"),
                SuitabilityCheck(check_key="b", state="warn"),
            )
        )
        assert rs.overall == "caution"
        assert rs.is_usable
        assert rs.has_warnings

    def test_overall_fail(self) -> None:
        rs = RunSuitability(
            checks=(
                SuitabilityCheck(check_key="a", state="pass"),
                SuitabilityCheck(check_key="b", state="fail"),
            )
        )
        assert rs.overall == "fail"
        assert not rs.is_usable
        assert len(rs.failed_checks) == 1
        assert rs.failed_checks[0].check_key == "b"

    def test_empty_checks(self) -> None:
        rs = RunSuitability()
        assert rs.overall == "pass"
        assert rs.is_usable

    def test_from_checks(self) -> None:
        checks = [
            {"check_key": "speed_variation", "state": "pass", "explanation": "OK"},
            {"check_key": "sample_count", "state": "warn", "explanation": "Marginal"},
            {"check_key": "noise_floor", "state": "fail", "explanation": "Too noisy"},
        ]
        rs = run_suitability_from_payload(checks)
        assert len(rs.checks) == 3
        assert rs.overall == "fail"
        assert rs.checks[0].check_key == "speed_variation"
        assert rs.checks[1].state == "warn"
        assert rs.checks[2].failed

    def test_evaluate_owns_thresholds_and_semantic_details(self) -> None:
        rs = RunSuitability.evaluate(
            steady_speed=True,
            speed_sufficient=True,
            sensor_count=2,
            reference_complete=False,
            sat_count=3,
            total_dropped=5,
            total_overflow=1,
        )
        states = {check.check_key: check.state for check in rs.checks}
        assert states == {
            "SUITABILITY_CHECK_SPEED_VARIATION": "pass",
            "SUITABILITY_CHECK_SENSOR_COVERAGE": "warn",
            "SUITABILITY_CHECK_REFERENCE_COMPLETENESS": "warn",
            "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS": "warn",
            "SUITABILITY_CHECK_FRAME_INTEGRITY": "warn",
        }
        details = {check.check_key: check.details_dict for check in rs.checks}
        assert details["SUITABILITY_CHECK_SATURATION_AND_OUTLIERS"] == {"sat_count": 3}
        assert details["SUITABILITY_CHECK_FRAME_INTEGRITY"] == {
            "total_dropped": 5,
            "total_overflow": 1,
        }

    def test_from_checks_empty(self) -> None:
        rs = run_suitability_from_payload([])
        assert rs.overall == "pass"

    def test_from_checks_canonical_key(self) -> None:
        rs = run_suitability_from_payload([{"check_key": "speed_profile", "state": "pass"}])
        assert rs.checks[0].check_key == "speed_profile"

    def test_has_reference_gaps_true_when_not_passing(self) -> None:
        rs = RunSuitability(
            checks=(
                SuitabilityCheck(
                    check_key="SUITABILITY_CHECK_REFERENCE_COMPLETENESS",
                    state="warn",
                ),
            )
        )
        assert rs.has_reference_gaps

    def test_has_reference_gaps_false_when_passing(self) -> None:
        rs = RunSuitability(
            checks=(
                SuitabilityCheck(
                    check_key="SUITABILITY_CHECK_REFERENCE_COMPLETENESS",
                    state="pass",
                ),
            )
        )
        assert not rs.has_reference_gaps

    def test_has_reference_gaps_false_when_absent(self) -> None:
        rs = RunSuitability(checks=(SuitabilityCheck(check_key="other", state="pass"),))
        assert not rs.has_reference_gaps
