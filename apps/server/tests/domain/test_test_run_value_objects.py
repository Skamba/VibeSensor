"""Domain value-object tests for composed test-run state and segments."""

from __future__ import annotations

import pytest

from vibesensor.analysis._run_input import build_diagnostics_run_input
from vibesensor.analysis.run_analysis import RunAnalysis
from vibesensor.analysis.summary_payload import analysis_result_to_summary
from vibesensor.domain.diagnostic_case import DiagnosticCase
from vibesensor.domain.driving_segment import DrivingPhase, DrivingPhaseInterval, DrivingSegment
from vibesensor.domain.finding import Finding
from vibesensor.domain.run_capture import RunCapture, RunSetup
from vibesensor.domain.sensor import Sensor
from vibesensor.domain.test_run import TestRun
from vibesensor.recording.run_metadata import run_metadata_from_mapping
from vibesensor.recording.sensor_frame_mapping import sensor_frames_from_mappings
from vibesensor.summary.reconstruction import (
    test_run_from_summary as reconstruct_test_run_from_summary,
)


def _make_test_run_finding(
    finding_id: str,
    *,
    suspected_source: str = "wheel/tire",
    confidence: float = 0.82,
    strongest_location: str | None = "front_left",
) -> Finding:
    return Finding(
        finding_id=finding_id,
        suspected_source=suspected_source,
        confidence=confidence,
        strongest_location=strongest_location,
    )


def _make_test_run(
    *,
    run_id: str = "run-1",
    findings: tuple[Finding, ...],
    top_causes: tuple[Finding, ...],
) -> TestRun:
    return TestRun(
        capture=RunCapture(run_id=run_id),
        findings=findings,
        top_causes=top_causes,
    )


class TestTestRunQueries:
    def test_finding_classification_queries(self) -> None:
        first = _make_test_run_finding("F001", strongest_location="Rear Right")
        diag = _make_test_run_finding("F003", strongest_location="Left Front")
        ref = _make_test_run_finding("REF_SPEED", suspected_source="unknown", confidence=1.0)
        info = Finding(
            finding_id="F002", confidence=0.10, severity="info", suspected_source="unknown"
        )

        result = _make_test_run(findings=(ref, first, diag, info), top_causes=(diag,))

        # The top cause is primary even when another diagnostic finding comes first.
        assert result.primary_finding == diag
        assert result.diagnostic_findings == (first, diag)
        assert result.non_reference_findings == (first, diag, info)
        assert result.sensor_count == 0

    def test_effective_top_causes_prefer_actionable_top_causes(self) -> None:
        actionable = _make_test_run_finding("F001")
        other = _make_test_run_finding("F002", suspected_source="engine", confidence=0.5)
        assert _make_test_run(
            findings=(actionable, other), top_causes=(actionable,)
        ).effective_top_causes() == (actionable,)

        reference_only = _make_test_run_finding("REF_SPEED", suspected_source="unknown")
        assert _make_test_run(
            findings=(reference_only,), top_causes=(reference_only,)
        ).effective_top_causes() == (reference_only,)

    def test_run_analysis_builds_test_run_and_diagnostic_case(self) -> None:
        metadata = {
            "run_id": "domain-case-guard",
            "active_car_snapshot": {"name": "Guard Car", "type": "sedan"},
            "language": "en",
        }
        samples = [
            {
                "t_s": float(i),
                "accel_x_g": 0.01,
                "accel_y_g": 0.01,
                "accel_z_g": 1.0,
                "speed_kmh": 80.0,
                "vibration_strength_db": 5.0,
            }
            for i in range(30)
        ]
        analysis = RunAnalysis(
            build_diagnostics_run_input(
                run_metadata_from_mapping(metadata),
                sensor_frames_from_mappings(samples),
            ),
        )
        result = analysis.summarize()
        summary = analysis_result_to_summary(result)

        assert isinstance(result.test_run, TestRun)
        assert result.test_run.run_id == summary["run_id"] == "domain-case-guard"
        assert len(result.test_run.findings) == len(summary["findings"])
        assert isinstance(result.diagnostic_case, DiagnosticCase)
        assert result.diagnostic_case.test_runs == (result.test_run,)
        assert result.diagnostic_case.car is not None
        assert result.diagnostic_case.car.name == "Guard Car"


