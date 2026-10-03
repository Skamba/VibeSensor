"""Action-defined confidence levels, workshop order codes, and the verdict candidate."""

from __future__ import annotations

import pytest
from test_support.findings import make_finding

from vibesensor.domain.finding_types import ConfidenceLevel, VibrationSource
from vibesensor.domain.run_capture import RunCapture
from vibesensor.domain.test_run import TestRun


@pytest.mark.parametrize(
    ("score", "level"),
    [
        (0.95, ConfidenceLevel.STRONG),
        (0.70, ConfidenceLevel.STRONG),
        (0.69, ConfidenceLevel.MODERATE),
        (0.40, ConfidenceLevel.MODERATE),
        (0.39, ConfidenceLevel.WEAK),
        (0.0, ConfidenceLevel.WEAK),
    ],
)
def test_levels_follow_documented_thresholds(score: float, level: ConfidenceLevel) -> None:
    assert make_finding(confidence=score).confidence_level is level


def test_negligible_strength_caps_strong_to_moderate() -> None:
    finding = make_finding(confidence=0.9).with_confidence_assessment(
        strength_band_key="negligible",
        steady_speed=True,
        has_reference_gaps=False,
        sensor_count=4,
    )
    assert finding.confidence_level is ConfidenceLevel.MODERATE


@pytest.mark.parametrize(
    ("key", "code"),
    [
        ("wheel_1x", "T1"),
        ("wheel_2x", "T2"),
        ("driveshaft_1x", "P1"),
        ("driveshaft_2x", "P2"),
        ("engine_1x", "E1"),
        ("engine_2x", "E2"),
        ("peak_41hz", None),
    ],
)
def test_order_codes_use_workshop_labels(key: str, code: str | None) -> None:
    assert make_finding(finding_key=key).order_code == code


def test_candidate_skips_noise_transients_and_unsurfaced_findings() -> None:
    noise = make_finding(
        finding_id="F001", suspected_source=VibrationSource.BASELINE_NOISE, confidence=0.9
    )
    transient = make_finding(
        finding_id="F002", suspected_source=VibrationSource.TRANSIENT_IMPACT, confidence=0.9
    )
    faint = make_finding(finding_id="F003", confidence=0.1)
    real = make_finding(finding_id="F004", confidence=0.6)
    findings = (noise, transient, faint, real)
    run = TestRun(capture=RunCapture(run_id="r"), findings=findings, top_causes=findings)
    assert run.diagnosis_candidate is real

    quiet = TestRun(capture=RunCapture(run_id="r"), findings=(noise,), top_causes=(noise,))
    assert quiet.diagnosis_candidate is None
