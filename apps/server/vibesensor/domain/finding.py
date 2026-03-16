"""One diagnostic conclusion or cause candidate from analysis.

``Finding`` is the richest domain object.  It owns classification
(reference / informational / diagnostic), actionability, surfacing
decisions, confidence normalisation, deterministic ranking, and
phase-adjusted scoring.

Optionally carries structured domain value objects for evidence
(:class:`FindingEvidence`), spatial localisation
(:class:`LocationHotspot`), and confidence rationale
(:class:`ConfidenceAssessment`).
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from vibesensor.domain.confidence_assessment import ConfidenceAssessment
    from vibesensor.domain.location_hotspot import LocationHotspot
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


# ── Speed-band helpers ────────────────────────────────────────────────────────


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


# ── FindingEvidence ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class FindingEvidence:
    """Structured support for a finding — evidence quality and consistency."""

    match_rate: float = 0.0
    snr_db: float | None = None
    presence_ratio: float = 0.0
    burstiness: float = 0.0
    spatial_concentration: float = 0.0
    frequency_correlation: float = 0.0
    speed_uniformity: float = 0.0
    spatial_uniformity: float = 0.0
    phase_confidences: tuple[tuple[str, float], ...] = ()
    vibration_strength_db: float | None = None

    _STRONG_MATCH_RATE: ClassVar[float] = 0.70
    _STRONG_SNR_DB: ClassVar[float] = 6.0
    _CONSISTENT_BURSTINESS: ClassVar[float] = 0.3
    _CONSISTENT_PRESENCE: ClassVar[float] = 0.5
    _WELL_LOCALIZED_CONCENTRATION: ClassVar[float] = 0.6

    @property
    def is_strong(self) -> bool:
        """Evidence is strong enough to support a diagnostic conclusion."""
        return (
            self.match_rate >= self._STRONG_MATCH_RATE
            and self.snr_db is not None
            and self.snr_db >= self._STRONG_SNR_DB
        )

    @property
    def is_consistent(self) -> bool:
        """Evidence is temporally consistent (not bursty/intermittent)."""
        return (
            self.burstiness < self._CONSISTENT_BURSTINESS
            and self.presence_ratio >= self._CONSISTENT_PRESENCE
        )

    @property
    def is_well_localized(self) -> bool:
        """Evidence is spatially concentrated, not diffuse."""
        return self.spatial_concentration >= self._WELL_LOCALIZED_CONCENTRATION

    @classmethod
    def from_metrics(cls, d: Mapping[str, object]) -> FindingEvidence:
        """Construct from a ``FindingEvidenceMetrics`` dict using canonical keys.

        Legacy alias handling (e.g. ``snr_ratio`` → ``snr_db``) is NOT done
        here — boundary callers must pre-normalize before calling this factory.
        """

        def _float(key: str) -> float:
            raw = d.get(key)
            if raw is None:
                return 0.0
            try:
                return float(raw)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return 0.0

        def _float_or_none(key: str) -> float | None:
            raw = d.get(key)
            if raw is None:
                return None
            try:
                return float(raw)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None

        phase_conf = d.get("per_phase_confidence")
        phase_items: tuple[tuple[str, float], ...] = ()
        if isinstance(phase_conf, dict):
            phase_items = tuple(
                (str(k), float(v))
                for k, v in sorted(phase_conf.items())
                if isinstance(v, (int, float))
            )

        return cls(
            match_rate=_float("match_rate"),
            snr_db=_float_or_none("snr_db"),
            presence_ratio=_float("presence_ratio"),
            burstiness=_float("burstiness"),
            spatial_concentration=_float("spatial_concentration"),
            frequency_correlation=_float("frequency_correlation"),
            speed_uniformity=_float("speed_uniformity"),
            spatial_uniformity=_float("spatial_uniformity"),
            phase_confidences=phase_items,
            vibration_strength_db=_float_or_none("vibration_strength_db"),
        )


# ── Signature ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Signature:
    """A meaningful vibration pattern label attached to a finding."""

    key: str
    source: VibrationSource
    label: str
    observation_ids: tuple[str, ...] = ()
    support_score: float = 0.0

    @property
    def observation_count(self) -> int:
        return len(self.observation_ids)

    @property
    def is_consistent(self) -> bool:
        return len(self.observation_ids) > 0 and self.support_score > 0.0

    @classmethod
    def from_label(
        cls,
        label: str,
        *,
        source: VibrationSource,
        observation_ids: tuple[str, ...] = (),
        support_score: float = 0.0,
    ) -> Signature:
        key = label.strip().lower().replace("/", "_").replace(" ", "_") or "unknown_signature"
        return cls(
            key=key,
            source=source,
            label=label.strip() or "unknown signature",
            observation_ids=observation_ids,
            support_score=support_score,
        )


# ── Finding ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Finding:
    """One diagnostic conclusion or cause candidate from analysis.

    This is the first-class domain object for a finding.
    ``FindingPayload`` (the TypedDict in ``analysis._types``) remains as
    the serialization/payload shape; use
    :func:`~vibesensor.shared.boundaries.finding.finding_from_payload` to create
    a domain ``Finding`` from a payload dict.

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

    # Evidence and ranking fields ------------------------------------------
    ranking_score: float = 0.0
    dominance_ratio: float | None = None
    diffuse_excitation: bool = False
    weak_spatial_separation: bool = False
    vibration_strength_db: float | None = None
    cruise_fraction: float = 0.0

    # Structured domain value objects (optional — populated when available)
    evidence: FindingEvidence | None = None
    location: LocationHotspot | None = None
    confidence_assessment: ConfidenceAssessment | None = None
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
        """Single derivation path for FindingKind.

        Checks ``explicit_kind`` first (from payload ``finding_kind`` /
        ``finding_type`` fields), then falls back to string-pattern
        inference from ``finding_id`` and ``severity``.
        """
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

    @property
    def signature_labels(self) -> tuple[str, ...]:
        return tuple(signature.label for signature in self.signatures)

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

    # -- confidence thresholds ------------------------------------------------

    CONFIDENCE_HIGH_THRESHOLD: ClassVar[float] = 0.70
    CONFIDENCE_MEDIUM_THRESHOLD: ClassVar[float] = 0.40

    # -- confidence presentation (domain-owned) ----------------------------

    @staticmethod
    def classify_confidence(
        conf_0_to_1: float,
        *,
        strength_band_key: str | None = None,
    ) -> tuple[str, str, str]:
        """Classify a 0–1 confidence into ``(label_key, tone, pct_text)``.

        Pure classification logic shared by the instance method
        :meth:`confidence_label` and by boundary helpers that operate on
        raw confidence values without a full ``Finding`` object.

        * **HIGH** (≥ 0.70): ``("CONFIDENCE_HIGH", "success", "…%")``
        * **MEDIUM** (0.40–0.70): ``("CONFIDENCE_MEDIUM", "warn", "…%")``
        * **LOW** (< 0.40): ``("CONFIDENCE_LOW", "neutral", "…%")``

        When *strength_band_key* is ``"negligible"`` and the raw tier
        would be HIGH, the result is downgraded to MEDIUM.
        """
        conf = float(conf_0_to_1) if math.isfinite(conf_0_to_1) else 0.0
        pct = max(0.0, min(100.0, conf * 100.0))
        pct_text = f"{pct:.0f}%"
        if conf >= Finding.CONFIDENCE_HIGH_THRESHOLD:
            label_key, tone = "CONFIDENCE_HIGH", "success"
        elif conf >= Finding.CONFIDENCE_MEDIUM_THRESHOLD:
            label_key, tone = "CONFIDENCE_MEDIUM", "warn"
        else:
            label_key, tone = "CONFIDENCE_LOW", "neutral"
        if (
            strength_band_key or ""
        ).strip().lower() == "negligible" and label_key == "CONFIDENCE_HIGH":
            label_key, tone = "CONFIDENCE_MEDIUM", "warn"
        return label_key, tone, pct_text

    def confidence_label(
        self,
        *,
        strength_band_key: str | None = None,
    ) -> tuple[str, str, str]:
        """Return ``(label_key, tone, pct_text)`` for this finding's confidence.

        Convenience wrapper around :meth:`classify_confidence` that uses
        the finding's own :attr:`effective_confidence`.
        """
        return self.classify_confidence(
            self.effective_confidence,
            strength_band_key=strength_band_key,
        )

    @property
    def confidence_label_key(self) -> str:
        """The i18n key for this finding's confidence tier (no strength override)."""
        return self.confidence_label()[0]

    @property
    def confidence_tone(self) -> str:
        """The display tone for this finding's confidence tier (no strength override)."""
        return self.confidence_label()[1]

    @property
    def confidence_pct_text(self) -> str:
        """Confidence as percentage text (e.g. ``'75%'``)."""
        return self.confidence_label()[2]

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

    def with_confidence_assessment(
        self,
        strength_band_key: str,
        steady_speed: bool,
        has_reference_gaps: bool,
        sensor_count: int,
    ) -> Finding:
        """Return a copy with a computed :class:`ConfidenceAssessment`.

        Reads ``effective_confidence`` and ``weak_spatial_separation``
        from *self*, delegates to :meth:`ConfidenceAssessment.assess`,
        and returns ``replace(self, confidence_assessment=ca)``.
        """
        from vibesensor.domain.confidence_assessment import ConfidenceAssessment as CA

        ca = CA.assess(
            self.effective_confidence,
            strength_band_key=strength_band_key,
            steady_speed=steady_speed,
            has_reference_gaps=has_reference_gaps,
            weak_spatial=self.weak_spatial_separation,
            sensor_count=max(sensor_count, 1),
        )
        return replace(self, confidence_assessment=ca)
