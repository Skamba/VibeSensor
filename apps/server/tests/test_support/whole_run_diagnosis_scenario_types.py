"""Whole-run diagnosis scenario DTOs."""

from __future__ import annotations

from dataclasses import dataclass

from test_support.report_helpers import minimal_summary
from vibesensor.shared.types.whole_run_analysis import WholeRunContextInterval
from vibesensor.use_cases.diagnostics.orders.whole_run_contracts import OrderTraceSummary
from vibesensor.use_cases.diagnostics.spatial_evidence_contracts import SpatialEvidenceSummary
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
