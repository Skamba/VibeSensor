"""Meaningful fact extracted from processed run data."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.domain.sensing.driving_phase import DrivingPhase

from .finding import VibrationSource

__all__ = ["Observation"]


@dataclass(frozen=True, slots=True)
class Observation:
    """One diagnostically meaningful observation."""

    observation_id: str
    kind: str
    source: VibrationSource
    signature_key: str
    magnitude_db: float | None = None
    speed_band: str | None = None
    phase: DrivingPhase | None = None
    location: str | None = None
    support_score: float = 0.0

    @property
    def supports_signature(self) -> bool:
        return bool(self.signature_key.strip()) and self.support_score > 0.0
