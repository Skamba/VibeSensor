from __future__ import annotations

from vibesensor.domain import (
    DiagnosisAssessmentFactor,
    DiagnosisAssessmentFactorDetails,
    diagnosis_assessment_from_components,
)
from vibesensor.report_i18n import tr as report_tr
from vibesensor.shared.report_confidence_presentation import (
    confidence_caveat_text,
    confidence_reason_text,
)


def test_confidence_reason_text_mentions_user_confirmed_vehicle_data_scope() -> None:
    confidence = diagnosis_assessment_from_components(
        score_0_to_1=0.75,
        data_basis="raw_backed",
        raw_backed_sample_count=0,
        supporting_window_count=0,
        supporting_duration_s=None,
        stable_frequency_min_hz=None,
        stable_frequency_max_hz=None,
        supporting_location_count=0,
        top_support_location=None,
        top_support_share=None,
        mean_relative_error=None,
        snr_db=None,
        alternative_source=None,
        has_reference_gap=False,
        speed_gap_window_count=0,
        rpm_gap_window_count=0,
        car_data_reference_scope="tire",
        car_data_confidence="user_confirmed",
        uses_summary_fallback=False,
        fallback_reason=None,
        support_factors=(
            DiagnosisAssessmentFactor(
                factor_key="user_confirmed_vehicle_data",
                polarity="support",
                severity="low",
                weight=0.04,
                details=DiagnosisAssessmentFactorDetails(
                    car_data_reference_scope="tire",
                    car_data_confidence="user_confirmed",
                ),
            ),
        ),
        counterevidence_factors=(),
    )

    text = confidence_reason_text(confidence, tr=_tr)

    assert "user-confirmed vehicle data" in text
    assert "wheel-speed" in text


def test_confidence_caveat_text_mentions_approximate_vehicle_data_scope() -> None:
    confidence = diagnosis_assessment_from_components(
        score_0_to_1=0.45,
        data_basis="raw_backed",
        raw_backed_sample_count=0,
        supporting_window_count=0,
        supporting_duration_s=None,
        stable_frequency_min_hz=None,
        stable_frequency_max_hz=None,
        supporting_location_count=0,
        top_support_location=None,
        top_support_share=None,
        mean_relative_error=None,
        snr_db=None,
        alternative_source=None,
        has_reference_gap=False,
        speed_gap_window_count=0,
        rpm_gap_window_count=0,
        car_data_reference_scope="engine_speed_derived",
        car_data_confidence="family_default",
        uses_summary_fallback=False,
        fallback_reason=None,
        support_factors=(),
        counterevidence_factors=(
            DiagnosisAssessmentFactor(
                factor_key="approximate_vehicle_data",
                polarity="counterevidence",
                severity="medium",
                weight=0.06,
                details=DiagnosisAssessmentFactorDetails(
                    car_data_reference_scope="engine_speed_derived",
                    car_data_confidence="family_default",
                ),
            ),
        ),
    )

    text = confidence_caveat_text(confidence, tr=_tr)

    assert text is not None
    assert "approximate vehicle data" in text
    assert "speed-derived engine" in text


def _tr(key: str, **kwargs) -> str:
    return report_tr("en", key, **kwargs)
