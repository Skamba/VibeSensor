from __future__ import annotations

import pytest

from vibesensor.shared.types.history_analysis_contracts import (
    DiagnosisExemplarReferenceResponse,
    DiagnosisFactorDetailsResponse,
    DiagnosisFactorResponse,
    WholeRunDiagnosisSummaryResponse,
)
from vibesensor.use_cases.diagnostics.whole_run_diagnosis_contracts import (
    DiagnosisExemplarReference,
    DiagnosisFactor,
    DiagnosisFactorDetails,
    WholeRunDiagnosisSummary,
)


def test_diagnosis_exemplar_reference_round_trips_json_shape() -> None:
    exemplar = DiagnosisExemplarReference(
        kind="order_support_interval",
        order_hypothesis_key="wheel_1x",
        support_interval_index=1,
        phase="cruise",
        speed_band="60-80 km/h",
    )

    assert DiagnosisExemplarReference.from_mapping(exemplar.to_json_object()) == exemplar


def test_whole_run_diagnosis_summary_round_trips_nested_compact_contracts() -> None:
    summary = WholeRunDiagnosisSummary(
        diagnosis_key="wheel_1x",
        suspected_source="wheel/tire",
        rank=1,
        data_basis="raw_backed",
        support_score=0.78,
        counterevidence_score=0.16,
        total_score=0.62,
        order_hypothesis_key="wheel_1x",
        spatial_candidate_key="wheel_1x",
        location_proof_basis="supporting_windows_raw_backed",
        supporting_window_count=8,
        supporting_duration_s=4.0,
        supporting_sensor_count=2,
        stable_frequency_min_hz=13.1,
        stable_frequency_max_hz=13.6,
        dominant_location="front-left",
        runner_up_location="front-right",
        dominant_phase="cruise",
        dominant_speed_band="60-80 km/h",
        location_separation_db=3.2,
        dominance_ratio=1.4,
        alternative_source="driveshaft",
        confidence_gap_to_alternative=0.18,
        ambiguous_diagnosis=False,
        ambiguous_location=False,
        suspicious=False,
        weak_spatial_separation=False,
        has_reference_gap=True,
        uses_summary_fallback=False,
        exemplar_references=(
            DiagnosisExemplarReference(
                kind="order_support_interval",
                order_hypothesis_key="wheel_1x",
                support_interval_index=0,
                phase="cruise",
                speed_band="60-80 km/h",
            ),
            DiagnosisExemplarReference(
                kind="spatial_location",
                spatial_candidate_key="wheel_1x",
                location="front-left",
            ),
            DiagnosisExemplarReference(
                kind="whole_run_context_interval",
                context_segment_index=2,
                phase="cruise",
                speed_band="60-80 km/h",
            ),
        ),
        support_factors=(
            DiagnosisFactor(
                factor_key="raw_backed",
                polarity="support",
                severity="high",
                weight=0.10,
                details=DiagnosisFactorDetails(raw_backed_sample_count=48),
            ),
        ),
        counterevidence_factors=(
            DiagnosisFactor(
                factor_key="incomplete_reference",
                polarity="counterevidence",
                severity="low",
                weight=0.06,
                details=DiagnosisFactorDetails(),
            ),
        ),
    )

    assert WholeRunDiagnosisSummary.from_mapping(summary.to_json_object()) == summary


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("support_score", "bad", "optional numeric field must be a number or null"),
        ("supporting_window_count", 1.5, "optional int field must be an int or null"),
        ("dominant_location", 7, "optional text field must be a string or null"),
    ],
)
def test_whole_run_diagnosis_summary_rejects_invalid_optional_values(
    field: str,
    value: object,
    message: str,
) -> None:
    payload = WholeRunDiagnosisSummary(
        diagnosis_key="wheel_1x",
        suspected_source="wheel/tire",
        rank=1,
        data_basis="raw_backed",
    ).to_json_object()
    payload[field] = value

    with pytest.raises(ValueError, match=message):
        WholeRunDiagnosisSummary.from_mapping(payload)


