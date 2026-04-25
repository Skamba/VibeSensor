from __future__ import annotations

from dataclasses import dataclass

from test_support.findings import make_finding_payload
from test_support.report_helpers import minimal_summary
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
from vibesensor.use_cases.diagnostics.whole_run_diagnosis_contracts import (
    WholeRunDiagnosisSummary,
)
from vibesensor.use_cases.diagnostics.whole_run_diagnosis_ranking import (
    build_whole_run_diagnosis_summaries,
)


@dataclass(frozen=True, slots=True)
class WholeRunDiagnosisScenario:
    case_id: str
    analysis_metadata: dict[str, object]
    context_intervals: tuple[WholeRunContextInterval, ...]
    order_summaries: tuple[OrderTraceSummary, ...]
    spatial_summaries: tuple[SpatialEvidenceSummary, ...]
    findings: tuple[dict[str, object], ...]
    top_causes: tuple[dict[str, object], ...]
    expected_ranked_sources: tuple[str, ...]
    expected_report_source: str
    expected_report_alternative: str | None
    expected_report_location: str
    expected_report_frequency_fragment: str
    expected_primary_ambiguous: bool
    expected_primary_suspicious: bool
    expected_primary_counterevidence_keys: tuple[str, ...]
    expected_runner_up_counterevidence_keys: tuple[str, ...] = ()

    def build_diagnosis_summaries(self) -> tuple[WholeRunDiagnosisSummary, ...]:
        return build_whole_run_diagnosis_summaries(
            analysis_metadata=self.analysis_metadata,
            context_intervals=self.context_intervals,
            order_summaries=self.order_summaries,
            spatial_summaries=self.spatial_summaries,
            car_order_reference_status=None,
        )

    def build_report_summary(self) -> dict[str, object]:
        return minimal_summary(
            run_id=f"{self.case_id}-report",
            lang="en",
            metadata={
                "run_id": f"{self.case_id}-report",
                "record_type": "metadata",
                "schema_version": "v2-jsonl",
                "feature_interval_s": 0.5,
            },
            sensor_count_used=4,
            sensor_locations=["Front Left", "Front Right", "Rear Left", "Rear Right"],
            sensor_locations_connected_throughout=[
                "Front Left",
                "Front Right",
                "Rear Left",
                "Rear Right",
            ],
            sensor_intensity_by_location=[
                {"location": "Front Left", "p95_intensity_db": 18.0, "peak_intensity_db": 22.0},
                {"location": "Front Right", "p95_intensity_db": 12.0, "peak_intensity_db": 15.0},
                {"location": "Rear Left", "p95_intensity_db": 14.0, "peak_intensity_db": 17.0},
                {"location": "Rear Right", "p95_intensity_db": 13.0, "peak_intensity_db": 16.0},
            ],
            findings=list(self.findings),
            top_causes=list(self.top_causes),
            analysis_metadata=self.analysis_metadata,
            whole_run_diagnosis_summaries=[
                summary.to_json_object() for summary in self.build_diagnosis_summaries()
            ],
        )


def whole_run_diagnosis_scenarios() -> tuple[WholeRunDiagnosisScenario, ...]:
    return (
        _clear_wheel_scenario(),
        _counterevidence_overturn_scenario(),
        _ambiguous_matching_source_scenario(),
    )


