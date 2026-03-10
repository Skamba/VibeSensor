"""Intermediate data model for the diagnostic PDF report.

Pure data-class definitions consumed by the Canvas-based PDF renderer.
The ``map_summary()`` builder that populates these classes lives in
``vibesensor.analysis.report_mapping.pipeline`` so that the report package
stays renderer-only with zero analysis imports.
"""

from __future__ import annotations

__all__ = [
    "CarMeta",
    "DataTrustItem",
    "NextStep",
    "ObservedSignature",
    "PartSuggestion",
    "PatternEvidence",
    "PeakRow",
    "ReportTemplateData",
    "SystemFindingCard",
]

import dataclasses
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Self

from ..json_types import JsonObject, is_json_array, is_json_object


@lru_cache(maxsize=16)
def _valid_field_names(cls: type) -> frozenset[str]:
    """Return declared dataclass field names for *cls* (cached per class)."""
    return frozenset(f.name for f in dataclasses.fields(cls))


def _filter_fields(cls: type, raw: JsonObject) -> dict[str, object]:
    """Keep only keys that match declared dataclass fields.

    All dataclass fields in this module use defaults so that ``from_dict()``
    tolerates missing keys when reconstructing from older persisted data.
    """
    valid = _valid_field_names(cls)
    return {k: v for k, v in raw.items() if k in valid}


class _FromDictMixin:
    """Shared ``from_dict()`` class-method for simple report dataclasses.

    Subclasses that need custom deserialization (e.g. nested dataclass
    fields) should override ``from_dict`` directly.
    """

    @classmethod
    def from_dict(cls, d: object) -> Self:
        if not is_json_object(d):
            return cls()
        return cls(**_filter_fields(cls, d))


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class CarMeta(_FromDictMixin):
    """Vehicle identification metadata (name, type) extracted from the report run."""

    name: str | None = None
    car_type: str | None = None


@dataclass
class ObservedSignature(_FromDictMixin):
    """The dominant vibration signature observed during the run."""

    primary_system: str | None = None
    strongest_sensor_location: str | None = None
    speed_band: str | None = None
    strength_label: str | None = None
    strength_peak_db: float | None = None
    certainty_label: str | None = None
    certainty_pct: str | None = None
    certainty_reason: str | None = None


@dataclass
class PartSuggestion:
    """A suggested replacement part associated with a diagnostic finding."""

    name: str = ""

    @classmethod
    def from_dict(cls, d: object) -> Self:
        if isinstance(d, str):
            return cls(name=d)
        if not is_json_object(d):
            return cls(name=str(d))
        return cls(**_filter_fields(cls, d))


@dataclass
class SystemFindingCard:
    """A per-system diagnostic finding card for the report, with location and parts."""

    system_name: str = ""
    strongest_location: str | None = None
    pattern_summary: str | None = None
    parts: list[PartSuggestion] = field(default_factory=list)
    tone: str = "neutral"

    @classmethod
    def from_dict(cls, d: object) -> Self:
        if not is_json_object(d):
            return cls()
        filtered = _filter_fields(cls, d)
        parts_raw = d.get("parts")
        filtered["parts"] = (
            [PartSuggestion.from_dict(part) for part in parts_raw]
            if is_json_array(parts_raw)
            else []
        )
        return cls(**filtered)


@dataclass
class NextStep(_FromDictMixin):
    """A recommended diagnostic next step (action, rationale, ETA)."""

    action: str = ""
    why: str | None = None
    confirm: str | None = None
    falsify: str | None = None
    eta: str | None = None


@dataclass
class DataTrustItem(_FromDictMixin):
    """A single data-quality check result (pass/warn/fail with detail).

    ``state`` defaults to ``"warn"`` so that data quality items reconstructed
    from older persisted data (where the ``state`` key may be absent) are
    treated conservatively rather than silently marked as passing.
    """

    check: str = ""
    state: str = "warn"
    detail: str | None = None


@dataclass
class PatternEvidence(_FromDictMixin):
    """Evidence summary for the dominant vibration pattern from post-analysis."""

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

    @classmethod
    def from_dict(cls, d: object) -> Self:
        """Reconstruct from a persisted dict, guarding ``matched_systems`` against ``None``.

        Older persisted records may omit ``matched_systems`` or store ``null``,
        which would bypass the ``default_factory`` and set the field to ``None``.
        This override coerces any non-list value back to an empty list so the
        renderer can safely call ``', '.join(ev.matched_systems)``.
        """
        if not is_json_object(d):
            return cls()
        filtered = _filter_fields(cls, d)
        if not is_json_array(filtered.get("matched_systems")):
            filtered["matched_systems"] = []
        return cls(**filtered)


@dataclass
class PeakRow(_FromDictMixin):
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
    observed: ObservedSignature = field(default_factory=ObservedSignature)
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

    @classmethod
    def from_dict(cls, d: object) -> ReportTemplateData:
        """Reconstruct a :class:`ReportTemplateData` from a persisted dict."""
        if not is_json_object(d):
            return cls()
        filtered = _filter_fields(cls, d)
        filtered["car"] = CarMeta.from_dict(d.get("car"))
        filtered["observed"] = ObservedSignature.from_dict(d.get("observed"))
        system_cards_raw = d.get("system_cards")
        next_steps_raw = d.get("next_steps")
        data_trust_raw = d.get("data_trust")
        peak_rows_raw = d.get("peak_rows")
        filtered["system_cards"] = (
            [SystemFindingCard.from_dict(card) for card in system_cards_raw]
            if is_json_array(system_cards_raw)
            else []
        )
        filtered["next_steps"] = (
            [NextStep.from_dict(step) for step in next_steps_raw]
            if is_json_array(next_steps_raw)
            else []
        )
        filtered["data_trust"] = (
            [DataTrustItem.from_dict(item) for item in data_trust_raw]
            if is_json_array(data_trust_raw)
            else []
        )
        filtered["pattern_evidence"] = PatternEvidence.from_dict(d.get("pattern_evidence"))
        filtered["peak_rows"] = (
            [PeakRow.from_dict(row) for row in peak_rows_raw]
            if is_json_array(peak_rows_raw)
            else []
        )
        return cls(**filtered)
