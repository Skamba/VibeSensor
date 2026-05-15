"""Guardrails for TestRun as the canonical post-analysis domain aggregate."""

from __future__ import annotations

import pytest

from vibesensor.domain import Finding, RunCapture, TestRun, VibrationSource
from vibesensor.shared.boundaries.analysis_payloads.reconstruction import (
    test_run_from_summary as reconstruct_test_run_from_summary,
)


def _finding(
    finding_id: str,
    *,
    confidence: float = 0.75,
    source: str = "wheel/tire",
    strength_db: float | None = None,
    severity: str = "diagnostic",
    location: str = "",
) -> Finding:
    return Finding(
        finding_id=finding_id,
        confidence=confidence,
        severity=severity,
        suspected_source=source,
        vibration_strength_db=strength_db,
        strongest_location=location,
    )


def test_test_run_provides_finding_queries() -> None:
    """``TestRun`` must own finding classification queries."""
    diag = _finding("F001")
    ref = _finding("REF_SPEED", confidence=1.0, source="unknown")
    info = _finding("F002", confidence=0.10, severity="info", source="unknown")

    result = TestRun(
        capture=RunCapture(run_id="test-123"),
        findings=(ref, diag, info),
        top_causes=(diag,),
    )

    assert result.primary_finding == diag
    assert result.diagnostic_findings == (diag,)
    assert result.non_reference_findings == (diag, info)
    assert result.sensor_count == 0
    assert result.total_usable_samples == 0


def test_test_run_effective_top_causes() -> None:
    """``effective_top_causes()`` mirrors diagnosis_candidates logic."""
    actionable = _finding("F001")
    result = TestRun(
        capture=RunCapture(run_id="test"),
        findings=(actionable,),
        top_causes=(actionable,),
    )
    effective = result.effective_top_causes()
    assert effective == (actionable,)

    reference_only = _finding("REF_SPEED", source="unknown")
    fallback = TestRun(
        capture=RunCapture(run_id="test"),
        findings=(reference_only,),
        top_causes=(reference_only,),
    )
    assert fallback.effective_top_causes() == (reference_only,)


def test_run_analysis_produces_test_run() -> None:
    """``RunAnalysis.summarize()`` must populate ``test_run``."""
    from vibesensor.adapters.analysis_summary import analysis_result_to_summary
    from vibesensor.domain import TestRun
    from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
    from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
    from vibesensor.use_cases.diagnostics._run_input import build_diagnostics_run_input
    from vibesensor.use_cases.diagnostics.run_analysis import RunAnalysis

    metadata = {"run_id": "test-guard", "active_car_snapshot": {"type": "sedan"}}
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
    assert analysis.test_run is not None
    assert isinstance(analysis.test_run, TestRun)
    assert analysis.test_run.run_id == summary["run_id"]
    assert len(analysis.test_run.findings) == len(summary["findings"])


def test_test_run_reference_gap_detection() -> None:
    """``has_relevant_reference_gap()`` detects source-relevant gaps."""
    ref_speed = _finding("REF_SPEED", source="unknown")
    ref_wheel = _finding("REF_WHEEL", source="unknown")
    ref_engine = _finding("REF_ENGINE", source="unknown")
    diag = _finding("F001", confidence=0.80)

    assert ref_speed.is_reference
    assert ref_wheel.is_reference
    assert ref_engine.is_reference
    assert not diag.is_reference

    def _make(findings: tuple[Finding, ...]) -> TestRun:
        return TestRun(
            capture=RunCapture(run_id="test"),
            findings=findings + (diag,),
            top_causes=(diag,),
        )

    result = _make((ref_speed,))
    assert result.has_relevant_reference_gap(VibrationSource.WHEEL_TIRE)
    assert result.has_relevant_reference_gap(VibrationSource.ENGINE)

    result2 = _make((ref_wheel,))
    assert result2.has_relevant_reference_gap(VibrationSource.WHEEL_TIRE)
    assert result2.has_relevant_reference_gap(VibrationSource.DRIVELINE)
    assert not result2.has_relevant_reference_gap(VibrationSource.ENGINE)

    result3 = _make((ref_engine,))
    assert result3.has_relevant_reference_gap(VibrationSource.ENGINE)
    assert not result3.has_relevant_reference_gap(VibrationSource.WHEEL_TIRE)


