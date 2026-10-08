from __future__ import annotations

from dataclasses import dataclass

from vibesensor.common.units import KMH_TO_MPS
from vibesensor.recording.run_schema import GuidedPhaseName

__all__ = [
    "PhaseOverride",
    "PhasePulse",
    "ScenarioPhase",
    "ScriptedScenario",
    "phase_speed_kmh",
]


@dataclass(frozen=True, slots=True)
class PhaseOverride:
    target: str
    profile_name: str
    scene_gain: float
    scene_noise_gain: float
    amp_scale: float
    noise_scale: float


@dataclass(frozen=True, slots=True)
class PhasePulse:
    at_s: float
    target: str
    strength: float


@dataclass(frozen=True, slots=True)
class ScenarioPhase:
    name: str
    duration_s: float
    speed_start_kmh: float
    speed_end_kmh: float
    overrides: tuple[PhaseOverride, ...]
    pulses: tuple[PhasePulse, ...] = ()
    # The guided test-drive step the driver would mark when this phase starts.
    guided_phase: GuidedPhaseName | None = None
    # The gearbox ratio the engine drives through in this phase (a lower gear);
    # ``None`` keeps the car's own gear, its top gear. Only engine orders follow it.
    gear_ratio: float | None = None
    # The bend the road takes: its radius, positive turning left, negative
    # turning right; ``None`` is straight on.
    turn_radius_m: float | None = None

    @property
    def accel_mps2(self) -> float:
        """The phase's steady longitudinal acceleration (its speed changes linearly)."""
        if self.duration_s <= 0:
            return 0.0
        return (self.speed_end_kmh - self.speed_start_kmh) * KMH_TO_MPS / self.duration_s

    @property
    def curvature_1pm(self) -> float:
        return 0.0 if not self.turn_radius_m else 1.0 / self.turn_radius_m


@dataclass(frozen=True, slots=True)
class ScriptedScenario:
    name: str
    description: str
    phases: tuple[ScenarioPhase, ...]


def phase_speed_kmh(phase: ScenarioPhase, elapsed_s: float) -> float:
    if phase.duration_s <= 0:
        return phase.speed_end_kmh
    ratio = min(max(elapsed_s / phase.duration_s, 0.0), 1.0)
    return phase.speed_start_kmh + ((phase.speed_end_kmh - phase.speed_start_kmh) * ratio)
