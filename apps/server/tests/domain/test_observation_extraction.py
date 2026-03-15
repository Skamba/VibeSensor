"""Tests for observation extraction from pre-finding evidence."""

from __future__ import annotations

from vibesensor.domain.finding import VibrationSource
from vibesensor.domain.observation import Observation
from vibesensor.domain.services.observation_extraction import (
    ObservationEvidence,
    extract_observations,
)


def _evidence(
    *,
    source: VibrationSource = VibrationSource.WHEEL_TIRE,
    signature_labels: tuple[str, ...] = ("1x wheel",),
    magnitude_db: float | None = 12.5,
    speed_band: str | None = "80-90 km/h",
    dominant_phase: str | None = None,
    location: str | None = None,
    confidence: float = 0.8,
) -> ObservationEvidence:
    return ObservationEvidence(
        source=source,
        signature_labels=signature_labels,
        magnitude_db=magnitude_db,
        speed_band=speed_band,
        dominant_phase=dominant_phase,
        location=location,
        confidence=confidence,
    )


def test_extract_observations_from_single_evidence() -> None:
    result = extract_observations([_evidence()])
    assert len(result) == 1
    obs = result[0]
    assert isinstance(obs, Observation)
    assert obs.source == VibrationSource.WHEEL_TIRE
    assert obs.magnitude_db == 12.5
    assert obs.speed_band == "80-90 km/h"
    assert obs.support_score == 0.8
    assert obs.kind == "signature-support"


def test_extract_observations_from_multiple_labels() -> None:
    ev = _evidence(signature_labels=("1x wheel", "28.0 Hz"))
    result = extract_observations([ev])
    assert len(result) == 2
    assert result[0].signature_key == "1x_wheel"
    assert result[1].signature_key == "28.0_hz"


def test_extract_observations_skips_empty_labels() -> None:
    ev = _evidence(signature_labels=("1x wheel", "", "  "))
    result = extract_observations([ev])
    assert len(result) == 1
    assert result[0].signature_key == "1x_wheel"


def test_extract_observations_normalizes_signature_key() -> None:
    ev = _evidence(signature_labels=("  Body Resonance  ",))
    result = extract_observations([ev])
    assert result[0].signature_key == "body_resonance"


def test_extract_observations_parses_phase() -> None:
    ev = _evidence(dominant_phase="cruise")
    result = extract_observations([ev])
    from vibesensor.domain.driving_phase import DrivingPhase

    assert result[0].phase == DrivingPhase.CRUISE


def test_extract_observations_handles_invalid_phase() -> None:
    ev = _evidence(dominant_phase="NOT_A_PHASE")
    result = extract_observations([ev])
    assert result[0].phase is None


def test_extract_observations_deterministic_ids() -> None:
    evs = [_evidence(), _evidence(signature_labels=("sig_a", "sig_b"))]
    result = extract_observations(evs)
    assert result[0].observation_id == "obs-1-1"
    assert result[1].observation_id == "obs-2-1"
    assert result[2].observation_id == "obs-2-2"


def test_observation_evidence_is_finding_independent() -> None:
    ev = ObservationEvidence(
        source=VibrationSource.ENGINE,
        signature_labels=("harmonic",),
        magnitude_db=5.0,
        speed_band=None,
        dominant_phase=None,
        location="front_left",
        confidence=0.6,
    )
    result = extract_observations([ev])
    assert len(result) == 1
    assert result[0].source == VibrationSource.ENGINE
    assert result[0].location == "front_left"
