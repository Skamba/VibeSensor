from __future__ import annotations

import pytest

from vibesensor.shared.types.history_analysis_contracts import (
    SpatialEvidenceSummaryResponse,
    SpatialLocationSummaryResponse,
)
from vibesensor.use_cases.diagnostics.spatial_evidence_contracts import (
    SpatialEvidenceSummary,
    SpatialEvidenceWindow,
    SpatialLocationSummary,
)


def test_spatial_evidence_window_round_trips_json_shape() -> None:
    window = SpatialEvidenceWindow(
        candidate_key="wheel",
        suspected_source="wheel/tire",
        window_index=12,
        sensor_id="front-left",
        location="Front Left",
        supporting=True,
        coherent=True,
        peak_intensity_db=18.4,
        vibration_strength_db=11.2,
        matched_frequency_hz=14.6,
        coherence_score=0.82,
    )

    assert SpatialEvidenceWindow.from_mapping(window.to_json_object()) == window


def test_spatial_evidence_summary_round_trips_nested_compact_contracts() -> None:
    summary = SpatialEvidenceSummary(
        candidate_key="wheel",
        suspected_source="wheel/tire",
        proof_basis="supporting_windows_raw_backed",
        total_window_count=128,
        supporting_window_count=42,
        supporting_sensor_count=4,
        coherent_window_count=30,
        coherence_ratio=30 / 42,
        dominant_location="Front Left",
        runner_up_location="Front Right",
        location_separation_db=4.5,
        dominance_ratio=1.42,
        ambiguous_location=False,
        weak_spatial_separation=False,
        location_summaries=(
            SpatialLocationSummary(
                location="Front Left",
                sensor_ids=("front-left",),
                supporting_window_count=24,
                support_ratio=24 / 42,
                coherent_window_count=18,
                coherence_ratio=18 / 24,
                peak_intensity_db=19.3,
                mean_vibration_strength_db=12.1,
            ),
            SpatialLocationSummary(
                location="Front Right",
                sensor_ids=("front-right",),
                supporting_window_count=12,
                support_ratio=12 / 42,
                coherent_window_count=8,
                coherence_ratio=8 / 12,
                peak_intensity_db=14.8,
                mean_vibration_strength_db=9.4,
            ),
        ),
    )

    assert SpatialEvidenceSummary.from_mapping(summary.to_json_object()) == summary


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("dominant_location", 7, "optional text field must be a string or null"),
        ("coherence_ratio", "bad", "optional numeric field must be a number or null"),
    ],
)
def test_spatial_evidence_summary_rejects_invalid_optional_values(
    field: str,
    value: object,
    message: str,
) -> None:
    payload = SpatialEvidenceSummary(
        candidate_key="wheel",
        suspected_source="wheel/tire",
        proof_basis="supporting_windows_raw_backed",
        total_window_count=128,
        supporting_window_count=42,
        supporting_sensor_count=4,
    ).to_json_object()
    payload[field] = value

    with pytest.raises(ValueError, match=message):
        SpatialEvidenceSummary.from_mapping(payload)


def test_spatial_evidence_summary_skips_non_mapping_location_rows() -> None:
    payload = SpatialEvidenceSummary(
        candidate_key="wheel",
        suspected_source="wheel/tire",
        proof_basis="supporting_windows_raw_backed",
        total_window_count=12,
        supporting_window_count=4,
        supporting_sensor_count=2,
    ).to_json_object()
    payload["location_summaries"] = [
        {
            "location": "Front Left",
            "sensor_ids": ["front-left"],
            "supporting_window_count": 3,
            "support_ratio": 0.75,
            "coherent_window_count": 2,
        },
        "skip-me",
    ]

    restored = SpatialEvidenceSummary.from_mapping(payload)

    assert [summary.location for summary in restored.location_summaries] == ["Front Left"]


def test_history_spatial_response_contracts_expose_named_summary_fields() -> None:
    assert set(SpatialLocationSummaryResponse.__annotations__) == {
        "location",
        "sensor_ids",
        "supporting_window_count",
        "support_ratio",
        "coherent_window_count",
        "coherence_ratio",
        "peak_intensity_db",
        "mean_vibration_strength_db",
    }
    assert set(SpatialEvidenceSummaryResponse.__annotations__) == {
        "candidate_key",
        "suspected_source",
        "proof_basis",
        "total_window_count",
        "supporting_window_count",
        "supporting_sensor_count",
        "coherent_window_count",
        "coherence_ratio",
        "dominant_location",
        "runner_up_location",
        "location_separation_db",
        "dominance_ratio",
        "ambiguous_location",
        "weak_spatial_separation",
        "location_summaries",
    }
