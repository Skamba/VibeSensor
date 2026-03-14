"""Observation extraction service."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..driving_phase import DrivingPhase
from ..finding import VibrationSource
from ..observation import Observation


@dataclass(frozen=True, slots=True)
class ObservationEvidence:
    """Pre-finding evidence needed for observation extraction."""

    source: VibrationSource
    signature_labels: tuple[str, ...]
    magnitude_db: float | None
    speed_band: str | None
    dominant_phase: str | None
    location: str | None
    confidence: float


def extract_observations(evidence: Sequence[ObservationEvidence]) -> tuple[Observation, ...]:
    """Derive diagnostically meaningful observations from pre-finding evidence."""
    observations: list[Observation] = []
    for ev_idx, ev in enumerate(evidence, start=1):
        dominant_phase = (ev.dominant_phase or "").upper()
        phase = DrivingPhase[dominant_phase] if dominant_phase in DrivingPhase.__members__ else None
        for sig_idx, label in enumerate(ev.signature_labels, start=1):
            if not label.strip():
                continue
            observations.append(
                Observation(
                    observation_id=f"obs-{ev_idx}-{sig_idx}",
                    kind="signature-support",
                    source=ev.source,
                    signature_key=label.strip().lower().replace(" ", "_"),
                    magnitude_db=ev.magnitude_db,
                    speed_band=ev.speed_band,
                    phase=phase,
                    location=ev.location,
                    support_score=ev.confidence,
                )
            )
    return tuple(observations)
