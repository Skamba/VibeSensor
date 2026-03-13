"""Intermediate data model for the diagnostic PDF report.

Pure data-class definitions consumed by the Canvas-based PDF renderer.
The ``map_summary()`` builder that populates these classes lives in
``vibesensor.report.mapping.pipeline``.
"""

from __future__ import annotations

__all__ = [
    "CarMeta",
    "DataTrustItem",
    "NextStep",
    "PartSuggestion",
    "PatternEvidence",
    "PeakRow",
    "ReportTemplateData",
    "SystemFindingCard",
]

from dataclasses import dataclass, field

from ..json_types import JsonObject

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class CarMeta:
    """Vehicle identification metadata (name, type) extracted from the report run."""

    name: str | None = None
    car_type: str | None = None


@dataclass
class PartSuggestion:
    """A suggested replacement part associated with a diagnostic finding."""

    name: str = ""


@dataclass
class SystemFindingCard:
    """A per-system diagnostic finding card for the report, with location and parts."""

    system_name: str = ""
    strongest_location: str | None = None
    pattern_summary: str | None = None
    parts: list[PartSuggestion] = field(default_factory=list)
    tone: str = "neutral"


@dataclass
class NextStep:
    """A recommended diagnostic next step (action, rationale, ETA)."""

    action: str = ""
    why: str | None = None
    confirm: str | None = None
    falsify: str | None = None
    eta: str | None = None


@dataclass
class DataTrustItem:
    """A single data-quality check result (pass/warn/fail with detail).

    ``state`` defaults to ``"warn"`` so that data quality items reconstructed
    from older persisted data (where the ``state`` key may be absent) are
    treated conservatively rather than silently marked as passing.
    """

    check: str = ""
    state: str = "warn"
    detail: str | None = None


@dataclass
class PatternEvidence:
    """Evidence summary for the dominant vibration pattern from post-analysis.

    This class also serves as the observed-signature block for the report
    template (the ``observed`` field on :class:`ReportTemplateData`).
    """

    primary_system: str | None = None
    matched_systems: list[str] = field(default_factory=list)
    strongest_location: str | None = None
    speed_band: str | None = None
    strength_label: str | None = None
    strength_peak_db: float | None = None
    certainty_label: str | None = None
    certainty_pct: str | None = None
    certainty_reason: str | None = None
    warning: str | None = None
    interpretation: str | None = None
    why_parts_text: str | None = None


@dataclass
class PeakRow:
    """A single row in the report's peak-frequency evidence table."""

    rank: str = ""
    system: str = ""
    freq_hz: str = ""
    order: str = ""
    peak_db: str = ""
    strength_db: str = ""
    speed_band: str = ""
    relevance: str = ""


@dataclass
class ReportTemplateData:
    """All data needed to render a diagnostic PDF report."""

    title: str = ""
    run_datetime: str | None = None
    run_id: str | None = None
    duration_text: str | None = None
    start_time_utc: str | None = None
    end_time_utc: str | None = None
    sample_rate_hz: str | None = None
    tire_spec_text: str | None = None
    sample_count: int = 0
    sensor_count: int = 0
    sensor_locations: list[str] = field(default_factory=list)
    sensor_model: str | None = None
    firmware_version: str | None = None
    car: CarMeta = field(default_factory=CarMeta)
    observed: PatternEvidence = field(default_factory=PatternEvidence)
    system_cards: list[SystemFindingCard] = field(default_factory=list)
    next_steps: list[NextStep] = field(default_factory=list)
    data_trust: list[DataTrustItem] = field(default_factory=list)
    pattern_evidence: PatternEvidence = field(default_factory=PatternEvidence)
    peak_rows: list[PeakRow] = field(default_factory=list)
    version_marker: str = ""
    lang: str = "en"
    certainty_tier_key: str = "C"

    # Rendering context — pre-computed during analysis so the report
    # renderer never needs to read raw samples or call analysis code.
    findings: list[JsonObject] = field(default_factory=list)
    top_causes: list[JsonObject] = field(default_factory=list)
    sensor_intensity_by_location: list[JsonObject] = field(default_factory=list)
    location_hotspot_rows: list[JsonObject] = field(default_factory=list)