class TestTestRunWithValueObjects:
    def test_from_summary_extracts_speed_profile(self) -> None:
        summary = {
            "run_id": "test-123",
            "findings": [],
            "top_causes": [],
            "speed_stats": {
                "min_kmh": 30.0,
                "max_kmh": 90.0,
                "mean_kmh": 60.0,
                "steady_speed": True,
                "sample_count": 500,
            },
            "phase_summary": {
                "phase_counts": {"cruise": 325},
                "phase_pcts": {"cruise": 65.0},
            },
        }
        result = reconstruct_test_run_from_summary(summary)
        assert result.speed_profile is not None
        assert result.speed_profile.min_kmh == 30.0
        assert result.speed_profile.steady_speed
        assert result.speed_profile.has_cruise
        assert result.speed_profile.cruise_fraction == pytest.approx(0.65)

    def test_from_summary_extracts_suitability(self) -> None:
        summary = {
            "run_id": "test-123",
            "findings": [],
            "top_causes": [],
            "run_suitability": [
                {"check_key": "speed", "state": "pass", "explanation": "OK"},
                {"check_key": "noise", "state": "warn", "explanation": "Marginal"},
            ],
        }
        result = reconstruct_test_run_from_summary(summary)
        assert result.suitability is not None
        assert [check.state for check in result.suitability.checks] == ["pass", "warn"]

    def test_from_summary_no_speed_stats(self) -> None:
        summary = {"run_id": "test-123", "findings": [], "top_causes": []}
        result = reconstruct_test_run_from_summary(summary)
        assert result.speed_profile is None
        assert result.suitability is None


class TestTestRunSensors:
    @pytest.mark.parametrize(
        ("location_codes", "expected_count"),
        [
            pytest.param([], 0, id="default-empty"),
            pytest.param(["front_left_wheel", "rear_axle"], 2, id="two-sensors"),
            pytest.param(
                ["front_left_wheel", "rear_axle", "dashboard"],
                3,
                id="sensor-count-property",
            ),
        ],
    )
    def test_test_run_sensor_cases(
        self,
        location_codes: list[str],
        expected_count: int,
    ) -> None:
        if location_codes:
            sensors = Sensor.from_location_codes(location_codes)
            test_run = TestRun(
                capture=RunCapture(run_id="r1", setup=RunSetup(sensors=sensors)),
            )
        else:
            test_run = TestRun(capture=RunCapture(run_id="r1"))

        assert len(test_run.capture.setup.sensors) == expected_count
        assert test_run.sensor_count == expected_count


class TestDrivingSegment:
    """Tests for DrivingSegment value semantics."""

    @pytest.mark.parametrize(
        ("segment", "expected"),
        [
            pytest.param(
                DrivingSegment(
                    phase=DrivingPhase.CRUISE,
                    start_idx=0,
                    end_idx=10,
                    start_t_s=1.0,
                    end_t_s=3.5,
                ),
                pytest.approx(2.5),
                id="with-timestamps",
            ),
            pytest.param(
                DrivingSegment(phase=DrivingPhase.CRUISE, start_idx=0, end_idx=10),
                None,
                id="without-timestamps",
            ),
        ],
    )
    def test_duration_s_cases(
        self,
        segment: DrivingSegment,
        expected: float | None,
    ) -> None:
        assert segment.duration_s == expected


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
        self, start_t_s: float | None, end_t_s: float | None, expected_duration: float | None
    ) -> None:
        interval = DrivingPhaseInterval(
            phase=DrivingPhase.CRUISE, start_t_s=start_t_s, end_t_s=end_t_s
        )
        assert interval.duration_s == expected_duration

    def test_temporal_ordering_invariant(self) -> None:
        with pytest.raises(ValueError, match="start_t_s"):
            DrivingPhaseInterval(phase=DrivingPhase.CRUISE, start_t_s=20.0, end_t_s=10.0)
