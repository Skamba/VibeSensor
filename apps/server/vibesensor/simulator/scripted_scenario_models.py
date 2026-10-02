from __future__ import annotations

from dataclasses import dataclass

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
    common_event_gain: float


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
