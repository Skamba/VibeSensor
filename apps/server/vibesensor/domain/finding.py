"""One diagnostic conclusion or cause candidate from analysis.

``Finding`` is the richest domain object.  It owns classification
(reference / informational / diagnostic), actionability, surfacing
decisions, confidence normalisation, deterministic ranking, and
phase-adjusted scoring.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import ClassVar, TypedDict

__all__ = [
    "ConfidenceTier",
    "Finding",
    "FindingKind",
    "PhaseEvidence",
    "SpeedBand",
    "VibrationSource",
]


# ── Enums ─────────────────────────────────────────────────────────────────────


class VibrationSource(StrEnum):
    """Canonical mechanical vibration source categories.

    Compares equal to plain strings (``VibrationSource.ENGINE == "engine"``),
    so serialised payloads and dict-keyed lookups work without migration.
    """

    WHEEL_TIRE = "wheel/tire"
    DRIVELINE = "driveline"
    ENGINE = "engine"
    BODY_RESONANCE = "body resonance"
    TRANSIENT_IMPACT = "transient_impact"
    BASELINE_NOISE = "baseline_noise"
    UNKNOWN_RESONANCE = "unknown_resonance"
    UNKNOWN = "unknown"


class FindingKind(StrEnum):
    """Classification category of a diagnostic finding."""

    REFERENCE = "reference"
    INFORMATIONAL = "informational"
    DIAGNOSTIC = "diagnostic"


class ConfidenceTier(StrEnum):
    """Confidence classification tier for findings."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# ── Value objects ─────────────────────────────────────────────────────────────


class PhaseEvidence(TypedDict, total=False):
    """Phase context evidence attached to a finding (serialization shape)."""

    cruise_fraction: float
    phases_detected: list[str]


def _parse_cruise_fraction(raw: dict[str, object] | None) -> float:
    """Extract cruise_fraction from a raw phase_evidence dict."""
    if not isinstance(raw, dict):
        return 0.0
    try:
        return float(raw.get("cruise_fraction", 0.0))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


