"""Panel-level presentation models for PDF report assembly."""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "DataTrustItem",
    "NextStep",
    "PartSuggestion",
    "PatternEvidence",
    "SystemFindingCard",
]


@dataclass
class PartSuggestion:
    """A suggested replacement part associated with a diagnostic finding."""

    name: str = ""


@dataclass
class SystemFindingCard:
    """A per-system diagnostic finding card for the report, with location and parts."""

    system_name: str = ""
    status_label: str | None = None
    strongest_location: str | None = None
    pattern_summary: str | None = None
    parts: list[PartSuggestion] = field(default_factory=list)
    tone: str = "neutral"


@dataclass
class NextStep:
    """A recommended diagnostic next step and its supporting detail."""

    action: str = ""
    why: str | None = None
    confirm: str | None = None
    falsify: str | None = None
    eta: str | None = None


@dataclass
class DataTrustItem:
    """A single data-quality check result (pass/warn/fail with detail)."""

    check: str = ""
    state: str = "warn"
    detail: str | None = None


@dataclass
class PatternEvidence:
    """Observed-signature and evidence summary block for the report template."""

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
