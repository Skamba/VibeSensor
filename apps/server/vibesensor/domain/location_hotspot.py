"""Spatial concentration of vibration evidence.

``LocationHotspot`` captures where vibration evidence is strongest,
whether the source is well-localised or ambiguous, and what
alternative locations compete.  This gives spatial reasoning a
domain-level identity instead of living in boundary TypedDicts.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar

from vibesensor.coerce import coerce_float, coerce_int

__all__ = ["LocationHotspot", "LocationIntensitySummary"]


@dataclass(frozen=True, slots=True)
class LocationHotspot:
    """Where vibration evidence is spatially concentrated."""

    strongest_location: str = ""
    dominance_ratio: float | None = None
    localization_confidence: float | None = None
    weak_spatial_separation: bool = False
    ambiguous: bool = False
    alternative_locations: tuple[str, ...] = ()
    location_count: int | None = None

    _UNKNOWN_LOCATIONS: ClassVar[frozenset[str]] = frozenset(
        {"", "unknown", "not available", "n/a"},
    )
    WEAK_SPATIAL_BASELINE: ClassVar[float] = 1.2
    _HIGH_CONFIDENCE_THRESHOLD: ClassVar[float] = 0.7
    _MEDIUM_CONFIDENCE_THRESHOLD: ClassVar[float] = 0.4
    _NEAR_TIE_CONFIDENCE_RATIO: ClassVar[float] = 0.7

    @staticmethod
    def weak_spatial_threshold(location_count: int | None) -> float:
        """Return the adaptive dominance threshold for weak separation."""
        baseline = LocationHotspot.WEAK_SPATIAL_BASELINE
        if location_count is None:
            return baseline
        n_locations = max(2, int(location_count))
        return baseline * (1.0 + (0.1 * (n_locations - 2)))

    @staticmethod
    def compute_confidence(
        *,
        dominance_ratio: float,
        location_count: int,
        total_samples: int,
    ) -> float:
        """Compute localization confidence from spatial evidence metrics."""
        dominance_component = max(0.0, min(1.0, (dominance_ratio - 1.0) / 0.5))
        location_component = 1.0 / max(1.0, 1.0 + (max(0, location_count - 1) * 0.15))
        sample_component = min(1.0, max(0.0, total_samples / 10.0))
        confidence = dominance_component * location_component * (0.6 + 0.4 * sample_component)
        return max(0.05, min(1.0, confidence))

    # -- domain queries ----------------------------------------------------

    @property
    def has_clear_separation(self) -> bool:
        """Evidence is not spatially weak or ambiguous."""
        return not self.weak_spatial_separation and not self.ambiguous

    @property
    def is_well_localized(self) -> bool:
        """Evidence is clearly concentrated at one location."""
        if self.strongest_location.strip().lower() in self._UNKNOWN_LOCATIONS:
            return False
        return self.has_clear_separation and (
            self.dominance_ratio is None or self.dominance_ratio >= 0.5
        )

    @property
    def is_actionable(self) -> bool:
        """Location is known and clear enough to act on."""
        return (
            self.strongest_location.strip().lower() not in self._UNKNOWN_LOCATIONS
            and not self.ambiguous
        )

    @property
    def confidence_band(self) -> str:
        """Bucket localization confidence into high/medium/low bands."""
        confidence = self.localization_confidence or 0.0
        if confidence >= self._HIGH_CONFIDENCE_THRESHOLD:
            return "high"
        if confidence >= self._MEDIUM_CONFIDENCE_THRESHOLD:
            return "medium"
        return "low"

    @property
    def supporting_locations(self) -> tuple[str, ...]:
        """Alternative locations excluding the primary location."""
        primary = self.strongest_location.strip()
        supporting: list[str] = []
        for candidate in self.alternative_locations:
            location = str(candidate).strip()
            if not location or location == primary or location in supporting:
                continue
            supporting.append(location)
        return tuple(supporting)

    @property
    def summary_location(self) -> str:
        """Location string used by summarized origin projections."""
        primary = self.strongest_location.strip() or "unknown"
        if self.has_clear_separation:
            return primary
        display_locations = [primary, *self.supporting_locations]
        unique_locations: list[str] = []
        for candidate in display_locations:
            if candidate and candidate not in unique_locations:
                unique_locations.append(candidate)
        return " / ".join(unique_locations) if unique_locations else primary

    @property
    def display_location(self) -> str:
        """Human-readable location string."""
        loc = self.strongest_location.strip()
        if loc.lower() in self._UNKNOWN_LOCATIONS:
            return "Unknown"
        return loc.replace("_", " ").title()

    @classmethod
    def from_analysis_inputs(
        cls,
        *,
        strongest_location: str,
        dominance_ratio: float | None = None,
        localization_confidence: float | None = None,
        weak_spatial_separation: bool = False,
        ambiguous: bool = False,
        alternative_locations: Sequence[str] = (),
    ) -> LocationHotspot:
        """Construct from typed analysis-side inputs.

        Any ambiguity promotion driven by a second finding must be resolved
        before this method is called because ``LocationHotspot`` is frozen.
        """
        return cls(
            strongest_location=strongest_location,
            dominance_ratio=dominance_ratio,
            localization_confidence=localization_confidence,
            weak_spatial_separation=weak_spatial_separation,
            ambiguous=ambiguous,
            alternative_locations=tuple(str(loc) for loc in alternative_locations if loc),
        )

    def promote_near_tie(
        self,
        *,
        alternative_location: str,
        top_confidence: float,
        alternative_confidence: float,
    ) -> LocationHotspot:
        """Return a hotspot promoted to ambiguous when a second finding is near-tied."""
        contender = alternative_location.strip()
        primary = self.strongest_location.strip()
        if (
            not contender
            or not primary
            or contender == primary
            or top_confidence <= 0.0
            or alternative_confidence / top_confidence < self._NEAR_TIE_CONFIDENCE_RATIO
        ):
            return self
        return LocationHotspot(
            strongest_location=self.strongest_location,
            dominance_ratio=self.dominance_ratio,
            localization_confidence=self.localization_confidence,
            weak_spatial_separation=True,
            ambiguous=True,
            alternative_locations=(*self.alternative_locations, contender),
        )

    def with_adaptive_weak_spatial(self, location_count: int | None) -> LocationHotspot:
        """Return a hotspot with adaptive weak-spatial classification applied."""
        if self.dominance_ratio is None:
            return self
        threshold = self.weak_spatial_threshold(location_count)
        if self.weak_spatial_separation or self.dominance_ratio < threshold:
            return LocationHotspot(
                strongest_location=self.strongest_location,
                dominance_ratio=self.dominance_ratio,
                localization_confidence=self.localization_confidence,
                weak_spatial_separation=True,
                ambiguous=self.ambiguous,
                alternative_locations=self.alternative_locations,
            )
        return self


# ---------------------------------------------------------------------------
# LocationIntensitySummary
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LocationIntensitySummary:
    """Typed internal per-location intensity summary for diagnostics.

    Replaces the untyped ``IntensityRow`` (``JsonObject`` alias) with a
    structured domain representation of sensor intensity at one location.
    """

    location: str
    partial_coverage: bool = False
    sample_count: int = 0
    sample_coverage_ratio: float = 0.0
    sample_coverage_warning: bool = False
    mean_intensity_db: float | None = None
    p50_intensity_db: float | None = None
    p95_intensity_db: float | None = None
    max_intensity_db: float | None = None
    dropped_frames_delta: float | None = None
    queue_overflow_drops_delta: float | None = None
    strength_bucket_distribution: Mapping[str, object] = ()  # type: ignore[assignment]
    phase_intensity: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if self.sample_count < 0:
            raise ValueError("sample_count must be >= 0")
        if not (0.0 <= self.sample_coverage_ratio <= 1.0):
            raise ValueError("sample_coverage_ratio must be in [0.0, 1.0]")
        # Normalize strength_bucket_distribution from any input to a dict
        sbd = self.strength_bucket_distribution
        if isinstance(sbd, tuple) and not sbd:
            object.__setattr__(self, "strength_bucket_distribution", {})
        elif not isinstance(sbd, dict):
            object.__setattr__(self, "strength_bucket_distribution", dict(sbd))

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> LocationIntensitySummary:
        """Parse from a raw dict."""

        def _opt_float(key: str) -> float | None:
            v = raw.get(key)
            if v is None:
                return None
            if not isinstance(v, (int, float, str)):
                return None
            try:
                f = coerce_float(v)
            except (TypeError, ValueError):
                return None
            return f

        sc = raw.get("sample_count", raw.get("samples", 0))
        try:
            sample_count = coerce_int(sc)
        except (TypeError, ValueError):
            sample_count = 0

        scr = raw.get("sample_coverage_ratio", 0.0)
        try:
            sample_coverage_ratio = coerce_float(scr)
        except (TypeError, ValueError):
            sample_coverage_ratio = 0.0

        sbd = raw.get("strength_bucket_distribution")
        if not isinstance(sbd, dict):
            sbd = {}

        pi = raw.get("phase_intensity")
        if pi is not None and not isinstance(pi, dict):
            pi = None

        return cls(
            location=str(raw.get("location", "")),
            partial_coverage=bool(raw.get("partial_coverage", False)),
            sample_count=sample_count,
            sample_coverage_ratio=sample_coverage_ratio,
            sample_coverage_warning=bool(raw.get("sample_coverage_warning", False)),
            mean_intensity_db=_opt_float("mean_intensity_db"),
            p50_intensity_db=_opt_float("p50_intensity_db"),
            p95_intensity_db=_opt_float("p95_intensity_db"),
            max_intensity_db=_opt_float("max_intensity_db"),
            dropped_frames_delta=_opt_float("dropped_frames_delta"),
            queue_overflow_drops_delta=_opt_float("queue_overflow_drops_delta"),
            strength_bucket_distribution=sbd,
            phase_intensity=pi if isinstance(pi, dict) else None,
        )