def test_whole_run_diagnosis_summary_skips_non_mapping_nested_rows() -> None:
    payload = WholeRunDiagnosisSummary(
        diagnosis_key="wheel_1x",
        suspected_source="wheel/tire",
        rank=1,
        data_basis="raw_backed",
    ).to_json_object()
    payload["exemplar_references"] = [
        {"kind": "whole_run_context_interval", "context_segment_index": 2},
        "skip-me",
    ]
    payload["support_factors"] = [
        {
            "factor_key": "raw_backed",
            "polarity": "support",
            "severity": "high",
            "weight": 0.1,
        },
        3,
    ]
    payload["counterevidence_factors"] = [
        {
            "factor_key": "incomplete_reference",
            "polarity": "counterevidence",
            "severity": "low",
            "weight": 0.05,
        },
        None,
    ]

    restored = WholeRunDiagnosisSummary.from_mapping(payload)

    assert [reference.kind for reference in restored.exemplar_references] == [
        "whole_run_context_interval"
    ]
    assert [factor.factor_key for factor in restored.support_factors] == ["raw_backed"]
    assert [factor.factor_key for factor in restored.counterevidence_factors] == [
        "incomplete_reference"
    ]


def test_diagnosis_exemplar_reference_rejects_unsupported_kind() -> None:
    with pytest.raises(ValueError, match="supported diagnosis exemplar kind"):
        DiagnosisExemplarReference.from_mapping({"kind": "bad-kind"})


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("factor_key", "bad-factor", "supported diagnosis factor key"),
        ("polarity", "neutral", "supported diagnosis factor polarity"),
        ("severity", "urgent", "supported diagnosis factor severity"),
    ],
)
def test_diagnosis_factor_rejects_unsupported_literal_values(
    field: str,
    value: object,
    message: str,
) -> None:
    payload = DiagnosisFactor(
        factor_key="raw_backed",
        polarity="support",
        severity="high",
        weight=0.10,
    ).to_json_object()
    payload[field] = value

    with pytest.raises(ValueError, match=message):
        DiagnosisFactor.from_mapping(payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("data_basis", "derived_only", "supported whole-run diagnosis data basis"),
        ("location_proof_basis", "sensor_vote", "supported location proof basis"),
    ],
)
def test_whole_run_diagnosis_summary_rejects_unsupported_literal_values(
    field: str,
    value: object,
    message: str,
) -> None:
    payload = WholeRunDiagnosisSummary(
        diagnosis_key="wheel_1x",
        suspected_source="wheel/tire",
        rank=1,
        data_basis="raw_backed",
    ).to_json_object()
    payload[field] = value

    with pytest.raises(ValueError, match=message):
        WholeRunDiagnosisSummary.from_mapping(payload)


def test_history_diagnosis_response_contracts_expose_named_summary_fields() -> None:
    assert set(DiagnosisExemplarReferenceResponse.__annotations__) == {
        "kind",
        "order_hypothesis_key",
        "support_interval_index",
        "spatial_candidate_key",
        "context_segment_index",
        "location",
        "phase",
        "speed_band",
    }
    assert set(DiagnosisFactorDetailsResponse.__annotations__) == {
        "raw_backed_sample_count",
        "supporting_window_count",
        "supporting_duration_s",
        "stable_frequency_min_hz",
        "stable_frequency_max_hz",
        "frequency_span_hz",
        "supporting_location_count",
        "top_support_location",
        "top_support_share",
        "mean_relative_error",
        "snr_db",
        "alternative_source",
        "speed_gap_window_count",
        "rpm_gap_window_count",
        "fallback_reason",
        "car_data_reference_scope",
        "car_data_confidence",
    }
    assert set(DiagnosisFactorResponse.__annotations__) == {
        "factor_key",
        "polarity",
        "severity",
        "weight",
        "details",
    }
    assert set(WholeRunDiagnosisSummaryResponse.__annotations__) == {
        "diagnosis_key",
        "suspected_source",
        "rank",
        "data_basis",
        "support_score",
        "counterevidence_score",
        "total_score",
        "order_hypothesis_key",
        "spatial_candidate_key",
        "location_proof_basis",
        "supporting_window_count",
        "supporting_duration_s",
        "supporting_sensor_count",
        "stable_frequency_min_hz",
        "stable_frequency_max_hz",
        "dominant_location",
        "runner_up_location",
        "dominant_phase",
        "dominant_speed_band",
        "location_separation_db",
        "dominance_ratio",
        "alternative_source",
        "confidence_gap_to_alternative",
        "ambiguous_diagnosis",
        "ambiguous_location",
        "suspicious",
        "weak_spatial_separation",
        "has_reference_gap",
        "uses_summary_fallback",
        "fallback_reason",
        "exemplar_references",
        "support_factors",
        "counterevidence_factors",
    }
