"""Structured evidence supporting a diagnostic finding.

``FindingEvidence`` captures the quantitative evidence metrics that
underpin a finding's confidence and classification.  It gives evidence
quality, consistency, and strength a domain-level identity instead of
leaving these concerns in serialization-oriented TypedDict payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

__all__ = ["FindingEvidence"]


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

    # -- thresholds --------------------------------------------------------

    _STRONG_MATCH_RATE: ClassVar[float] = 0.70
    _STRONG_SNR_DB: ClassVar[float] = 6.0
    _CONSISTENT_BURSTINESS: ClassVar[float] = 0.3
    _CONSISTENT_PRESENCE: ClassVar[float] = 0.5
    _WELL_LOCALIZED_CONCENTRATION: ClassVar[float] = 0.6

    # -- domain queries ----------------------------------------------------

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
