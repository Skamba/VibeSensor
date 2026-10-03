"""Diagnostic finding aggregate plus small speed-band helpers."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, ClassVar

from vibesensor.domain.finding_evidence import FindingEvidence, Signature
from vibesensor.domain.finding_types import ConfidenceLevel, FindingKind, VibrationSource

if TYPE_CHECKING:
    from vibesensor.domain.location_hotspot import LocationHotspot
    from vibesensor.domain.order_match import OrderMatchObservation
    from vibesensor.domain.vibration_origin import VibrationOrigin

__all__ = [
    "Finding",
    "FindingEvidence",
    "FindingKind",
    "Signature",
    "VibrationSource",
    "speed_band_sort_key",
    "speed_bin_label",
]

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PeakClassificationView:
    """Minimal view of a finding's peak-specific classification fields."""

    classification: str = ""


def speed_bin_label(kmh: float, bin_width: int = 10) -> str:
    """Return a human-readable speed-bin label like ``'80-90 km/h'``."""
    if not math.isfinite(kmh) or kmh < 0:
        kmh = 0.0
    low = int(kmh // bin_width) * bin_width
    return f"{low}-{low + bin_width} km/h"


def speed_band_sort_key(label: str) -> int:
    """Return an integer sort key from a label like ``'80-90 km/h'``."""
    head = label.split(" ", 1)[0]
    parts = head.split("-", 1)
    try:
        return int(parts[0])
    except (ValueError, IndexError):
        return 0


@dataclass(frozen=True, slots=True)
class Finding:
    """Diagnostic conclusion or cause candidate from analysis."""

    finding_id: str = ""
    finding_key: str = ""
    suspected_source: VibrationSource = VibrationSource.UNKNOWN
    confidence: float | None = None
    frequency_hz: float | None = None
    order: str = ""
    severity: str = ""
    strongest_location: str | None = None
    strongest_speed_band: str | None = None
    peak_classification: str = ""
    kind: FindingKind | None = None
    dominant_phase: str | None = None

    ranking_score: float = 0.0
    dominance_ratio: float | None = None
    diffuse_excitation: bool = False
    weak_spatial_separation: bool = False
    vibration_strength_db: float | None = None
    cruise_fraction: float = 0.0
    phases_detected: tuple[str, ...] = ()
    matched_points: tuple[OrderMatchObservation, ...] = ()

    negligible_strength: bool = False
    evidence: FindingEvidence | None = None
    location: LocationHotspot | None = None
    origin: VibrationOrigin | None = None
    signatures: tuple[Signature, ...] = ()

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
                self,
                "kind",
                self.derive_kind_from_fields(self.finding_id, self.severity),
            )
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Finding.confidence must be in [0, 1], got {self.confidence}")
        if not (0.0 <= self.cruise_fraction <= 1.0):
            raise ValueError(
                f"Finding.cruise_fraction must be in [0, 1], got {self.cruise_fraction}"
            )
        if not math.isfinite(self.ranking_score):
            raise ValueError(f"Finding.ranking_score must be finite, got {self.ranking_score}")

    @staticmethod
    def derive_kind_from_fields(
        finding_id: str,
        severity: str,
        *,
        explicit_kind: str | None = None,
    ) -> FindingKind:
        """Derive ``FindingKind`` from explicit payload metadata or core fields."""
        if explicit_kind is not None:
            normed = explicit_kind.strip().lower()
            derived: FindingKind | None = None
            if normed == "reference":
                derived = FindingKind.REFERENCE
            elif normed in ("informational", "info"):
                derived = FindingKind.INFORMATIONAL
            elif normed == "diagnostic":
                derived = FindingKind.DIAGNOSTIC
            if derived is not None:
                if (
                    finding_id.strip().upper().startswith("REF_")
                    and derived is not FindingKind.REFERENCE
                ):
                    _LOGGER.warning(
                        "Finding %r has REF_ prefix but explicit kind %r overrides to %s",
                        finding_id,
                        explicit_kind,
                        derived,
                    )
                return derived
        if finding_id.strip().upper().startswith("REF_"):
            return FindingKind.REFERENCE
        if severity.strip().lower() == "info":
            return FindingKind.INFORMATIONAL
        return FindingKind.DIAGNOSTIC

    _MIN_SURFACING_CONFIDENCE: ClassVar[float] = 0.25
    _QUANTISE_STEP: ClassVar[float] = 0.02
    _PLACEHOLDER_SOURCES: ClassVar[frozenset[VibrationSource]] = frozenset(
        {VibrationSource.UNKNOWN_RESONANCE, VibrationSource.UNKNOWN},
    )
    _UNKNOWN_LOCATIONS: ClassVar[frozenset[str]] = frozenset(
        {"", "unknown", "not available", "n/a"},
    )

    def with_id(self, finding_id: str) -> Finding:
        """Return a copy of this finding with a new ``finding_id``."""
        return replace(self, finding_id=finding_id)

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
    def source_normalized(self) -> str:
        """Lower-cased, stripped suspected source for comparison."""
        return self.suspected_source.strip().lower()

    @property
    def signature_labels(self) -> tuple[str, ...]:
        return tuple(signature.label for signature in self.signatures)

    @property
    def effective_confidence(self) -> float:
        """Confidence normalised for computation (``None`` → ``0.0``)."""
        return float(self.confidence) if self.confidence is not None else 0.0

    @classmethod
    def is_unknown_location(cls, location: object) -> bool:
        """Whether a location value carries no actionable spatial information."""
        return str(location or "").strip().lower() in cls._UNKNOWN_LOCATIONS

    @property
    def is_actionable(self) -> bool:
        """Whether this finding identifies a meaningful mechanical component."""
        if self.suspected_source not in self._PLACEHOLDER_SOURCES:
            return True
        return not self.is_unknown_location(self.strongest_location)

    @property
    def should_surface(self) -> bool:
        """Whether this finding should appear in user-facing report output."""
        if self.is_reference:
            return False
        if self.is_informational:
            return False
        return self.effective_confidence >= self._MIN_SURFACING_CONFIDENCE

    @property
    def rank_key(self) -> tuple[float, float]:
        """Deterministic sort key for stable finding ordering."""
        step = self._QUANTISE_STEP
        quantised = round(self.effective_confidence / step) * step
        return (quantised, self.ranking_score)

    CONFIDENCE_HIGH_THRESHOLD: ClassVar[float] = 0.70
    CONFIDENCE_MEDIUM_THRESHOLD: ClassVar[float] = 0.40

    @staticmethod
    def classify_confidence(
        conf_0_to_1: float,
        *,
        negligible_strength: bool = False,
    ) -> ConfidenceLevel:
        """Strong >= 0.70, Moderate >= 0.40, else Weak; negligible strength caps at Moderate."""
        conf = float(conf_0_to_1) if math.isfinite(conf_0_to_1) else 0.0
        if conf >= Finding.CONFIDENCE_HIGH_THRESHOLD:
            return ConfidenceLevel.MODERATE if negligible_strength else ConfidenceLevel.STRONG
        if conf >= Finding.CONFIDENCE_MEDIUM_THRESHOLD:
            return ConfidenceLevel.MODERATE
        return ConfidenceLevel.WEAK

    @property
    def confidence_level(self) -> ConfidenceLevel:
        """Action-defined confidence level shown to users (never a percentage)."""
        return self.classify_confidence(
            self.effective_confidence, negligible_strength=self.negligible_strength
        )

    _ORDER_CODES: ClassVar[dict[str, str]] = {
        "wheel_1x": "T1",
        "wheel_2x": "T2",
        "driveshaft_1x": "P1",
        "driveshaft_2x": "P2",
        "engine_1x": "E1",
        "engine_2x": "E2",
    }

    @property
    def order_code(self) -> str | None:
        """Workshop order label (T1/T2 tire, P1/P2 propshaft, E1/E2 engine), if order-tracked."""
        return self._ORDER_CODES.get(self.finding_key.strip().lower())

    @property
    def phase_adjusted_score(self) -> float:
        """Phase-aware ranking score used for top-cause selection."""
        cf = self.cruise_fraction
        return self.effective_confidence * (0.85 + 0.15 * cf)

    def is_stronger_than(self, other: Finding) -> bool:
        """Whether this finding ranks higher than *other*."""
        return self.phase_adjusted_score > other.phase_adjusted_score

    @property
    def peaks(self) -> PeakClassificationView:
        """Return the current peak-classification view used by report serializers."""
        return PeakClassificationView(classification=self.peak_classification)

    def with_strength_band(self, strength_band_key: str | None) -> Finding:
        """Return a copy that knows whether the run-wide vibration strength was negligible."""
        negligible = (strength_band_key or "").strip().lower() == "negligible"
        return replace(self, negligible_strength=negligible)
