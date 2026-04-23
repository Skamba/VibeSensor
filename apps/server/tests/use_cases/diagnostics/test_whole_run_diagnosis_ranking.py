from __future__ import annotations

from vibesensor.domain import DrivingPhase
from vibesensor.shared.types.whole_run_analysis import WholeRunContextInterval
from vibesensor.use_cases.diagnostics.orders.whole_run_contracts import (
    OrderTraceSummary,
    OrderTraceSupportInterval,
)
from vibesensor.use_cases.diagnostics.spatial_evidence_contracts import (
    SpatialEvidenceSummary,
    SpatialLocationSummary,
)
from vibesensor.use_cases.diagnostics.whole_run_diagnosis_ranking import (
    build_whole_run_diagnosis_summaries,
)


def test_build_whole_run_diagnosis_summaries_ranks_candidates_and_projects_exemplars() -> None:
    summaries = build_whole_run_diagnosis_summaries(
        analysis_metadata={
            "raw_backed_sample_count": 96,
            "raw_capture_mode": "raw_backed",
            "whole_run_context_available": True,
        },
        context_intervals=(
            WholeRunContextInterval(
                segment_index=0,
                phase=DrivingPhase.CRUISE,
                load_state="steady",
                start_window_index=0,
                end_window_index=7,
                start_t_s=0.0,
                end_t_s=4.0,
                speed_min_kmh=58.0,
                speed_max_kmh=72.0,
                speed_band="60-80 km/h",
                full_context_window_count=8,
            ),
        ),
        order_summaries=(
            OrderTraceSummary(
                hypothesis_key="wheel_1x",
                suspected_source="wheel/tire",
                order_family="wheel",
                order_label="1x wheel",
                total_window_count=8,
                eligible_window_count=8,
                matched_window_count=6,
                support_ratio=0.75,
                reference_coverage_ratio=0.9,
                longest_contiguous_support_window_count=4,
                contiguous_support_ratio=0.5,
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
                drift_score=0.1,
                lock_score=0.8,
                peak_intensity_db=18.0,
                mean_vibration_strength_db=10.0,
                ref_sources=("speed+tire",),
            ),
            OrderTraceSummary(
                hypothesis_key="driveshaft_1x",
                suspected_source="driveshaft",
                order_family="driveshaft",
                order_label="1x driveshaft",
                total_window_count=8,
                eligible_window_count=8,
                matched_window_count=5,
                support_ratio=0.7,
                reference_coverage_ratio=0.85,
                longest_contiguous_support_window_count=3,
                contiguous_support_ratio=0.4,
                support_intervals=(
                    OrderTraceSupportInterval(
                        interval_index=0,
                        start_window_index=2,
                        end_window_index=4,
                        matched_window_count=3,
                        support_ratio=1.0,
                        start_t_s=1.0,
                        end_t_s=2.0,
                        phase="cruise",
                        speed_band="60-80 km/h",
                        mean_relative_error=0.04,
                    ),
                ),
                stable_frequency_min_hz=12.8,
                stable_frequency_max_hz=13.4,
                exemplar_interval_index=0,
                dominant_phase="cruise",
                dominant_speed_band="60-80 km/h",
                strongest_location="rear-left",
                mean_relative_error=0.04,
                drift_score=0.12,
                lock_score=0.78,
                peak_intensity_db=16.0,
                mean_vibration_strength_db=9.2,
                ref_sources=("speed+driveshaft",),
            ),
        ),
        spatial_summaries=(
            SpatialEvidenceSummary(
                candidate_key="wheel_1x",
                suspected_source="wheel/tire",
                proof_basis="supporting_windows_raw_backed",
                total_window_count=8,
                supporting_window_count=6,
                supporting_sensor_count=2,
                coherent_window_count=5,
                coherence_ratio=0.83,
                dominant_location="front-left",
                runner_up_location="front-right",
                location_separation_db=3.0,
                dominance_ratio=1.4,
                location_summaries=(
                    SpatialLocationSummary(
                        location="front-left",
                        sensor_ids=("front",),
                        supporting_window_count=5,
                        support_ratio=0.83,
                        coherent_window_count=4,
                        coherence_ratio=0.8,
                    ),
                    SpatialLocationSummary(
                        location="front-right",
                        sensor_ids=("right",),
                        supporting_window_count=1,
                        support_ratio=0.17,
                        coherent_window_count=1,
                        coherence_ratio=1.0,
                    ),
                ),
            ),
            SpatialEvidenceSummary(
                candidate_key="driveshaft_1x",
                suspected_source="driveshaft",
                proof_basis="supporting_windows_raw_backed",
                total_window_count=8,
                supporting_window_count=5,
                supporting_sensor_count=2,
                coherent_window_count=4,
                coherence_ratio=0.8,
                dominant_location="rear-left",
                runner_up_location="rear-right",
                location_separation_db=2.6,
                dominance_ratio=1.25,
                location_summaries=(
                    SpatialLocationSummary(
                        location="rear-left",
                        sensor_ids=("rear",),
                        supporting_window_count=4,
                        support_ratio=0.8,
                        coherent_window_count=3,
                        coherence_ratio=0.75,
                    ),
                    SpatialLocationSummary(
                        location="rear-right",
                        sensor_ids=("rear-right",),
                        supporting_window_count=1,
                        support_ratio=0.2,
                        coherent_window_count=1,
                        coherence_ratio=1.0,
                    ),
                ),
            ),
        ),
    )

    assert [summary.diagnosis_key for summary in summaries] == ["wheel_1x", "driveshaft_1x"]
    top_summary = summaries[0]
    assert top_summary.rank == 1
    assert top_summary.order_hypothesis_key == "wheel_1x"
    assert top_summary.spatial_candidate_key == "wheel_1x"
    assert top_summary.location_proof_basis == "supporting_windows_raw_backed"
    assert top_summary.alternative_source == "driveshaft"
    assert top_summary.confidence_gap_to_alternative is not None
    assert "close_alternative" in {
        factor.factor_key for factor in top_summary.counterevidence_factors
    }
    assert [reference.kind for reference in top_summary.exemplar_references] == [
        "order_support_interval",
        "spatial_location",
        "whole_run_context_interval",
    ]
    assert "raw_backed" in {factor.factor_key for factor in top_summary.support_factors}
    assert "incomplete_reference" in {
        factor.factor_key for factor in top_summary.counterevidence_factors
    }


