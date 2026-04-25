from __future__ import annotations

from typing import cast

import pytest

from vibesensor.domain import CarOrderReferenceStatus, DrivingPhase, VehicleFieldConfidence
from vibesensor.shared.types.whole_run_analysis import WholeRunContextInterval
from vibesensor.use_cases.diagnostics.orders.whole_run_contracts import (
    OrderTraceSummary,
    OrderTraceSupportInterval,
)
from vibesensor.use_cases.diagnostics.spatial_evidence_contracts import (
    SpatialEvidenceSummary,
    SpatialLocationSummary,
)
from vibesensor.use_cases.diagnostics.whole_run_diagnosis_contracts import (
    WholeRunDiagnosisSummary,
)
from vibesensor.use_cases.diagnostics.whole_run_diagnosis_ranking import (
    build_whole_run_diagnosis_summaries,
)


def test_build_whole_run_diagnosis_summaries_adds_user_confirmed_vehicle_data_signal() -> None:
    summaries = _build_ranked_summaries(
        car_order_reference_status=CarOrderReferenceStatus(
            selection_source_status="manual_entry",
            tire_dimensions_confidence="user_confirmed",
            final_drive_ratio_confidence="official_exact",
            current_gear_ratio_confidence="official_exact",
            transmission_confidence="official_exact",
        ),
        ref_sources=("speed+tire",),
        suspected_source="wheel/tire",
    )

    factor = next(
        factor
        for factor in summaries[0].support_factors
        if factor.factor_key == "user_confirmed_vehicle_data"
    )
    assert factor.details.car_data_reference_scope == "tire"
    assert factor.details.car_data_confidence == "user_confirmed"


@pytest.mark.parametrize(
    ("field_confidence", "ref_sources", "suspected_source", "expected_factor", "expected_scope"),
    [
        (
            "reputable_secondary_crosschecked",
            ("speed+tire+final_drive",),
            "driveshaft",
            "secondary_vehicle_data",
            "driveline",
        ),
        (
            "family_default",
            ("speed+engine",),
            "engine",
            "approximate_vehicle_data",
            "engine_speed_derived",
        ),
        (
            "unverified",
            ("speed+tire",),
            "wheel/tire",
            "unverified_vehicle_data",
            "tire",
        ),
    ],
)
def test_build_whole_run_diagnosis_summaries_projects_vehicle_data_caveats(
    field_confidence: str,
    ref_sources: tuple[str, ...],
    suspected_source: str,
    expected_factor: str,
    expected_scope: str,
) -> None:
    typed_confidence = cast(VehicleFieldConfidence, field_confidence)
    summaries = _build_ranked_summaries(
        car_order_reference_status=CarOrderReferenceStatus(
            selection_source_status="exact_row",
            tire_dimensions_confidence=(
                typed_confidence if "tire" in ref_sources[0] else "official_exact"
            ),
            final_drive_ratio_confidence=(
                typed_confidence
                if "final_drive" in ref_sources[0] or suspected_source == "driveshaft"
                else "official_exact"
            ),
            current_gear_ratio_confidence=(
                typed_confidence if ref_sources == ("speed+engine",) else "official_exact"
            ),
            transmission_confidence="official_exact",
        ),
        ref_sources=ref_sources,
        suspected_source=suspected_source,
    )

    factor = next(
        factor
        for factor in summaries[0].counterevidence_factors
        if factor.factor_key == expected_factor
    )
    assert factor.details.car_data_reference_scope == expected_scope
    assert factor.details.car_data_confidence == typed_confidence


def test_build_whole_run_diagnosis_summaries_does_not_penalize_direct_engine_reference() -> None:
    summaries = _build_ranked_summaries(
        car_order_reference_status=CarOrderReferenceStatus(
            selection_source_status="exact_row",
            tire_dimensions_confidence="unverified",
            final_drive_ratio_confidence="unverified",
            current_gear_ratio_confidence="unverified",
            transmission_confidence="official_exact",
        ),
        ref_sources=("obd2",),
        suspected_source="engine",
    )

    factor_keys = {factor.factor_key for factor in summaries[0].counterevidence_factors}
    assert "unverified_vehicle_data" not in factor_keys
    assert "approximate_vehicle_data" not in factor_keys
    assert "secondary_vehicle_data" not in factor_keys


def _build_ranked_summaries(
    *,
    car_order_reference_status: CarOrderReferenceStatus,
    ref_sources: tuple[str, ...],
    suspected_source: str,
) -> tuple[WholeRunDiagnosisSummary, ...]:
    order_family = (
        "wheel"
        if suspected_source == "wheel/tire"
        else "driveshaft"
        if suspected_source in {"driveshaft", "driveline"}
        else "engine"
    )
    return build_whole_run_diagnosis_summaries(
        analysis_metadata={
            "raw_backed_sample_count": 64,
            "raw_capture_mode": "raw_backed",
            "whole_run_context_available": True,
        },
        context_intervals=(
            WholeRunContextInterval(
                segment_index=0,
                phase=DrivingPhase.CRUISE,
                load_state="steady",
                start_window_index=0,
                end_window_index=5,
                start_t_s=0.0,
                end_t_s=3.0,
                speed_band="60-80 km/h",
                full_context_window_count=6,
            ),
        ),
        order_summaries=(
            OrderTraceSummary(
                hypothesis_key="candidate_1x",
                suspected_source=suspected_source,
                order_family=order_family,
                order_label="candidate",
                total_window_count=6,
                eligible_window_count=6,
                matched_window_count=5,
                support_ratio=0.84,
                reference_coverage_ratio=0.92,
                longest_contiguous_support_window_count=4,
                contiguous_support_ratio=0.67,
                support_intervals=(
                    OrderTraceSupportInterval(
                        interval_index=0,
                        start_window_index=1,
                        end_window_index=4,
                        matched_window_count=4,
                        support_ratio=1.0,
                        start_t_s=0.5,
                        end_t_s=2.0,
                        phase="cruise",
                        speed_band="60-80 km/h",
                        mean_relative_error=0.03,
                    ),
                ),
                stable_frequency_min_hz=13.1,
                stable_frequency_max_hz=13.4,
                exemplar_interval_index=0,
                dominant_phase="cruise",
                dominant_speed_band="60-80 km/h",
                strongest_location="front-left",
                mean_relative_error=0.03,
                drift_score=0.08,
                lock_score=0.86,
                peak_intensity_db=18.0,
                mean_vibration_strength_db=11.0,
                ref_sources=ref_sources,
            ),
        ),
        spatial_summaries=(
            SpatialEvidenceSummary(
                candidate_key="candidate_1x",
                suspected_source=suspected_source,
                proof_basis="supporting_windows_raw_backed",
                total_window_count=6,
                supporting_window_count=5,
                supporting_sensor_count=2,
                coherent_window_count=4,
                coherence_ratio=0.8,
                dominant_location="front-left",
                runner_up_location="front-right",
                location_separation_db=3.0,
                dominance_ratio=1.6,
                location_summaries=(
                    SpatialLocationSummary(
                        location="front-left",
                        sensor_ids=("front",),
                        supporting_window_count=4,
                        support_ratio=0.8,
                        coherent_window_count=3,
                        coherence_ratio=0.75,
                    ),
                    SpatialLocationSummary(
                        location="front-right",
                        sensor_ids=("right",),
                        supporting_window_count=1,
                        support_ratio=0.2,
                        coherent_window_count=1,
                        coherence_ratio=1.0,
                    ),
                ),
            ),
        ),
        car_order_reference_status=car_order_reference_status,
    )
