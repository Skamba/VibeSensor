"""One diagnostic conclusion or cause candidate from analysis.

``Finding`` is the richest domain object.  It owns classification
(reference / informational / diagnostic), actionability, surfacing
decisions, confidence normalisation, deterministic ranking, and
phase-adjusted scoring.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import ClassVar, Final

__all__ = [
    "Finding",
    "FindingKind",
]


class FindingKind(StrEnum):
    """Classification category of a diagnostic finding."""

    REFERENCE = "reference"
    INFORMATIONAL = "informational"
    DIAGNOSTIC = "diagnostic"


_KIND_AUTO: Final = FindingKind.DIAGNOSTIC
"""Sentinel: when ``kind`` is left at this default during direct construction,
``__post_init__`` derives the actual kind from ``finding_id`` / ``severity``."""


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
    suspected_source: str = ""
    confidence: float | None = None
    frequency_hz: float | None = None
    order: str = ""
    severity: str = ""
    strongest_location: str | None = None
    strongest_speed_band: str | None = None
    peak_classification: str = ""
    kind: FindingKind = FindingKind.DIAGNOSTIC

    # Evidence and ranking fields ------------------------------------------
    ranking_score: float = 0.0
    dominance_ratio: float | None = None
    diffuse_excitation: bool = False
    weak_spatial_separation: bool = False
    phase_evidence: dict[str, float] | None = field(default=None, hash=False)

    def __post_init__(self) -> None:
        """Auto-derive ``kind`` when constructed directly without explicit kind."""
        if self.kind is _KIND_AUTO:
            derived = self._kind_from_fields(self.finding_id, self.severity)
            if derived is not _KIND_AUTO:
                object.__setattr__(self, "kind", derived)

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

    _PLACEHOLDER_SOURCES: ClassVar[frozenset[str]] = frozenset(
        {"unknown_resonance", "unknown"},
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

        # Evidence / ranking fields (read both new and legacy key names)
        ranking_raw = payload.get("ranking_score") or payload.get("_ranking_score")
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
        phase_evidence: dict[str, float] | None = None
        if isinstance(phase_ev, dict):
            phase_evidence = phase_ev

        finding_id = _str("finding_id")
        severity = _str("severity")

        # Derive kind from explicit finding_type or infer from fields
        kind = cls._derive_kind(payload, finding_id=finding_id, severity=severity)

        return cls(
            finding_id=finding_id,
            suspected_source=_str("suspected_source", "source"),
            confidence=confidence,
            frequency_hz=frequency_hz,
            order=_str("order"),
            severity=severity,
            strongest_location=str(loc) if loc is not None else None,
            strongest_speed_band=str(band) if band is not None else None,
            peak_classification=_str("peak_classification"),
            kind=kind,
            ranking_score=ranking_score,
            dominance_ratio=dominance_ratio,
            diffuse_excitation=bool(payload.get("diffuse_excitation", False)),
            weak_spatial_separation=bool(payload.get("weak_spatial_separation", False)),
            phase_evidence=phase_evidence,
        )

    @staticmethod
    def _derive_kind(
        payload: Mapping[str, object],
        *,
        finding_id: str,
        severity: str,
    ) -> FindingKind:
        """Derive FindingKind from explicit ``finding_type`` or infer from fields."""
        explicit = payload.get("finding_type")
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

    @property
    def is_actionable(self) -> bool:
        """Whether this finding identifies a meaningful mechanical component.

        A finding is actionable when its suspected source is not a
        placeholder value, **or** when it has a specific (non-unknown)
        location even if the source is a placeholder.
        """
        if self.source_normalized not in self._PLACEHOLDER_SOURCES:
            return True
        location = (self.strongest_location or "").strip().lower()
        return location not in self._UNKNOWN_LOCATIONS

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

    @property
    def phase_adjusted_score(self) -> float:
        """Phase-aware ranking score used for top-cause selection.

        Cruise-heavy findings receive a modest score boost because
        constant-speed conditions produce the most reliable spectral
        evidence.
        """
        cruise_fraction = 0.0
        if isinstance(self.phase_evidence, dict):
            raw = self.phase_evidence.get("cruise_fraction", 0.0)
            try:
                cruise_fraction = float(raw)
            except (TypeError, ValueError):
                pass
        return self.effective_confidence * (0.85 + 0.15 * cruise_fraction)

    def is_stronger_than(self, other: Finding) -> bool:
        """Whether this finding ranks higher than *other*."""
        return self.phase_adjusted_score > other.phase_adjusted_score
