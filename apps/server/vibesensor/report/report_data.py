"""Intermediate data model for the diagnostic PDF report.

Pure data-class definitions consumed by the Canvas-based PDF renderer.
The ``map_summary()`` builder that populates these classes lives in
``vibesensor.analysis.report_data_builder`` so that the report package
stays renderer-only with zero analysis imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class CarMeta:
    name: str | None = None
    car_type: str | None = None


@dataclass
class ObservedSignature:
    primary_system: str | None = None
    strongest_sensor_location: str | None = None
    speed_band: str | None = None
    phase: str | None = None
    strength_label: str | None = None
    strength_peak_db: float | None = None
    certainty_label: str | None = None
    certainty_pct: str | None = None
    certainty_reason: str | None = None


@dataclass
class PartSuggestion:
    name: str
    why_shown: str | None = None


@dataclass
class SystemFindingCard:
    system_name: str
    strongest_location: str | None = None
    pattern_summary: str | None = None
    parts: list[PartSuggestion] = field(default_factory=list)
    tone: str = "neutral"


@dataclass
class NextStep:
    action: str = ""
    why: str | None = None
    rank: int = 999
    speed_band: str | None = None
    confirm: str | None = None
    falsify: str | None = None
    eta: str | None = None


@dataclass
class DataTrustItem:
    check: str
    state: str  # "pass" or "warn"
    detail: str | None = None


@dataclass
class PatternEvidence:
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
    rank: str
    system: str
    freq_hz: str
    order: str
    peak_db: str
    strength_db: str
    speed_band: str
    relevance: str


@dataclass
class ReportTemplateData:
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
    observed: ObservedSignature = field(default_factory=ObservedSignature)
    system_cards: list[SystemFindingCard] = field(default_factory=list)
    next_steps: list[NextStep] = field(default_factory=list)
    data_trust: list[DataTrustItem] = field(default_factory=list)
    pattern_evidence: PatternEvidence = field(default_factory=PatternEvidence)
    peak_rows: list[PeakRow] = field(default_factory=list)
    phase_info: dict | None = None
    version_marker: str = ""
    lang: str = "en"
    certainty_tier_key: str = "C"

    # Rendering context — pre-computed during analysis so the report
    # renderer never needs to read raw samples or call analysis code.
    findings: list[dict] = field(default_factory=list)
    top_causes: list[dict] = field(default_factory=list)
    sensor_intensity_by_location: list[dict] = field(default_factory=list)
    location_hotspot_rows: list[dict] = field(default_factory=list)
