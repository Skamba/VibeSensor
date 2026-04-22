"""Appendix presentation models for PDF report assembly."""

from __future__ import annotations

from dataclasses import dataclass, field

from .panels import DataTrustItem

__all__ = [
    "AppendixAData",
    "AppendixBData",
    "AppendixCData",
    "EvidenceChainRow",
    "MeasurementRow",
    "ProofWindowRow",
    "RankedCandidateRow",
    "ReportLabelValueRow",
    "SensorObservationCell",
    "SensorObservationMatrixRow",
    "TopologyIntensityRow",
]


@dataclass
class ReportLabelValueRow:
    """A simple label/value row used in appendix metadata blocks."""

    label: str = ""
    value: str = ""


@dataclass
class RankedCandidateRow:
    """One ranked source row used in the worksheet appendix."""

    source_name: str = ""
    confidence_pct: str | None = None
    inspect_first: str | None = None
    path_role: str | None = None
    reason: str | None = None


@dataclass
class TopologyIntensityRow:
    """One topology/intensity row for the sensor-topology appendix."""

    location: str = ""
    p95_db: float | None = None
    coverage_state: str | None = None


@dataclass
class SensorObservationCell:
    """One per-sensor relative observation cell for a signal row."""

    location: str = ""
    relative_level_db: float | None = None


@dataclass
class SensorObservationMatrixRow:
    """One detected signal row in the Appendix B sensor-observation matrix."""

    source_name: str = ""
    signal_label: str = ""
    sensor_levels: list[SensorObservationCell] = field(default_factory=list)


@dataclass
class MeasurementRow:
    """One supporting-measurement row in the evidence appendix."""

    measurement_id: str = ""
    source_name: str = ""
    signal_label: str = ""
    frequency_hz: float | None = None
    peak_db: float | None = None
    strength_db: float | None = None
    speed_window: str | None = None
    dominant_location: str | None = None
    classification: str | None = None


@dataclass
class ProofWindowRow:
    """One retained supporting-window exemplar for the chosen diagnosis."""

    window_id: str = ""
    time_s: float | None = None
    speed_kmh: float | None = None
    matched_hz: float | None = None
    dominant_location: str | None = None
    phase: str | None = None


@dataclass
class EvidenceChainRow:
    """One evidence-chain row tying a candidate to concrete measurements."""

    source_name: str = ""
    supporting_signal_label: str = ""
    measurement_refs: list[str] = field(default_factory=list)
    matched_evidence_window_count: int | None = None
    speed_window: str | None = None
    dominant_location: str | None = None
    ambiguity_note: str | None = None


@dataclass
class AppendixAData:
    """Technician worksheet or capture-guidance appendix data."""

    mode: str = "workflow"
    primary_source: str | None = None
    alternative_source: str | None = None
    why_primary_first: str | None = None
    why_alternative_next: str | None = None
    next_if_clean: str | None = None
    ranked_candidates: list[RankedCandidateRow] = field(default_factory=list)
    capture_issues: list[str] = field(default_factory=list)
    capture_changes: list[str] = field(default_factory=list)
    capture_conditions: list[str] = field(default_factory=list)


@dataclass
class AppendixBData:
    """Spatial-proof appendix content and sensor-by-signal view."""

    dominant_corner: str | None = None
    runner_up_corner: str | None = None
    dominance_ratio_text: str | None = None
    location_confidence: str | None = None
    coverage_label: str | None = None
    coverage_notes: list[str] = field(default_factory=list)
    intensity_rows: list[TopologyIntensityRow] = field(default_factory=list)
    sensor_observation_rows: list[SensorObservationMatrixRow] = field(default_factory=list)


@dataclass
class AppendixCData:
    """Evidence appendix content."""

    evidence_chain_rows: list[EvidenceChainRow] = field(default_factory=list)
    measurement_rows: list[MeasurementRow] = field(default_factory=list)
    proof_window_rows: list[ProofWindowRow] = field(default_factory=list)
    evidence_snapshot_rows: list[ReportLabelValueRow] = field(default_factory=list)
    evidence_summary: str | None = None
    measurement_guide: str | None = None
    context_summary: str | None = None
    limits_summary: str | None = None
    speed_band_summary: str | None = None
    phase_summary: str | None = None
    observations: list[str] = field(default_factory=list)
    suitability_items: list[DataTrustItem] = field(default_factory=list)
