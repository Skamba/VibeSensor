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

from .section_context import AppendixBContext

__all__ = ["build_appendix_b_data"]


def build_appendix_b_data(
    *,
    aggregate: TestRun,
    primary_candidate_facts: PrimaryReportFacts,
    active_sensor_intensity: Sequence[LocationIntensitySummary],
    proof_basis: str,
    appendix_context: AppendixBContext,
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
        runner_up_corner=appendix_context.runner_up_corner,
        dominance_ratio_text=dominance_ratio_text,
        proof_basis_note=_location_proof_basis_note(proof_basis, tr=tr),
        location_confidence=location_confidence_text(
            presented_location_confidence_key(
                action_status_key=appendix_context.action_status_key,
                location_confidence_key=appendix_context.location_confidence_key,
            ),
            tr=tr,
        ),
        coverage_label=appendix_context.coverage_label,
        coverage_notes=list(appendix_context.coverage_notes),
        intensity_rows=intensity_rows,
        sensor_observation_rows=build_sensor_observation_matrix_rows(
            aggregate,
            sensor_locations=list(appendix_context.active_locations),
            tr=tr,
        ),
    )


def _location_proof_basis_note(proof_basis: str, *, tr: Callable[..., str]) -> str:
    if proof_basis == "supporting_windows_raw_backed":
        return tr("REPORT_LOCATION_PROOF_BASIS_SUPPORTING_WINDOWS_RAW")
    if proof_basis == "supporting_windows_summary_only":
        return tr("REPORT_LOCATION_PROOF_BASIS_SUPPORTING_WINDOWS_SUMMARY")
    return tr("REPORT_LOCATION_PROOF_BASIS_WHOLE_RUN")
