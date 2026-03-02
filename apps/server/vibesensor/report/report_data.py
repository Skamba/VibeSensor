"""Intermediate data model for the diagnostic PDF report.

Pure data-class definitions consumed by the Canvas-based PDF renderer.
The ``map_summary()`` builder that populates these classes lives in
``vibesensor.analysis.report_data_builder`` so that the report package
stays renderer-only with zero analysis imports.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any


def _filter_fields(cls: type, raw: dict[str, Any]) -> dict[str, Any]:
    """Keep only keys that match declared dataclass fields.

    All dataclass fields in this module use defaults so that ``from_dict()``
    tolerates missing keys when reconstructing from older persisted data.
    """
    valid = {f.name for f in dataclasses.fields(cls)}
    return {k: v for k, v in raw.items() if k in valid}


class _FromDictMixin:
    """Shared ``from_dict()`` class-method for simple report dataclasses.

    Subclasses that need custom deserialization (e.g. nested dataclass
    fields) should override ``from_dict`` directly.
    """

    @classmethod
    def from_dict(cls, d: Any):  # type: ignore[misc]
        if not isinstance(d, dict):
            return cls()
        return cls(**_filter_fields(cls, d))


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class CarMeta(_FromDictMixin):
    name: str | None = None
    car_type: str | None = None


@dataclass
class ObservedSignature(_FromDictMixin):
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
    name: str = ""
    why_shown: str | None = None

    @classmethod
    def from_dict(cls, d: Any) -> PartSuggestion:
        if isinstance(d, str):
            return cls(name=d)
        if not isinstance(d, dict):
            return cls(name=str(d))
        return cls(**_filter_fields(cls, d))


@dataclass
class SystemFindingCard:
    system_name: str = ""
    strongest_location: str | None = None
    pattern_summary: str | None = None
    parts: list[PartSuggestion] = field(default_factory=list)
    tone: str = "neutral"

    @classmethod
    def from_dict(cls, d: Any) -> SystemFindingCard:
        if not isinstance(d, dict):
            return cls()
        filtered = _filter_fields(cls, d)
        filtered["parts"] = [PartSuggestion.from_dict(p) for p in (d.get("parts") or [])]
        return cls(**filtered)


@dataclass
class NextStep(_FromDictMixin):
    action: str = ""
    why: str | None = None
    rank: int = 999
    speed_band: str | None = None
    confirm: str | None = None
    falsify: str | None = None
    eta: str | None = None


@dataclass
class DataTrustItem(_FromDictMixin):
    check: str = ""
    state: str = "pass"
    detail: str | None = None


@dataclass
class PatternEvidence(_FromDictMixin):
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
class PeakRow(_FromDictMixin):
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

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ReportTemplateData:
        """Reconstruct a :class:`ReportTemplateData` from a persisted dict."""
        filtered = _filter_fields(cls, d)
        filtered["car"] = CarMeta.from_dict(d.get("car"))
        filtered["observed"] = ObservedSignature.from_dict(d.get("observed"))
        filtered["system_cards"] = [
            SystemFindingCard.from_dict(c) for c in d.get("system_cards", [])
        ]
        filtered["next_steps"] = [NextStep.from_dict(s) for s in d.get("next_steps", [])]
        filtered["data_trust"] = [DataTrustItem.from_dict(t) for t in d.get("data_trust", [])]
        filtered["pattern_evidence"] = PatternEvidence.from_dict(d.get("pattern_evidence"))
        filtered["peak_rows"] = [PeakRow.from_dict(r) for r in d.get("peak_rows", [])]
        return cls(**filtered)
