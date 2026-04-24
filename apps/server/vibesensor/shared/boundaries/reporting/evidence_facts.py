"""Evidence-centric prepared report facts for PDF/report mapping."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

from vibesensor.shared.boundaries.codecs.scalars import coerce_count, text_or_none
from vibesensor.shared.boundaries.reporting.decision_facts import ReportDecisionFacts
from vibesensor.shared.boundaries.reporting.projection import PrimaryReportFacts
from vibesensor.shared.boundaries.reporting.summary import NormalizedReportSummary

__all__ = [
    "ReportEvidenceFacts",
    "build_report_evidence_facts",
]


@dataclass(frozen=True, slots=True)
class ReportEvidenceFacts:
    """Prepared evidence facts shared by page-1 proof and Appendix C."""

    data_basis: str
    raw_backed_sample_count: int
    supporting_window_count: int | None
    supporting_duration_s: float | None
    stable_frequency_min_hz: float | None
    stable_frequency_max_hz: float | None
    supporting_location_counts: tuple[tuple[str, int], ...]
    has_weak_spatial_separation: bool
    alternative_source: str | None
    has_reference_gap: bool


def build_report_evidence_facts(
    payload: Mapping[str, object],
    *,
    summary: NormalizedReportSummary,
    primary_candidate: PrimaryReportFacts,
    decision_facts: ReportDecisionFacts,
) -> ReportEvidenceFacts:
    """Build prepared evidence facts from persisted analysis plus domain finding data."""

    metadata = payload.get("analysis_metadata")
    analysis_metadata = metadata if isinstance(metadata, Mapping) else {}
    raw_backed_sample_count = coerce_count(analysis_metadata.get("raw_backed_sample_count"))
    data_basis = _resolve_data_basis(analysis_metadata, raw_backed_sample_count)
    supporting_window_count = primary_candidate.matched_evidence_window_count
    duration_s = _supporting_duration_s(
        supporting_window_count=supporting_window_count,
        feature_interval_s=(
            summary.metadata.feature_interval_s if summary.metadata is not None else None
        ),
    )
    frequency_min_hz, frequency_max_hz = _stable_frequency_band(primary_candidate)
    return ReportEvidenceFacts(
        data_basis=data_basis,
        raw_backed_sample_count=raw_backed_sample_count,
        supporting_window_count=supporting_window_count,
        supporting_duration_s=duration_s,
        stable_frequency_min_hz=frequency_min_hz,
        stable_frequency_max_hz=frequency_max_hz,
        supporting_location_counts=_supporting_location_counts(primary_candidate),
        has_weak_spatial_separation=primary_candidate.weak_spatial,
        alternative_source=(
            decision_facts.alternative_source if decision_facts.alternative_source_visible else None
        ),
        has_reference_gap=primary_candidate.has_reference_gaps,
    )


def _resolve_data_basis(
    analysis_metadata: Mapping[str, object],
    raw_backed_sample_count: int,
) -> str:
    raw_capture_mode = text_or_none(analysis_metadata.get("raw_capture_mode"))
    if raw_capture_mode in {"raw_backed", "partial_raw_backed", "summary_only"}:
        return raw_capture_mode
    return "raw_backed" if raw_backed_sample_count > 0 else "summary_only"


def _supporting_duration_s(
    *,
    supporting_window_count: int | None,
    feature_interval_s: float | None,
) -> float | None:
    if supporting_window_count is None or supporting_window_count <= 0:
        return None
    if feature_interval_s is None or feature_interval_s <= 0:
        return None
    return supporting_window_count * feature_interval_s


def _stable_frequency_band(
    primary_candidate: PrimaryReportFacts,
) -> tuple[float | None, float | None]:
    finding = primary_candidate.domain_primary
    if finding is None:
        return (None, None)
    matched_hz_values = [
        observation.matched_hz if observation.matched_hz > 0 else observation.predicted_hz
        for observation in finding.matched_points
        if observation.predicted_hz > 0
    ]
    if matched_hz_values:
        return (min(matched_hz_values), max(matched_hz_values))
    if finding.frequency_hz is not None and finding.frequency_hz > 0:
        return (finding.frequency_hz, finding.frequency_hz)
    return (None, None)


def _supporting_location_counts(
    primary_candidate: PrimaryReportFacts,
) -> tuple[tuple[str, int], ...]:
    finding = primary_candidate.domain_primary
    if finding is None:
        return ()
    counts: Counter[str] = Counter()
    order: dict[str, int] = {}
    for observation in finding.matched_points:
        location = str(observation.location or "").strip()
        if not location:
            continue
        counts[location] += 1
        order.setdefault(location, len(order))
    if counts:
        ranked = sorted(counts.items(), key=lambda item: (-item[1], order[item[0]], item[0]))
        return tuple(ranked[:3])
    if finding.strongest_location:
        return ((finding.strongest_location, 1),)
    return ()