def test_diagnosis_ranking_marks_context_gaps_and_weak_spatial_as_suspicious() -> None:
    summaries = build_whole_run_diagnosis_summaries(
        analysis_metadata={
            "raw_backed_sample_count": 48,
            "raw_capture_mode": "raw_backed",
            "whole_run_context_available": True,
            "whole_run_context_missing_speed_window_count": 1,
            "whole_run_context_stale_speed_window_count": 1,
            "whole_run_context_missing_rpm_window_count": 0,
            "whole_run_context_stale_rpm_window_count": 1,
        },
        context_intervals=(
            WholeRunContextInterval(
                segment_index=0,
                phase=DrivingPhase.ACCELERATION,
                load_state="pulling",
                start_window_index=0,
                end_window_index=3,
                start_t_s=0.0,
                end_t_s=2.0,
                speed_band="40-70 km/h",
                full_context_window_count=2,
                partial_context_window_count=1,
                missing_context_window_count=1,
            ),
        ),
        order_summaries=(
            OrderTraceSummary(
                hypothesis_key="engine_2x",
                suspected_source="engine",
                order_family="engine",
                order_label="2x engine",
                total_window_count=4,
                eligible_window_count=4,
                matched_window_count=2,
                support_ratio=0.5,
                reference_coverage_ratio=0.7,
                longest_contiguous_support_window_count=1,
                contiguous_support_ratio=0.25,
                support_intervals=(
                    OrderTraceSupportInterval(
                        interval_index=0,
                        start_window_index=1,
                        end_window_index=2,
                        matched_window_count=2,
                        support_ratio=1.0,
                        start_t_s=0.5,
                        end_t_s=1.0,
                        phase="accel",
                        speed_band="40-70 km/h",
                        mean_relative_error=0.16,
                    ),
                ),
                stable_frequency_min_hz=22.0,
                stable_frequency_max_hz=24.2,
                exemplar_interval_index=0,
                dominant_phase="accel",
                dominant_speed_band="40-70 km/h",
                strongest_location="front-right",
                mean_relative_error=0.16,
                drift_score=0.4,
                lock_score=0.35,
                peak_intensity_db=12.0,
                mean_vibration_strength_db=10.2,
                ref_sources=("speed+engine",),
            ),
        ),
        spatial_summaries=(
            SpatialEvidenceSummary(
                candidate_key="engine_2x",
                suspected_source="engine",
                proof_basis="supporting_windows_raw_backed",
                total_window_count=4,
                supporting_window_count=2,
                supporting_sensor_count=2,
                coherent_window_count=1,
                coherence_ratio=0.5,
                dominant_location="front-right",
                runner_up_location="rear-right",
                location_separation_db=0.8,
                dominance_ratio=1.05,
                ambiguous_location=True,
                weak_spatial_separation=True,
                location_summaries=(
                    SpatialLocationSummary(
                        location="front-right",
                        sensor_ids=("front",),
                        supporting_window_count=1,
                        support_ratio=0.5,
                        coherent_window_count=1,
                        coherence_ratio=1.0,
                    ),
                    SpatialLocationSummary(
                        location="rear-right",
                        sensor_ids=("rear",),
                        supporting_window_count=1,
                        support_ratio=0.5,
                        coherent_window_count=0,
                        coherence_ratio=0.0,
                    ),
                ),
            ),
        ),
    )

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.suspicious is True
    assert summary.ambiguous_location is True
    assert summary.weak_spatial_separation is True
    assert "speed_context_gaps" in {factor.factor_key for factor in summary.counterevidence_factors}
    assert "rpm_context_gaps" in {factor.factor_key for factor in summary.counterevidence_factors}
    assert "weak_spatial" in {factor.factor_key for factor in summary.counterevidence_factors}