def _context_interval(
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


def _finding(
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


def _order_summary(
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


def _spatial_summary(
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


def _clear_wheel_scenario() -> WholeRunDiagnosisScenario:
    wheel = _finding(
        finding_id="F_CLEAR_WHEEL",
        suspected_source="wheel/tire",
        confidence=0.82,
        strongest_location="Front Left",
        strongest_speed_band="60-80 km/h",
        dominant_phase="cruise",
        matched_hz=13.2,
    )
    driveline = _finding(
        finding_id="F_CLEAR_DRIVELINE",
        suspected_source="driveline",
        confidence=0.70,
        strongest_location="Rear Left",
        strongest_speed_band="60-80 km/h",
        dominant_phase="cruise",
        matched_hz=26.4,
    )
    return WholeRunDiagnosisScenario(
        case_id="clear-wheel",
        analysis_metadata={
            "raw_backed_sample_count": 96,
            "raw_capture_mode": "raw_backed",
            "whole_run_context_available": True,
        },
        context_intervals=(_context_interval(),),
        order_summaries=(
            _order_summary(
                hypothesis_key="wheel_1x",
                suspected_source="wheel/tire",
                order_family="wheel",
                order_label="1x wheel",
                matched_window_count=7,
                support_ratio=0.88,
                reference_coverage_ratio=1.0,
                longest_contiguous_support_window_count=6,
                contiguous_support_ratio=0.75,
                stable_frequency_min_hz=13.1,
                stable_frequency_max_hz=13.4,
                dominant_phase="cruise",
                dominant_speed_band="60-80 km/h",
                strongest_location="front-left",
                mean_relative_error=0.02,
                drift_score=0.06,
                lock_score=0.9,
                peak_intensity_db=19.5,
                mean_vibration_strength_db=10.8,
                ref_sources=("speed+tire",),
            ),
            _order_summary(
                hypothesis_key="driveline_1x",
                suspected_source="driveline",
                order_family="driveline",
                order_label="1x driveshaft",
                matched_window_count=2,
                support_ratio=0.25,
                reference_coverage_ratio=0.75,
                longest_contiguous_support_window_count=1,
                contiguous_support_ratio=0.12,
                stable_frequency_min_hz=26.1,
                stable_frequency_max_hz=26.4,
                dominant_phase="cruise",
                dominant_speed_band="60-80 km/h",
                strongest_location="rear-left",
                mean_relative_error=0.07,
                drift_score=0.22,
                lock_score=0.5,
                peak_intensity_db=12.5,
                mean_vibration_strength_db=7.5,
                ref_sources=("speed+driveshaft",),
            ),
        ),
        spatial_summaries=(
            _spatial_summary(
                candidate_key="wheel_1x",
                suspected_source="wheel/tire",
                dominant_location="front-left",
                runner_up_location="front-right",
                supporting_window_count=7,
                supporting_sensor_count=2,
                coherent_window_count=6,
                coherence_ratio=0.86,
                location_separation_db=3.6,
                dominance_ratio=1.55,
            ),
            _spatial_summary(
                candidate_key="driveline_1x",
                suspected_source="driveline",
                dominant_location="rear-left",
                runner_up_location="rear-right",
                supporting_window_count=2,
                supporting_sensor_count=2,
                coherent_window_count=1,
                coherence_ratio=0.5,
                location_separation_db=1.2,
                dominance_ratio=1.02,
                ambiguous_location=True,
                weak_spatial_separation=True,
            ),
        ),
        findings=(wheel, driveline),
        top_causes=(wheel, driveline),
        expected_ranked_sources=("wheel/tire", "driveline"),
        expected_report_source="Wheel / Tire",
        expected_report_alternative="Driveline",
        expected_report_location="Front-Left",
        expected_report_frequency_fragment="13.1",
        expected_primary_ambiguous=False,
        expected_primary_suspicious=False,
        expected_primary_counterevidence_keys=(),
        expected_runner_up_counterevidence_keys=("weak_spatial", "incomplete_reference"),
    )


def _counterevidence_overturn_scenario() -> WholeRunDiagnosisScenario:
    wheel = _finding(
        finding_id="F_COUNTER_WHEEL",
        suspected_source="wheel/tire",
        confidence=0.84,
        strongest_location="Front Left",
        strongest_speed_band="50-70 km/h",
        dominant_phase="accel",
        matched_hz=15.0,
    )
    engine = _finding(
        finding_id="F_COUNTER_ENGINE",
        suspected_source="engine",
        confidence=0.73,
        strongest_location="Front Right",
        strongest_speed_band="50-70 km/h",
        dominant_phase="accel",
        matched_hz=22.5,
    )
    return WholeRunDiagnosisScenario(
        case_id="counterevidence-overturn",
        analysis_metadata={
            "raw_backed_sample_count": 64,
            "raw_capture_mode": "raw_backed",
            "whole_run_context_available": True,
            "whole_run_context_missing_speed_window_count": 1,
            "whole_run_context_stale_speed_window_count": 1,
            "whole_run_context_missing_rpm_window_count": 0,
            "whole_run_context_stale_rpm_window_count": 1,
        },
        context_intervals=(
            _context_interval(
                phase=DrivingPhase.ACCELERATION,
                load_state="pulling",
                speed_band="50-70 km/h",
                full_window_count=5,
                partial_window_count=2,
                missing_window_count=1,
            ),
        ),
        order_summaries=(
            _order_summary(
                hypothesis_key="wheel_1x",
                suspected_source="wheel/tire",
                order_family="wheel",
                order_label="1x wheel",
                matched_window_count=6,
                support_ratio=0.75,
                reference_coverage_ratio=0.55,
                longest_contiguous_support_window_count=2,
                contiguous_support_ratio=0.25,
                stable_frequency_min_hz=14.8,
                stable_frequency_max_hz=15.4,
                dominant_phase="accel",
                dominant_speed_band="50-70 km/h",
                strongest_location="front-left",
                mean_relative_error=0.08,
                drift_score=0.32,
                lock_score=0.42,
                peak_intensity_db=18.0,
                mean_vibration_strength_db=11.0,
                ref_sources=("speed+tire",),
            ),
            _order_summary(
                hypothesis_key="engine_2x",
                suspected_source="engine",
                order_family="engine",
                order_label="2x engine",
                matched_window_count=5,
                support_ratio=0.62,
                reference_coverage_ratio=0.92,
                longest_contiguous_support_window_count=4,
                contiguous_support_ratio=0.5,
                stable_frequency_min_hz=22.4,
                stable_frequency_max_hz=22.7,
                dominant_phase="accel",
                dominant_speed_band="50-70 km/h",
                strongest_location="front-right",
                mean_relative_error=0.03,
                drift_score=0.1,
                lock_score=0.81,
                peak_intensity_db=16.5,
                mean_vibration_strength_db=9.6,
                ref_sources=("speed+engine",),
            ),
        ),
        spatial_summaries=(
            _spatial_summary(
                candidate_key="wheel_1x",
                suspected_source="wheel/tire",
                dominant_location="front-left",
                runner_up_location="rear-left",
                supporting_window_count=6,
                supporting_sensor_count=2,
                coherent_window_count=2,
                coherence_ratio=0.33,
                location_separation_db=0.7,
                dominance_ratio=1.04,
                ambiguous_location=True,
                weak_spatial_separation=True,
            ),
            _spatial_summary(
                candidate_key="engine_2x",
                suspected_source="engine",
                dominant_location="front-right",
                runner_up_location="rear-right",
                supporting_window_count=5,
                supporting_sensor_count=2,
                coherent_window_count=4,
                coherence_ratio=0.8,
                location_separation_db=2.8,
                dominance_ratio=1.35,
            ),
        ),
        findings=(wheel, engine),
        top_causes=(wheel, engine),
        expected_ranked_sources=("engine", "wheel/tire"),
        expected_report_source="Engine",
        expected_report_alternative="Wheel / Tire",
        expected_report_location="Front-Right",
        expected_report_frequency_fragment="22.4",
        expected_primary_ambiguous=False,
        expected_primary_suspicious=False,
        expected_primary_counterevidence_keys=(
            "speed_context_gaps",
            "rpm_context_gaps",
            "incomplete_reference",
        ),
        expected_runner_up_counterevidence_keys=(
            "weak_spatial",
            "speed_context_gaps",
            "rpm_context_gaps",
        ),
    )


def _ambiguous_matching_source_scenario() -> WholeRunDiagnosisScenario:
    wheel = _finding(
        finding_id="F_AMBIG_WHEEL",
        suspected_source="wheel/tire",
        confidence=0.80,
        strongest_location="Front Left",
        strongest_speed_band="100-110 km/h",
        dominant_phase="cruise",
        matched_hz=12.9,
    )
    driveline = _finding(
        finding_id="F_AMBIG_DRIVELINE",
        suspected_source="driveline",
        confidence=0.74,
        strongest_location="Front Left",
        strongest_speed_band="100-110 km/h",
        dominant_phase="cruise",
        matched_hz=39.8,
    )
    engine = _finding(
        finding_id="F_AMBIG_ENGINE",
        suspected_source="engine",
        confidence=0.72,
        strongest_location="Front Left",
        strongest_speed_band="100-110 km/h",
        dominant_phase="cruise",
        matched_hz=51.2,
    )
    return WholeRunDiagnosisScenario(
        case_id="ambiguous-matching-source",
        analysis_metadata={
            "raw_backed_sample_count": 84,
            "raw_capture_mode": "raw_backed",
            "whole_run_context_available": True,
        },
        context_intervals=(_context_interval(speed_band="100-110 km/h"),),
        order_summaries=(
            _order_summary(
                hypothesis_key="driveshaft",
                suspected_source="driveline",
                order_family="driveline",
                order_label="1x driveshaft",
                matched_window_count=5,
                support_ratio=0.62,
                reference_coverage_ratio=0.9,
                longest_contiguous_support_window_count=3,
                contiguous_support_ratio=0.38,
                stable_frequency_min_hz=39.8,
                stable_frequency_max_hz=39.8,
                dominant_phase="cruise",
                dominant_speed_band="100-110 km/h",
                strongest_location="front-left",
                mean_relative_error=0.03,
                drift_score=0.1,
                lock_score=0.82,
                peak_intensity_db=18.0,
                mean_vibration_strength_db=10.0,
                ref_sources=("speed+driveshaft",),
            ),
            _order_summary(
                hypothesis_key="engine",
                suspected_source="engine",
                order_family="engine",
                order_label="2x engine",
                matched_window_count=5,
                support_ratio=0.62,
                reference_coverage_ratio=0.9,
                longest_contiguous_support_window_count=3,
                contiguous_support_ratio=0.38,
                stable_frequency_min_hz=51.2,
                stable_frequency_max_hz=51.2,
                dominant_phase="cruise",
                dominant_speed_band="100-110 km/h",
                strongest_location="front-left",
                mean_relative_error=0.03,
                drift_score=0.1,
                lock_score=0.82,
                peak_intensity_db=18.0,
                mean_vibration_strength_db=10.0,
                ref_sources=("speed+engine",),
            ),
            _order_summary(
                hypothesis_key="wheel",
                suspected_source="wheel/tire",
                order_family="wheel",
                order_label="1x wheel",
                matched_window_count=5,
                support_ratio=0.62,
                reference_coverage_ratio=0.9,
                longest_contiguous_support_window_count=3,
                contiguous_support_ratio=0.38,
                stable_frequency_min_hz=12.9,
                stable_frequency_max_hz=12.9,
                dominant_phase="cruise",
                dominant_speed_band="100-110 km/h",
                strongest_location="front-left",
                mean_relative_error=0.03,
                drift_score=0.1,
                lock_score=0.82,
                peak_intensity_db=18.0,
                mean_vibration_strength_db=10.0,
                ref_sources=("speed+tire",),
            ),
        ),
        spatial_summaries=(
            _spatial_summary(
                candidate_key="driveshaft",
                suspected_source="driveline",
                dominant_location="front-left",
                runner_up_location="rear-left",
                supporting_window_count=5,
                supporting_sensor_count=3,
                coherent_window_count=4,
                coherence_ratio=0.8,
                location_separation_db=2.4,
                dominance_ratio=1.2,
            ),
            _spatial_summary(
                candidate_key="engine",
                suspected_source="engine",
                dominant_location="front-left",
                runner_up_location="rear-right",
                supporting_window_count=5,
                supporting_sensor_count=3,
                coherent_window_count=4,
                coherence_ratio=0.8,
                location_separation_db=2.4,
                dominance_ratio=1.2,
            ),
            _spatial_summary(
                candidate_key="wheel",
                suspected_source="wheel/tire",
                dominant_location="front-left",
                runner_up_location="front-right",
                supporting_window_count=5,
                supporting_sensor_count=3,
                coherent_window_count=4,
                coherence_ratio=0.8,
                location_separation_db=2.4,
                dominance_ratio=1.2,
            ),
        ),
        findings=(wheel, driveline, engine),
        top_causes=(wheel, driveline, engine),
        expected_ranked_sources=("driveline", "engine", "wheel/tire"),
        expected_report_source="Wheel / Tire",
        expected_report_alternative="Driveline",
        expected_report_location="Front-Left",
        expected_report_frequency_fragment="12.9",
        expected_primary_ambiguous=True,
        expected_primary_suspicious=True,
        expected_primary_counterevidence_keys=("close_alternative", "incomplete_reference"),
        expected_runner_up_counterevidence_keys=("close_alternative", "incomplete_reference"),
    )