@dataclass(frozen=True, slots=True)
class SpeedBand:
    """A speed-range bin used for amplitude-weighted matching.

    Encapsulates the encode/decode round-trip that previously lived in
    ``_speed_bin_label`` / ``_speed_bin_sort_key`` helper functions.
    """

    low_kmh: int
    high_kmh: int

    @classmethod
    def from_speed_kmh(cls, kmh: float, bin_width: int = 10) -> SpeedBand:
        """Create a speed band from a speed value."""
        if not math.isfinite(kmh) or kmh < 0:
            kmh = 0.0
        low = int(kmh // bin_width) * bin_width
        return cls(low_kmh=low, high_kmh=low + bin_width)

    @classmethod
    def from_label(cls, label: str) -> SpeedBand | None:
        """Parse a label like ``'80-100 km/h'`` back to a SpeedBand."""
        head = label.split(" ", 1)[0]
        parts = head.split("-", 1)
        try:
            return cls(low_kmh=int(parts[0]), high_kmh=int(parts[1]))
        except (ValueError, IndexError):
            return None

    @property
    def label(self) -> str:
        """Human-readable speed range label."""
        return f"{self.low_kmh}-{self.high_kmh} km/h"

    @property
    def sort_key(self) -> int:
        """Integer sort key for ordering speed bands."""
        return self.low_kmh




@dataclass(frozen=True, slots=True)
class Finding:
    """One diagnostic conclusion or cause candidate from analysis.

    This is the first-class domain object for a finding.
    ``FindingPayload`` (the TypedDict in ``analysis._types``) remains as
    the serialization/payload shape; use :meth:`from_payload` to create a
    domain ``Finding`` from a payload dict.

    ``finding_id`` is assigned during finalization (``F001``, ``F002``, …).
    ``suspected_source`` identifies the mechanical component suspected of
    causing the vibration (e.g. ``"wheel_bearing"``, ``"driveshaft"``).

    Classification
    --------------
    Findings are partitioned into three categories:

    * **Reference** findings (``REF_*``) carry data-quality metadata.
    * **Informational** findings carry context without a specific diagnosis.
    * **Diagnostic** findings identify a suspected cause with a confidence.

    Actionability and surfacing
    ---------------------------
    :attr:`is_actionable` indicates whether the finding identifies a
    meaningful component (not a placeholder "unknown" source).
    :attr:`should_surface` indicates whether the finding is suitable for
    display to the end-user in a report or UI.
    """

    finding_id: str = ""
    suspected_source: VibrationSource = VibrationSource.UNKNOWN
    confidence: float | None = None
    frequency_hz: float | None = None
    order: str = ""
    severity: str = ""
    strongest_location: str | None = None
    strongest_speed_band: SpeedBand | None = None
    peak_classification: str = ""
    kind: FindingKind | None = None

    # Evidence and ranking fields ------------------------------------------
    ranking_score: float = 0.0
    dominance_ratio: float | None = None
    diffuse_excitation: bool = False
    weak_spatial_separation: bool = False
    vibration_strength_db: float | None = None
    cruise_fraction: float = 0.0

    def __post_init__(self) -> None:
        """Auto-derive ``kind`` and validate invariants."""
        # Coerce str → VibrationSource for convenience (tests, direct construction).
        src = self.suspected_source
        if not isinstance(src, VibrationSource):
            normed = str(src).strip().lower()
            try:
                object.__setattr__(self, "suspected_source", VibrationSource(normed))
            except ValueError:
                object.__setattr__(self, "suspected_source", VibrationSource.UNKNOWN)
        if self.kind is None:
            object.__setattr__(
                self, "kind", self._kind_from_fields(self.finding_id, self.severity),
            )
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Finding.confidence must be in [0, 1], got {self.confidence}")
        # Coerce str → SpeedBand for convenience.
        sb = self.strongest_speed_band
        if isinstance(sb, str):
            object.__setattr__(self, "strongest_speed_band", SpeedBand.from_label(sb))

    @staticmethod
    def _kind_from_fields(finding_id: str, severity: str) -> FindingKind:
        if finding_id.strip().upper().startswith("REF_"):
            return FindingKind.REFERENCE
        if severity.strip().lower() == "info":
            return FindingKind.INFORMATIONAL
        return FindingKind.DIAGNOSTIC

    # Domain constants -----------------------------------------------------

    _MIN_SURFACING_CONFIDENCE: ClassVar[float] = 0.25
    """Findings below this confidence are not surfaced in user-facing output."""

    _QUANTISE_STEP: ClassVar[float] = 0.02
    """Confidence quantisation step to prevent jitter-driven reordering."""

    _PLACEHOLDER_SOURCES: ClassVar[frozenset[VibrationSource]] = frozenset(
        {VibrationSource.UNKNOWN_RESONANCE, VibrationSource.UNKNOWN},
    )
    """Suspected sources that are considered placeholder / unresolved."""

    _UNKNOWN_LOCATIONS: ClassVar[frozenset[str]] = frozenset(
        {"", "unknown", "not available", "n/a"},
    )
    """Location values that carry no actionable spatial information."""

    # -- factories ---------------------------------------------------------

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> Finding:
        """Create a domain Finding from a ``FindingPayload`` dict.

        Extracts the subset of fields that the domain object cares about,
        ignoring serialization-only keys present in the full payload.

        Reads ``suspected_source`` with fallback to ``source`` for backward
        compatibility with ``TopCause`` dicts that use the ``source`` key.
        """

        def _str(key: str, *fallback_keys: str) -> str:
            v = payload.get(key)
            if v is None:
                for fk in fallback_keys:
                    v = payload.get(fk)
                    if v is not None:
                        break
            return str(v) if v is not None else ""

        conf_raw = payload.get("confidence")
        confidence: float | None = None
        if conf_raw is not None:
            try:
                confidence = float(conf_raw)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                pass

        freq_raw = payload.get("frequency_hz") or payload.get("frequency_hz_or_order")
        frequency_hz: float | None = None
        if freq_raw is not None:
            try:
                frequency_hz = float(freq_raw)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                pass

        loc = payload.get("strongest_location")
        band = payload.get("strongest_speed_band")

        # Evidence / ranking fields
        ranking_raw = payload.get("ranking_score")
        ranking_score = 0.0
        if ranking_raw is not None:
            try:
                ranking_score = float(ranking_raw)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                pass

        dominance_raw = payload.get("dominance_ratio")
        dominance_ratio: float | None = None
        if dominance_raw is not None:
            try:
                dominance_ratio = float(dominance_raw)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                pass

        phase_ev = payload.get("phase_evidence")
        cruise_fraction = _parse_cruise_fraction(
            phase_ev if isinstance(phase_ev, dict) else None,
        )

        # Extract vibration_strength_db from evidence_metrics
        vib_db: float | None = None
        ev_metrics = payload.get("evidence_metrics")
        if isinstance(ev_metrics, dict):
            raw_db = ev_metrics.get("vibration_strength_db")
            if raw_db is not None:
                try:
                    vib_db = float(raw_db)
                except (TypeError, ValueError):
                    pass

        finding_id = _str("finding_id")
        severity = _str("severity")
        raw_source = _str("suspected_source", "source").strip().lower()
        try:
            source = VibrationSource(raw_source)
        except ValueError:
            source = VibrationSource.UNKNOWN

        # Derive kind from explicit finding_type or infer from fields
        kind = cls._derive_kind(payload, finding_id=finding_id, severity=severity)

        return cls(
            finding_id=finding_id,
            suspected_source=source,
            confidence=confidence,
            frequency_hz=frequency_hz,
            order=_str("order"),
            severity=severity,
            strongest_location=str(loc) if loc is not None else None,
            strongest_speed_band=SpeedBand.from_label(str(band)) if band is not None else None,
            peak_classification=_str("peak_classification"),
            kind=kind,
            ranking_score=ranking_score,
            dominance_ratio=dominance_ratio,
            diffuse_excitation=bool(payload.get("diffuse_excitation", False)),
            weak_spatial_separation=bool(payload.get("weak_spatial_separation", False)),
            vibration_strength_db=vib_db,
            cruise_fraction=cruise_fraction,
        )

    @staticmethod
    def _derive_kind(
        payload: Mapping[str, object],
        *,
        finding_id: str,
        severity: str,
    ) -> FindingKind:
        """Derive FindingKind from explicit ``finding_type`` or infer from fields."""
        explicit = payload.get("finding_kind") or payload.get("finding_type")
        if isinstance(explicit, str):
            normed = explicit.strip().lower()
            if normed == "reference":
                return FindingKind.REFERENCE
            if normed in ("informational", "info"):
                return FindingKind.INFORMATIONAL
            if normed == "diagnostic":
                return FindingKind.DIAGNOSTIC
        # Fall back to existing string-pattern inference
        if finding_id.strip().upper().startswith("REF_"):
            return FindingKind.REFERENCE
        if severity.strip().lower() == "info":
            return FindingKind.INFORMATIONAL
        return FindingKind.DIAGNOSTIC

    # -- identity mutation (frozen ⇒ returns new instance) -----------------

    def with_id(self, finding_id: str) -> Finding:
        """Return a copy of this finding with a new ``finding_id``."""
        return replace(self, finding_id=finding_id)

    # -- classification ----------------------------------------------------

    @property
    def is_reference(self) -> bool:
        """Whether this is a reference-data finding (``REF_*``)."""
        return self.kind is FindingKind.REFERENCE

    @property
    def is_informational(self) -> bool:
        return self.kind is FindingKind.INFORMATIONAL

    @property
    def is_diagnostic(self) -> bool:
        return self.kind is FindingKind.DIAGNOSTIC

    @property
    def confidence_pct(self) -> int | None:
        """Confidence as integer percentage, or None if unset."""
        if self.confidence is None:
            return None
        return round(self.confidence * 100)

    @property
    def source_normalized(self) -> str:
        """Lower-cased, stripped suspected source for comparison."""
        return self.suspected_source.strip().lower()

    # -- effective confidence -----------------------------------------------

    @property
    def effective_confidence(self) -> float:
        """Confidence normalised for computation (``None`` → ``0.0``)."""
        return float(self.confidence) if self.confidence is not None else 0.0

    # -- actionability / surfacing ------------------------------------------

    @classmethod
    def is_unknown_location(cls, location: object) -> bool:
        """Whether a location value carries no actionable spatial information."""
        return str(location or "").strip().lower() in cls._UNKNOWN_LOCATIONS

    @property
    def is_actionable(self) -> bool:
        """Whether this finding identifies a meaningful mechanical component.

        A finding is actionable when its suspected source is not a
        placeholder value, **or** when it has a specific (non-unknown)
        location even if the source is a placeholder.
        """
        if self.suspected_source not in self._PLACEHOLDER_SOURCES:
            return True
        return not self.is_unknown_location(self.strongest_location)

    @property
    def should_surface(self) -> bool:
        """Whether this finding should appear in user-facing report output.

        Filters out reference findings, informational findings, and those
        below the minimum confidence floor.
        """
        if self.is_reference:
            return False
        if self.is_informational:
            return False
        return self.effective_confidence >= self._MIN_SURFACING_CONFIDENCE

    # -- ranking / comparison ------------------------------------------------

    @property
    def rank_key(self) -> tuple[float, float]:
        """Deterministic sort key for stable finding ordering.

        Confidence is quantised so tiny timing/noise jitter does not
        reshuffle otherwise-equivalent findings, leaving the explicit
        ranking score to break ties consistently.
        """
        step = self._QUANTISE_STEP
        quantised = round(self.effective_confidence / step) * step
        return (quantised, self.ranking_score)

    # -- confidence classification ------------------------------------------

    CONFIDENCE_HIGH_THRESHOLD: ClassVar[float] = 0.70
    CONFIDENCE_MEDIUM_THRESHOLD: ClassVar[float] = 0.40

    @property
    def confidence_tier(self) -> ConfidenceTier:
        """Classify confidence into HIGH / MEDIUM / LOW tier."""
        conf = self.effective_confidence
        if conf >= self.CONFIDENCE_HIGH_THRESHOLD:
            return ConfidenceTier.HIGH
        if conf >= self.CONFIDENCE_MEDIUM_THRESHOLD:
            return ConfidenceTier.MEDIUM
        return ConfidenceTier.LOW

    @property
    def phase_adjusted_score(self) -> float:
        """Phase-aware ranking score used for top-cause selection.

        Cruise-heavy findings receive a modest score boost because
        constant-speed conditions produce the most reliable spectral
        evidence.
        """
        cf = self.cruise_fraction
        return self.effective_confidence * (0.85 + 0.15 * cf)

    def is_stronger_than(self, other: Finding) -> bool:
        """Whether this finding ranks higher than *other*."""
        return self.phase_adjusted_score > other.phase_adjusted_score
