"""Appendix-B location and topology builders for report document composition."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from vibesensor.domain import LocationIntensitySummary, TestRun
from vibesensor.shared.boundaries.reporting.document import AppendixBData, TopologyIntensityRow
from vibesensor.shared.boundaries.reporting.projection import PrimaryReportFacts
from vibesensor.shared.report_presentation import (
    display_location,
    location_confidence_text,
    presented_location_confidence_key,
)
from vibesensor.use_cases.history.report_observation_matrix import (
    build_sensor_observation_matrix_rows,
)

__all__ = ["build_appendix_b_data"]


def build_appendix_b_data(
    *,
    aggregate: TestRun,
    primary_candidate_facts: PrimaryReportFacts,
    active_sensor_intensity: Sequence[LocationIntensitySummary],
    action_status_key: str,
    location_confidence_key: str,
    active_locations: Sequence[str],
    runner_up_corner: str | None,
    coverage_label: str,
    coverage_notes: Sequence[str],
    tr: Callable[..., str],
) -> AppendixBData:
    dominance_ratio_text = (
        tr(
            "REPORT_DOMINANCE_RATIO_TEXT",
            ratio=f"{primary_candidate_facts.dominance_ratio:.2f}",
        )
        if primary_candidate_facts.dominance_ratio is not None
        else tr("REPORT_DOMINANCE_RATIO_UNKNOWN")
    )
    ranked_rows = sorted(
        active_sensor_intensity,
        key=lambda row: (
            row.p95_intensity_db if row.p95_intensity_db is not None else float("-inf"),
        ),
        reverse=True,
    )
    intensity_rows = [
        TopologyIntensityRow(
            location=display_location(row.location, short=False, tr=tr),
            p95_db=row.p95_intensity_db,
            coverage_state=(
                tr("REPORT_COVERAGE_STATE_PARTIAL")
                if row.partial_coverage or row.sample_coverage_warning
                else tr("REPORT_COVERAGE_STATE_COMPLETE")
            ),
        )
        for row in ranked_rows
    ]
    return AppendixBData(
        dominant_corner=display_location(primary_candidate_facts.primary_location, tr=tr),
        runner_up_corner=runner_up_corner,
        dominance_ratio_text=dominance_ratio_text,
        location_confidence=location_confidence_text(
            presented_location_confidence_key(
                action_status_key=action_status_key,
                location_confidence_key=location_confidence_key,
            ),
            tr=tr,
        ),
        coverage_label=coverage_label,
        coverage_notes=list(coverage_notes),
        intensity_rows=intensity_rows,
        sensor_observation_rows=build_sensor_observation_matrix_rows(
            aggregate,
            sensor_locations=list(active_locations),
            tr=tr,
        ),
    )