def test_test_run_top_strength_db() -> None:
    """``top_strength_db()`` finds the best strength from findings."""
    f1 = _finding("F001", confidence=0.80, strength_db=12.5)
    f2 = _finding("F002", confidence=0.60, source="engine", strength_db=8.0)
    result = TestRun(
        capture=RunCapture(run_id="test"),
        findings=(f1, f2),
        top_causes=(f1,),
    )
    assert result.top_strength_db() == 12.5

    # No strength → None
    f3 = _finding("F003", confidence=0.50, source="engine")
    result2 = TestRun(
        capture=RunCapture(run_id="test"),
        findings=(f3,),
        top_causes=(f3,),
    )
    assert result2.top_strength_db() is None


def test_test_run_primary_source_and_location() -> None:
    """``primary_source`` and ``primary_location`` are domain queries."""
    f = _finding("F001", confidence=0.80, location="Left Front")
    result = TestRun(
        capture=RunCapture(run_id="test"),
        findings=(f,),
        top_causes=(f,),
    )
    assert result.primary_source == VibrationSource.WHEEL_TIRE
    assert result.primary_location == "Left Front"

    # No findings → None
    empty = TestRun(
        capture=RunCapture(run_id="test"),
        findings=(),
        top_causes=(),
    )
    assert empty.primary_source is None
    assert empty.primary_location is None


def test_test_run_from_summary_populates_speed_profile() -> None:
    """test_run_from_summary extracts SpeedProfile when speed_stats is present."""
    summary = {
        "run_id": "test-123",
        "findings": [],
        "top_causes": [],
        "speed_stats": {
            "min_kmh": 30.0,
            "max_kmh": 90.0,
            "steady_speed": True,
        },
    }
    result = reconstruct_test_run_from_summary(summary)
    assert result.speed_profile is not None, "test_run_from_summary must populate speed_profile"
    assert result.speed_profile.steady_speed
    assert result.speed_profile.min_kmh == 30.0
    assert result.speed_profile.max_kmh == 90.0


def test_test_run_from_summary_populates_suitability() -> None:
    """test_run_from_summary extracts RunSuitability when run_suitability is present."""
    summary = {
        "run_id": "test-123",
        "findings": [],
        "top_causes": [],
        "run_suitability": [
            {"check_key": "speed", "state": "pass", "explanation": "OK"},
        ],
    }
    result = reconstruct_test_run_from_summary(summary)
    assert result.suitability is not None, "test_run_from_summary must populate suitability"
    assert result.suitability.is_usable
    assert result.suitability.checks[0].check_key == "speed"


def test_run_analysis_builds_test_run_and_diagnostic_case() -> None:
    from vibesensor.domain import DiagnosticCase, TestRun
    from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
    from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
    from vibesensor.use_cases.diagnostics._run_input import build_diagnostics_run_input
    from vibesensor.use_cases.diagnostics.run_analysis import RunAnalysis

    metadata = {
        "run_id": "domain-case-guard",
        "active_car_snapshot": {
            "name": "Guard Car",
            "type": "sedan",
        },
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

    assert analysis.test_run is not None
    assert result.diagnostic_case is not None
    assert isinstance(analysis.test_run, TestRun)
    assert isinstance(result.diagnostic_case, DiagnosticCase)
    assert result.diagnostic_case.primary_run is not None
    assert result.diagnostic_case.primary_run.run_id == analysis.test_run.run_id
    assert result.diagnostic_case.car is not None
    assert result.diagnostic_case.car.name == "Guard Car"


@pytest.mark.parametrize(
    ("top_causes", "message"),
    [
        pytest.param((), None, id="empty-top-causes"),
        pytest.param((_finding("F999"),), "unmatched top causes", id="unmatched-top-cause"),
    ],
)
def test_test_run_rejects_unmatched_top_causes(
    top_causes: tuple[Finding, ...],
    message: str | None,
) -> None:
    findings = (_finding("F001"),)
    if message is None:
        TestRun(capture=RunCapture(run_id="test"), findings=findings, top_causes=top_causes)
        return

    with pytest.raises(ValueError, match=message):
        TestRun(capture=RunCapture(run_id="test"), findings=findings, top_causes=top_causes)
