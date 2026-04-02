from __future__ import annotations

from dataclasses import replace

from test_support.findings import make_finding

from vibesensor.domain import VibrationSource
from vibesensor.use_cases.diagnostics._analysis_result_builder import _final_top_causes


def test_final_top_causes_preserves_derived_reason_in_findings_order() -> None:
    wheel = make_finding(
        finding_id="F_WHEEL",
        suspected_source=VibrationSource.WHEEL_TIRE,
        confidence=0.66,
        strongest_location="front-left",
    ).with_confidence_assessment(
        strength_band_key="moderate",
        steady_speed=True,
        has_reference_gaps=False,
        sensor_count=4,
    )
    driveline = make_finding(
        finding_id="F_DRIVELINE",
        suspected_source=VibrationSource.DRIVELINE,
        confidence=0.61,
        strongest_location="front-left",
    ).with_confidence_assessment(
        strength_band_key="moderate",
        steady_speed=True,
        has_reference_gaps=False,
        sensor_count=4,
    )
    assert wheel.confidence_assessment is not None
    assert driveline.confidence_assessment is not None
    ranked_top_causes = (
        replace(
            wheel,
            confidence_assessment=replace(
                wheel.confidence_assessment,
                reason="Wheel and driveline evidence overlap; inspect both areas.",
            ),
        ),
        replace(
            driveline,
            confidence_assessment=replace(
                driveline.confidence_assessment,
                reason="Wheel and driveline evidence overlap; inspect both areas.",
            ),
        ),
    )

    result = _final_top_causes((driveline, wheel), ranked_top_causes)

    assert [finding.finding_id for finding in result] == ["F_DRIVELINE", "F_WHEEL"]
    assert result[0].confidence_assessment is not None
    assert result[1].confidence_assessment is not None
    assert "wheel and driveline evidence overlap" in result[0].confidence_assessment.reason.lower()
    assert "wheel and driveline evidence overlap" in result[1].confidence_assessment.reason.lower()
