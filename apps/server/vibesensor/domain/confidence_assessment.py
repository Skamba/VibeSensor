"""Confidence rationale for a diagnostic conclusion.

``ConfidenceAssessment`` captures *why* confidence in a finding is
high, medium, low, or withheld.  It owns the confidence level,
drivers, caveats, and the diagnostic tier classification, giving
confidence reasoning a domain-level identity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import ClassVar

__all__ = ["ConfidenceAssessment"]


@dataclass(frozen=True, slots=True)
class ConfidenceAssessment:
    """Why confidence in a finding is high, low, or withheld."""

    raw_confidence: float
    label_key: str  # "CONFIDENCE_HIGH", "CONFIDENCE_MEDIUM", "CONFIDENCE_LOW"
    tone: str  # "success", "warn", "neutral"
    pct_text: str  # "92%", "65%", etc.
    reason: str = ""
    steady_speed: bool = True
    has_reference_gaps: bool = False
    weak_spatial: bool = False
    downgraded: bool = False

    _TIER_HIGH: ClassVar[float] = 0.70
    _TIER_MEDIUM: ClassVar[float] = 0.40

    # -- domain queries ----------------------------------------------------

    @property
    def tier(self) -> str:
        """Certainty tier: ``'A'`` (inconclusive), ``'B'`` (hypothesis), ``'C'`` (conclusion)."""
        if self.raw_confidence < self._TIER_MEDIUM or self.label_key == "CONFIDENCE_LOW":
            return "A"
        if (
            self.raw_confidence < self._TIER_HIGH
            or self.has_reference_gaps
            or self.downgraded
        ):
            return "B"
        return "C"

    @property
    def is_conclusive(self) -> bool:
        """Whether this assessment indicates a firm diagnostic conclusion."""
        return self.tier == "C"

    @property
    def needs_more_data(self) -> bool:
        """Whether more data is needed to form a useful conclusion."""
        return self.tier == "A"

    # -- factory -----------------------------------------------------------

    @classmethod
    def assess(
        cls,
        confidence: float,
        *,
        strength_band_key: str | None = None,
        steady_speed: bool = True,
        has_reference_gaps: bool = False,
        weak_spatial: bool = False,
        sensor_count: int = 1,
    ) -> ConfidenceAssessment:
        """Perform a full confidence assessment (single source of truth).

        Delegates to :meth:`Finding.classify_confidence` for the raw
        label/tone/pct classification, then layers contextual reasoning
        on top (reference gaps, speed steadiness, spatial separation,
        sensor count).
        """
        from .finding import Finding

        conf = float(confidence) if math.isfinite(confidence) else 0.0
        label_key, tone, pct_text = Finding.classify_confidence(
            conf, strength_band_key=strength_band_key
        )
        downgraded = (
            (strength_band_key or "").strip().lower() == "negligible"
            and conf >= Finding.CONFIDENCE_HIGH_THRESHOLD
        )

        reasons: list[str] = []
        if has_reference_gaps:
            reasons.append("Missing reference data may affect accuracy")
        if not steady_speed:
            reasons.append("Speed was not steady during measurement")
        if weak_spatial:
            reasons.append("Vibration spread across multiple locations")
        if sensor_count < 2:
            reasons.append("Single sensor limits spatial analysis")
        if downgraded:
            reasons.append(
                "Confidence downgraded due to negligible vibration strength"
            )

        return cls(
            raw_confidence=conf,
            label_key=label_key,
            tone=tone,
            pct_text=pct_text,
            reason="; ".join(reasons) if reasons else "",
            steady_speed=steady_speed,
            has_reference_gaps=has_reference_gaps,
            weak_spatial=weak_spatial,
            downgraded=downgraded,
        )
