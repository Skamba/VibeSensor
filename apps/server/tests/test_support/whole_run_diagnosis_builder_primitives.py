"""Primitive builders for whole-run diagnosis scenarios."""

from __future__ import annotations

from test_support.findings import make_finding_payload
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


def context_interval(
    *,
    phase: DrivingPhase = DrivingPhase.CRUISE,
    load_state: str = "steady",
    speed_band: str = "60-80 km/h",
    full_window_count: int = 8,
    partial_window_count: int = 0,
    missing_window_count: int = 0,
) -> WholeRunContextInterval:
    return WholeRunContextInterval(
        segment_index=0,
        phase=phase,
        load_state=load_state,
        start_window_index=0,
        end_window_index=max(
            0,
            full_window_count + partial_window_count + missing_window_count - 1,
        ),
        start_t_s=0.0,
        end_t_s=4.0,
        speed_min_kmh=58.0,
        speed_max_kmh=72.0,
        speed_band=speed_band,
        full_context_window_count=full_window_count,
        partial_context_window_count=partial_window_count,
        missing_context_window_count=missing_window_count,
    )


def diagnosis_finding(
    *,
    finding_id: str,
    suspected_source: str,
    confidence: float,
    strongest_location: str,
    strongest_speed_band: str,
    dominant_phase: str,
    matched_hz: float,
) -> dict[str, object]:
    return make_finding_payload(
        finding_id=finding_id,
        suspected_source=suspected_source,
        confidence=confidence,
        strongest_location=strongest_location,
        strongest_speed_band=strongest_speed_band,
        dominant_phase=dominant_phase,
        matched_points=[
            {
                "t_s": 1.0,
                "speed_kmh": 64.0,
                "predicted_hz": matched_hz,
                "matched_hz": matched_hz,
                "location": strongest_location,
                "phase": dominant_phase,
                "amp": 0.12,
            }
        ],
        evidence_metrics={
            "mean_relative_error": 0.03,
            "snr_db": 8.0,
            "matched_samples": 1,
        },
    )


def order_summary(
    *,
    hypothesis_key: str,
    suspected_source: str,
    order_family: str,
    order_label: str,
    matched_window_count: int,
    support_ratio: float,
    reference_coverage_ratio: float,
    longest_contiguous_support_window_count: int,
    contiguous_support_ratio: float,
    stable_frequency_min_hz: float,
    stable_frequency_max_hz: float,
    dominant_phase: str,
    dominant_speed_band: str,
    strongest_location: str,
    mean_relative_error: float,
    drift_score: float,
    lock_score: float,
    peak_intensity_db: float,
    mean_vibration_strength_db: float,
    ref_sources: tuple[str, ...],
) -> OrderTraceSummary:
    return OrderTraceSummary(
        hypothesis_key=hypothesis_key,
        suspected_source=suspected_source,
        order_family=order_family,
        order_label=order_label,
        total_window_count=8,
        eligible_window_count=8,
        matched_window_count=matched_window_count,
        support_ratio=support_ratio,
        reference_coverage_ratio=reference_coverage_ratio,
        longest_contiguous_support_window_count=longest_contiguous_support_window_count,
        contiguous_support_ratio=contiguous_support_ratio,
        support_intervals=(
            OrderTraceSupportInterval(
                interval_index=0,
                start_window_index=1,
                end_window_index=max(1, matched_window_count - 1),
                matched_window_count=matched_window_count,
                support_ratio=1.0,
                start_t_s=0.5,
                end_t_s=2.0,
                phase=dominant_phase,
                speed_band=dominant_speed_band,
                mean_relative_error=mean_relative_error,
            ),
        ),
        stable_frequency_min_hz=stable_frequency_min_hz,
        stable_frequency_max_hz=stable_frequency_max_hz,
        exemplar_interval_index=0,
        dominant_phase=dominant_phase,
        dominant_speed_band=dominant_speed_band,
        strongest_location=strongest_location,
        mean_relative_error=mean_relative_error,
        drift_score=drift_score,
        lock_score=lock_score,
        peak_intensity_db=peak_intensity_db,
        mean_vibration_strength_db=mean_vibration_strength_db,
        ref_sources=ref_sources,
    )


def spatial_summary(
    *,
    candidate_key: str,
    suspected_source: str,
    dominant_location: str,
    runner_up_location: str,
    supporting_window_count: int,
    supporting_sensor_count: int,
    coherent_window_count: int,
    coherence_ratio: float | None,
    location_separation_db: float | None,
    dominance_ratio: float | None,
    ambiguous_location: bool = False,
    weak_spatial_separation: bool = False,
) -> SpatialEvidenceSummary:
    dominant_share = (
        supporting_window_count - 1 if supporting_window_count > 1 else supporting_window_count
    )
    runner_up_share = 1 if supporting_window_count > 1 else 0
    return SpatialEvidenceSummary(
        candidate_key=candidate_key,
        suspected_source=suspected_source,
        proof_basis="supporting_windows_raw_backed",
        total_window_count=8,
        supporting_window_count=supporting_window_count,
        supporting_sensor_count=supporting_sensor_count,
        coherent_window_count=coherent_window_count,
        coherence_ratio=coherence_ratio,
        dominant_location=dominant_location,
        runner_up_location=runner_up_location,
        location_separation_db=location_separation_db,
        dominance_ratio=dominance_ratio,
        ambiguous_location=ambiguous_location,
        weak_spatial_separation=weak_spatial_separation,
        location_summaries=(
            SpatialLocationSummary(
                location=dominant_location,
                sensor_ids=(dominant_location,),
                supporting_window_count=dominant_share,
                support_ratio=dominant_share / max(1, supporting_window_count),
                coherent_window_count=max(1, coherent_window_count - runner_up_share),
                coherence_ratio=coherence_ratio,
            ),
            SpatialLocationSummary(
                location=runner_up_location,
                sensor_ids=(runner_up_location,),
                supporting_window_count=runner_up_share,
                support_ratio=runner_up_share / max(1, supporting_window_count),
                coherent_window_count=runner_up_share,
                coherence_ratio=1.0 if runner_up_share else 0.0,
            ),
        ),
    )
