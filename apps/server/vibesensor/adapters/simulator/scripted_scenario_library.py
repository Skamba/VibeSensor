from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "SCRIPTED_SCENARIOS",
    "PhaseOverride",
    "PhasePulse",
    "ScenarioPhase",
    "ScriptedScenario",
    "is_scripted_scenario",
    "phase_speed_kmh",
    "scripted_scenario_help",
    "scripted_scenario_names",
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


def _state(
    target: str,
    profile_name: str,
    *,
    scene_gain: float,
    scene_noise_gain: float,
    amp_scale: float,
    noise_scale: float,
    common_event_gain: float,
) -> PhaseOverride:
    return PhaseOverride(
        target=target,
        profile_name=profile_name,
        scene_gain=scene_gain,
        scene_noise_gain=scene_noise_gain,
        amp_scale=amp_scale,
        noise_scale=noise_scale,
        common_event_gain=common_event_gain,
    )


def _pulse(at_s: float, target: str, strength: float) -> PhasePulse:
    return PhasePulse(at_s=at_s, target=target, strength=strength)


def phase_speed_kmh(phase: ScenarioPhase, elapsed_s: float) -> float:
    if phase.duration_s <= 0:
        return phase.speed_end_kmh
    ratio = min(max(elapsed_s / phase.duration_s, 0.0), 1.0)
    return phase.speed_start_kmh + ((phase.speed_end_kmh - phase.speed_start_kmh) * ratio)


def is_scripted_scenario(name: str) -> bool:
    return name in SCRIPTED_SCENARIOS


def scripted_scenario_names() -> tuple[str, ...]:
    return tuple(SCRIPTED_SCENARIOS)


def scripted_scenario_help() -> str:
    return "\n".join(
        f"  {scenario.name}: {scenario.description}" for scenario in SCRIPTED_SCENARIOS.values()
    )


def _phase_with_hold(
    phase: ScenarioPhase,
    *,
    hold_name: str,
    hold_duration_s: float,
    hold_speed_kmh: float | None = None,
    hold_pulses: tuple[PhasePulse, ...] = (),
) -> tuple[ScenarioPhase, ScenarioPhase]:
    speed_kmh = phase.speed_end_kmh if hold_speed_kmh is None else hold_speed_kmh
    return (
        phase,
        ScenarioPhase(
            name=hold_name,
            duration_s=hold_duration_s,
            speed_start_kmh=speed_kmh,
            speed_end_kmh=speed_kmh,
            overrides=phase.overrides,
            pulses=hold_pulses,
        ),
    )


SCRIPTED_SCENARIOS: dict[str, ScriptedScenario] = {
    "accel-front-left-surge": ScriptedScenario(
        name="accel-front-left-surge",
        description="Accelerating run with a temporary front-left wheel surge before recovery.",
        phases=(
            ScenarioPhase(
                name="launch",
                duration_s=6.0,
                speed_start_kmh=18.0,
                speed_end_kmh=56.0,
                overrides=(
                    _state(
                        "all",
                        "rough_road",
                        scene_gain=0.34,
                        scene_noise_gain=1.02,
                        amp_scale=0.60,
                        noise_scale=1.00,
                        common_event_gain=0.10,
                    ),
                    _state(
                        "body",
                        "rear_body",
                        scene_gain=0.42,
                        scene_noise_gain=1.00,
                        amp_scale=0.74,
                        noise_scale=1.00,
                        common_event_gain=0.12,
                    ),
                    _state(
                        "front-left",
                        "wheel_mild_imbalance",
                        scene_gain=0.62,
                        scene_noise_gain=1.05,
                        amp_scale=0.92,
                        noise_scale=1.04,
                        common_event_gain=0.18,
                    ),
                ),
                pulses=(_pulse(1.5, "all", 0.18),),
            ),
            *_phase_with_hold(
                ScenarioPhase(
                    name="surge-window",
                    duration_s=8.0,
                    speed_start_kmh=56.0,
                    speed_end_kmh=96.0,
                    overrides=(
                        _state(
                            "all",
                            "rough_road",
                            scene_gain=0.38,
                            scene_noise_gain=1.04,
                            amp_scale=0.66,
                            noise_scale=1.02,
                            common_event_gain=0.12,
                        ),
                        _state(
                            "body",
                            "rear_body",
                            scene_gain=0.48,
                            scene_noise_gain=1.02,
                            amp_scale=0.78,
                            noise_scale=1.02,
                            common_event_gain=0.16,
                        ),
                        _state(
                            "front-left",
                            "wheel_imbalance",
                            scene_gain=0.98,
                            scene_noise_gain=1.10,
                            amp_scale=1.10,
                            noise_scale=1.08,
                            common_event_gain=0.24,
                        ),
                        _state(
                            "front-right",
                            "wheel_mild_imbalance",
                            scene_gain=0.58,
                            scene_noise_gain=1.03,
                            amp_scale=0.86,
                            noise_scale=1.02,
                            common_event_gain=0.16,
                        ),
                        _state(
                            "rear-left",
                            "wheel_mild_imbalance",
                            scene_gain=0.54,
                            scene_noise_gain=1.02,
                            amp_scale=0.82,
                            noise_scale=1.01,
                            common_event_gain=0.15,
                        ),
                    ),
                    pulses=(
                        _pulse(2.0, "front-left", 0.82),
                        _pulse(5.2, "front-left", 0.60),
                        _pulse(6.0, "front-right", 0.28),
                    ),
                ),
                hold_name="surge-hold",
                hold_duration_s=4.0,
            ),
            ScenarioPhase(
                name="settle",
                duration_s=6.0,
                speed_start_kmh=96.0,
                speed_end_kmh=84.0,
                overrides=(
                    _state(
                        "all",
                        "rough_road",
                        scene_gain=0.28,
                        scene_noise_gain=0.98,
                        amp_scale=0.52,
                        noise_scale=0.98,
                        common_event_gain=0.08,
                    ),
                    _state(
                        "body",
                        "rear_body",
                        scene_gain=0.34,
                        scene_noise_gain=0.98,
                        amp_scale=0.62,
                        noise_scale=0.99,
                        common_event_gain=0.10,
                    ),
                ),
            ),
        ),
    ),
    "coastdown-rear-right-rumble": ScriptedScenario(
        name="coastdown-rear-right-rumble",
        description="Rear-right rumble that grows during a highway coastdown, then fades.",
        phases=(
            ScenarioPhase(
                name="cruise",
                duration_s=5.0,
                speed_start_kmh=112.0,
                speed_end_kmh=108.0,
                overrides=(
                    _state(
                        "all",
                        "wheel_mild_imbalance",
                        scene_gain=0.42,
                        scene_noise_gain=1.02,
                        amp_scale=0.70,
                        noise_scale=1.02,
                        common_event_gain=0.14,
                    ),
                    _state(
                        "body",
                        "rear_body",
                        scene_gain=0.44,
                        scene_noise_gain=1.00,
                        amp_scale=0.76,
                        noise_scale=1.00,
                        common_event_gain=0.16,
                    ),
                ),
                pulses=(_pulse(2.4, "rear-axle", 0.22),),
            ),
            *_phase_with_hold(
                ScenarioPhase(
                    name="coastdown-window",
                    duration_s=6.0,
                    speed_start_kmh=108.0,
                    speed_end_kmh=100.0,
                    overrides=(
                        _state(
                            "all",
                            "wheel_mild_imbalance",
                            scene_gain=0.36,
                            scene_noise_gain=1.00,
                            amp_scale=0.66,
                            noise_scale=1.00,
                            common_event_gain=0.12,
                        ),
                        _state(
                            "body",
                            "rear_body",
                            scene_gain=0.56,
                            scene_noise_gain=1.04,
                            amp_scale=0.84,
                            noise_scale=1.04,
                            common_event_gain=0.22,
                        ),
                        _state(
                            "rear-right",
                            "wheel_imbalance",
                            scene_gain=0.92,
                            scene_noise_gain=1.08,
                            amp_scale=1.02,
                            noise_scale=1.06,
                            common_event_gain=0.22,
                        ),
                        _state(
                            "rear-left",
                            "wheel_mild_imbalance",
                            scene_gain=0.60,
                            scene_noise_gain=1.04,
                            amp_scale=0.88,
                            noise_scale=1.04,
                            common_event_gain=0.18,
                        ),
                        _state(
                            "right-side",
                            "wheel_mild_imbalance",
                            scene_gain=0.56,
                            scene_noise_gain=1.02,
                            amp_scale=0.84,
                            noise_scale=1.02,
                            common_event_gain=0.16,
                        ),
                    ),
                    pulses=(
                        _pulse(1.6, "rear-right", 0.58),
                        _pulse(4.8, "rear-right", 0.72),
                        _pulse(6.0, "body", 0.36),
                    ),
                ),
                hold_name="rear-right-hold",
                hold_duration_s=4.0,
            ),
            ScenarioPhase(
                name="rollout",
                duration_s=6.0,
                speed_start_kmh=100.0,
                speed_end_kmh=18.0,
                overrides=(
                    _state(
                        "all",
                        "rough_road",
                        scene_gain=0.24,
                        scene_noise_gain=0.96,
                        amp_scale=0.46,
                        noise_scale=0.96,
                        common_event_gain=0.06,
                    ),
                    _state(
                        "body",
                        "rear_body",
                        scene_gain=0.28,
                        scene_noise_gain=0.98,
                        amp_scale=0.56,
                        noise_scale=0.98,
                        common_event_gain=0.08,
                    ),
                ),
            ),
        ),
    ),
    "highway-window-shudder": ScriptedScenario(
        name="highway-window-shudder",
        description="All-sensor shudder appears only inside a narrow highway-speed window.",
        phases=(
            ScenarioPhase(
                name="approach",
                duration_s=7.0,
                speed_start_kmh=68.0,
                speed_end_kmh=94.0,
                overrides=(
                    _state(
                        "all",
                        "rough_road",
                        scene_gain=0.30,
                        scene_noise_gain=1.00,
                        amp_scale=0.56,
                        noise_scale=1.00,
                        common_event_gain=0.12,
                    ),
                    _state(
                        "body",
                        "rear_body",
                        scene_gain=0.38,
                        scene_noise_gain=1.00,
                        amp_scale=0.68,
                        noise_scale=1.00,
                        common_event_gain=0.14,
                    ),
                ),
            ),
            *_phase_with_hold(
                ScenarioPhase(
                    name="resonance-window",
                    duration_s=5.0,
                    speed_start_kmh=94.0,
                    speed_end_kmh=100.0,
                    overrides=(
                        _state(
                            "all",
                            "wheel_mild_imbalance",
                            scene_gain=0.62,
                            scene_noise_gain=1.05,
                            amp_scale=0.90,
                            noise_scale=1.04,
                            common_event_gain=0.44,
                        ),
                        _state(
                            "body",
                            "rear_body",
                            scene_gain=0.72,
                            scene_noise_gain=1.04,
                            amp_scale=0.98,
                            noise_scale=1.04,
                            common_event_gain=0.50,
                        ),
                    ),
                    pulses=(
                        _pulse(1.2, "all", 0.30),
                        _pulse(3.0, "all", 0.34),
                        _pulse(4.5, "all", 0.26),
                    ),
                ),
                hold_name="shudder-hold",
                hold_duration_s=4.0,
            ),
            ScenarioPhase(
                name="clear-air",
                duration_s=6.0,
                speed_start_kmh=100.0,
                speed_end_kmh=112.0,
                overrides=(
                    _state(
                        "all",
                        "rough_road",
                        scene_gain=0.26,
                        scene_noise_gain=0.98,
                        amp_scale=0.50,
                        noise_scale=0.98,
                        common_event_gain=0.10,
                    ),
                    _state(
                        "body",
                        "rear_body",
                        scene_gain=0.30,
                        scene_noise_gain=0.98,
                        amp_scale=0.58,
                        noise_scale=0.98,
                        common_event_gain=0.10,
                    ),
                ),
            ),
        ),
    ),
    "launch-engine-flare": ScriptedScenario(
        name="launch-engine-flare",
        description="Low-speed launch with strong engine order that settles into normal cruise.",
        phases=(
            ScenarioPhase(
                name="idle-creep",
                duration_s=5.0,
                speed_start_kmh=0.0,
                speed_end_kmh=18.0,
                overrides=(
                    _state(
                        "all",
                        "engine_idle",
                        scene_gain=0.70,
                        scene_noise_gain=0.98,
                        amp_scale=0.92,
                        noise_scale=0.96,
                        common_event_gain=0.10,
                    ),
                    _state(
                        "body",
                        "rear_body",
                        scene_gain=0.46,
                        scene_noise_gain=0.98,
                        amp_scale=0.70,
                        noise_scale=0.96,
                        common_event_gain=0.08,
                    ),
                ),
                pulses=(_pulse(2.0, "all", 0.12),),
            ),
            *_phase_with_hold(
                ScenarioPhase(
                    name="flare",
                    duration_s=7.0,
                    speed_start_kmh=18.0,
                    speed_end_kmh=72.0,
                    overrides=(
                        _state(
                            "all",
                            "engine_order",
                            scene_gain=0.88,
                            scene_noise_gain=1.04,
                            amp_scale=1.04,
                            noise_scale=1.00,
                            common_event_gain=0.20,
                        ),
                        _state(
                            "front-axle",
                            "engine_order",
                            scene_gain=0.94,
                            scene_noise_gain=1.06,
                            amp_scale=1.08,
                            noise_scale=1.02,
                            common_event_gain=0.24,
                        ),
                        _state(
                            "body",
                            "rear_body",
                            scene_gain=0.54,
                            scene_noise_gain=1.02,
                            amp_scale=0.80,
                            noise_scale=1.00,
                            common_event_gain=0.16,
                        ),
                    ),
                    pulses=(
                        _pulse(1.5, "front-axle", 0.20),
                        _pulse(4.2, "all", 0.18),
                    ),
                ),
                hold_name="engine-hold",
                hold_duration_s=4.0,
            ),
            ScenarioPhase(
                name="cruise",
                duration_s=6.0,
                speed_start_kmh=72.0,
                speed_end_kmh=68.0,
                overrides=(
                    _state(
                        "all",
                        "rough_road",
                        scene_gain=0.28,
                        scene_noise_gain=1.00,
                        amp_scale=0.54,
                        noise_scale=1.00,
                        common_event_gain=0.10,
                    ),
                    _state(
                        "body",
                        "rear_body",
                        scene_gain=0.34,
                        scene_noise_gain=1.00,
                        amp_scale=0.62,
                        noise_scale=1.00,
                        common_event_gain=0.12,
                    ),
                ),
            ),
        ),
    ),
    "pothole-recovery-loop": ScriptedScenario(
        name="pothole-recovery-loop",
        description="Cruise with repeated road impacts, then a quiet recovery section.",
        phases=(
            ScenarioPhase(
                name="steady-road",
                duration_s=6.0,
                speed_start_kmh=58.0,
                speed_end_kmh=70.0,
                overrides=(
                    _state(
                        "all",
                        "rough_road",
                        scene_gain=0.36,
                        scene_noise_gain=1.04,
                        amp_scale=0.64,
                        noise_scale=1.04,
                        common_event_gain=0.14,
                    ),
                    _state(
                        "body",
                        "rear_body",
                        scene_gain=0.44,
                        scene_noise_gain=1.03,
                        amp_scale=0.76,
                        noise_scale=1.02,
                        common_event_gain=0.16,
                    ),
                ),
            ),
            *_phase_with_hold(
                ScenarioPhase(
                    name="impact-cluster",
                    duration_s=5.0,
                    speed_start_kmh=70.0,
                    speed_end_kmh=72.0,
                    overrides=(
                        _state(
                            "all",
                            "rough_road",
                            scene_gain=0.48,
                            scene_noise_gain=1.12,
                            amp_scale=0.76,
                            noise_scale=1.10,
                            common_event_gain=0.24,
                        ),
                        _state(
                            "body",
                            "rear_body",
                            scene_gain=0.58,
                            scene_noise_gain=1.14,
                            amp_scale=0.88,
                            noise_scale=1.10,
                            common_event_gain=0.28,
                        ),
                    ),
                    pulses=(
                        _pulse(0.7, "all", 0.40),
                        _pulse(1.6, "left-side", 0.54),
                        _pulse(2.4, "right-side", 0.50),
                        _pulse(3.5, "all", 0.36),
                    ),
                ),
                hold_name="post-impact-hold",
                hold_duration_s=4.0,
            ),
            ScenarioPhase(
                name="recovery",
                duration_s=7.0,
                speed_start_kmh=72.0,
                speed_end_kmh=62.0,
                overrides=(
                    _state(
                        "all",
                        "rough_road",
                        scene_gain=0.20,
                        scene_noise_gain=0.94,
                        amp_scale=0.42,
                        noise_scale=0.94,
                        common_event_gain=0.05,
                    ),
                    _state(
                        "body",
                        "rear_body",
                        scene_gain=0.24,
                        scene_noise_gain=0.95,
                        amp_scale=0.50,
                        noise_scale=0.95,
                        common_event_gain=0.06,
                    ),
                ),
            ),
        ),
    ),
    "lane-change-left-right": ScriptedScenario(
        name="lane-change-left-right",
        description="Temporary left-side then right-side disturbance while speed oscillates.",
        phases=(
            *_phase_with_hold(
                ScenarioPhase(
                    name="left-load",
                    duration_s=5.0,
                    speed_start_kmh=72.0,
                    speed_end_kmh=84.0,
                    overrides=(
                        _state(
                            "all",
                            "wheel_mild_imbalance",
                            scene_gain=0.34,
                            scene_noise_gain=1.00,
                            amp_scale=0.62,
                            noise_scale=1.00,
                            common_event_gain=0.12,
                        ),
                        _state(
                            "body",
                            "rear_body",
                            scene_gain=0.42,
                            scene_noise_gain=1.00,
                            amp_scale=0.74,
                            noise_scale=1.00,
                            common_event_gain=0.14,
                        ),
                        _state(
                            "left-side",
                            "wheel_imbalance",
                            scene_gain=0.82,
                            scene_noise_gain=1.06,
                            amp_scale=0.98,
                            noise_scale=1.04,
                            common_event_gain=0.20,
                        ),
                    ),
                    pulses=(
                        _pulse(1.4, "left-side", 0.42),
                        _pulse(4.1, "front-left", 0.56),
                    ),
                ),
                hold_name="left-hold",
                hold_duration_s=3.0,
            ),
            *_phase_with_hold(
                ScenarioPhase(
                    name="right-load",
                    duration_s=5.0,
                    speed_start_kmh=84.0,
                    speed_end_kmh=82.0,
                    overrides=(
                        _state(
                            "all",
                            "wheel_mild_imbalance",
                            scene_gain=0.36,
                            scene_noise_gain=1.02,
                            amp_scale=0.64,
                            noise_scale=1.02,
                            common_event_gain=0.12,
                        ),
                        _state(
                            "body",
                            "rear_body",
                            scene_gain=0.42,
                            scene_noise_gain=1.00,
                            amp_scale=0.72,
                            noise_scale=1.00,
                            common_event_gain=0.14,
                        ),
                        _state(
                            "right-side",
                            "wheel_imbalance",
                            scene_gain=0.80,
                            scene_noise_gain=1.06,
                            amp_scale=0.96,
                            noise_scale=1.04,
                            common_event_gain=0.20,
                        ),
                    ),
                    pulses=(
                        _pulse(1.2, "right-side", 0.40),
                        _pulse(4.0, "rear-right", 0.52),
                    ),
                ),
                hold_name="right-hold",
                hold_duration_s=3.0,
            ),
            ScenarioPhase(
                name="straighten-out",
                duration_s=5.0,
                speed_start_kmh=82.0,
                speed_end_kmh=76.0,
                overrides=(
                    _state(
                        "all",
                        "rough_road",
                        scene_gain=0.24,
                        scene_noise_gain=0.98,
                        amp_scale=0.48,
                        noise_scale=0.98,
                        common_event_gain=0.08,
                    ),
                    _state(
                        "body",
                        "rear_body",
                        scene_gain=0.28,
                        scene_noise_gain=0.98,
                        amp_scale=0.56,
                        noise_scale=0.98,
                        common_event_gain=0.08,
                    ),
                ),
            ),
        ),
    ),
    "rear-left-cruise-rumble": ScriptedScenario(
        name="rear-left-cruise-rumble",
        description="Steady highway cruise with a temporary rear-left wheel rumble.",
        phases=(
            ScenarioPhase(
                name="approach",
                duration_s=6.0,
                speed_start_kmh=78.0,
                speed_end_kmh=92.0,
                overrides=(
                    _state(
                        "all",
                        "wheel_mild_imbalance",
                        scene_gain=0.30,
                        scene_noise_gain=1.00,
                        amp_scale=0.58,
                        noise_scale=1.00,
                        common_event_gain=0.10,
                    ),
                    _state(
                        "body",
                        "rear_body",
                        scene_gain=0.36,
                        scene_noise_gain=1.00,
                        amp_scale=0.66,
                        noise_scale=1.00,
                        common_event_gain=0.12,
                    ),
                ),
            ),
            *_phase_with_hold(
                ScenarioPhase(
                    name="rumble-window",
                    duration_s=5.0,
                    speed_start_kmh=92.0,
                    speed_end_kmh=96.0,
                    overrides=(
                        _state(
                            "all",
                            "wheel_mild_imbalance",
                            scene_gain=0.34,
                            scene_noise_gain=1.02,
                            amp_scale=0.60,
                            noise_scale=1.02,
                            common_event_gain=0.12,
                        ),
                        _state(
                            "rear-left",
                            "wheel_imbalance",
                            scene_gain=0.92,
                            scene_noise_gain=1.10,
                            amp_scale=1.04,
                            noise_scale=1.08,
                            common_event_gain=0.24,
                        ),
                        _state(
                            "left-side",
                            "wheel_mild_imbalance",
                            scene_gain=0.58,
                            scene_noise_gain=1.04,
                            amp_scale=0.84,
                            noise_scale=1.04,
                            common_event_gain=0.18,
                        ),
                        _state(
                            "body",
                            "rear_body",
                            scene_gain=0.42,
                            scene_noise_gain=1.02,
                            amp_scale=0.72,
                            noise_scale=1.02,
                            common_event_gain=0.14,
                        ),
                    ),
                    pulses=(
                        _pulse(1.0, "rear-left", 0.46),
                        _pulse(2.8, "rear-left", 0.58),
                        _pulse(4.2, "left-side", 0.22),
                    ),
                ),
                hold_name="rear-left-hold",
                hold_duration_s=4.0,
            ),
            ScenarioPhase(
                name="fade",
                duration_s=5.0,
                speed_start_kmh=96.0,
                speed_end_kmh=82.0,
                overrides=(
                    _state(
                        "all",
                        "rough_road",
                        scene_gain=0.24,
                        scene_noise_gain=0.98,
                        amp_scale=0.48,
                        noise_scale=0.98,
                        common_event_gain=0.08,
                    ),
                    _state(
                        "rear-left",
                        "wheel_mild_imbalance",
                        scene_gain=0.42,
                        scene_noise_gain=1.02,
                        amp_scale=0.72,
                        noise_scale=1.02,
                        common_event_gain=0.14,
                    ),
                ),
            ),
        ),
    ),
    "front-right-cruise-shimmy": ScriptedScenario(
        name="front-right-cruise-shimmy",
        description="Steady highway cruise with intermittent front-right wheel shimmy bursts.",
        phases=(
            ScenarioPhase(
                name="approach",
                duration_s=5.0,
                speed_start_kmh=72.0,
                speed_end_kmh=82.0,
                overrides=(
                    _state(
                        "all",
                        "wheel_mild_imbalance",
                        scene_gain=0.28,
                        scene_noise_gain=1.00,
                        amp_scale=0.56,
                        noise_scale=1.00,
                        common_event_gain=0.10,
                    ),
                    _state(
                        "body",
                        "rear_body",
                        scene_gain=0.32,
                        scene_noise_gain=1.00,
                        amp_scale=0.60,
                        noise_scale=1.00,
                        common_event_gain=0.10,
                    ),
                ),
            ),
            *_phase_with_hold(
                ScenarioPhase(
                    name="shimmy-window",
                    duration_s=5.0,
                    speed_start_kmh=82.0,
                    speed_end_kmh=84.0,
                    overrides=(
                        _state(
                            "all",
                            "wheel_mild_imbalance",
                            scene_gain=0.32,
                            scene_noise_gain=1.02,
                            amp_scale=0.60,
                            noise_scale=1.02,
                            common_event_gain=0.12,
                        ),
                        _state(
                            "body",
                            "rear_body",
                            scene_gain=0.40,
                            scene_noise_gain=1.02,
                            amp_scale=0.70,
                            noise_scale=1.02,
                            common_event_gain=0.14,
                        ),
                        _state(
                            "front-right",
                            "wheel_imbalance",
                            scene_gain=0.90,
                            scene_noise_gain=1.10,
                            amp_scale=1.02,
                            noise_scale=1.08,
                            common_event_gain=0.24,
                        ),
                    ),
                    pulses=(
                        _pulse(0.8, "front-right", 0.52),
                        _pulse(2.2, "front-right", 0.72),
                        _pulse(4.1, "front-right", 0.66),
                    ),
                ),
                hold_name="shimmy-hold",
                hold_duration_s=4.0,
            ),
            ScenarioPhase(
                name="linger",
                duration_s=5.0,
                speed_start_kmh=84.0,
                speed_end_kmh=84.0,
                overrides=(
                    _state(
                        "all",
                        "wheel_mild_imbalance",
                        scene_gain=0.26,
                        scene_noise_gain=0.98,
                        amp_scale=0.50,
                        noise_scale=0.98,
                        common_event_gain=0.08,
                    ),
                    _state(
                        "front-right",
                        "wheel_mild_imbalance",
                        scene_gain=0.48,
                        scene_noise_gain=1.02,
                        amp_scale=0.74,
                        noise_scale=1.02,
                        common_event_gain=0.14,
                    ),
                    _state(
                        "body",
                        "rear_body",
                        scene_gain=0.30,
                        scene_noise_gain=0.99,
                        amp_scale=0.58,
                        noise_scale=0.99,
                        common_event_gain=0.10,
                    ),
                ),
                pulses=(_pulse(1.8, "front-right", 0.30),),
            ),
            ScenarioPhase(
                name="cooldown",
                duration_s=4.0,
                speed_start_kmh=84.0,
                speed_end_kmh=70.0,
                overrides=(
                    _state(
                        "all",
                        "rough_road",
                        scene_gain=0.24,
                        scene_noise_gain=0.98,
                        amp_scale=0.48,
                        noise_scale=0.98,
                        common_event_gain=0.08,
                    ),
                    _state(
                        "body",
                        "rear_body",
                        scene_gain=0.28,
                        scene_noise_gain=0.99,
                        amp_scale=0.56,
                        noise_scale=0.99,
                        common_event_gain=0.08,
                    ),
                ),
            ),
        ),
    ),
    "driveline-coastdown": ScriptedScenario(
        name="driveline-coastdown",
        description="Engine-order pull followed by a driveline-heavy coastdown rumble.",
        phases=(
            *_phase_with_hold(
                ScenarioPhase(
                    name="pull",
                    duration_s=6.0,
                    speed_start_kmh=42.0,
                    speed_end_kmh=96.0,
                    overrides=(
                        _state(
                            "all",
                            "engine_order",
                            scene_gain=0.74,
                            scene_noise_gain=1.02,
                            amp_scale=0.96,
                            noise_scale=1.00,
                            common_event_gain=0.18,
                        ),
                        _state(
                            "body",
                            "rear_body",
                            scene_gain=0.48,
                            scene_noise_gain=1.00,
                            amp_scale=0.74,
                            noise_scale=1.00,
                            common_event_gain=0.16,
                        ),
                    ),
                    pulses=(_pulse(2.5, "rear-axle", 0.22),),
                ),
                hold_name="pull-hold",
                hold_duration_s=3.0,
            ),
            *_phase_with_hold(
                ScenarioPhase(
                    name="coast-rumble",
                    duration_s=6.0,
                    speed_start_kmh=96.0,
                    speed_end_kmh=84.0,
                    overrides=(
                        _state(
                            "all",
                            "engine_order",
                            scene_gain=0.58,
                            scene_noise_gain=1.04,
                            amp_scale=0.86,
                            noise_scale=1.02,
                            common_event_gain=0.28,
                        ),
                        _state(
                            "rear-axle",
                            "wheel_mild_imbalance",
                            scene_gain=0.62,
                            scene_noise_gain=1.06,
                            amp_scale=0.88,
                            noise_scale=1.04,
                            common_event_gain=0.30,
                        ),
                        _state(
                            "body",
                            "rear_body",
                            scene_gain=0.56,
                            scene_noise_gain=1.06,
                            amp_scale=0.82,
                            noise_scale=1.04,
                            common_event_gain=0.30,
                        ),
                    ),
                    pulses=(
                        _pulse(1.8, "rear-axle", 0.42),
                        _pulse(4.7, "all", 0.24),
                        _pulse(6.0, "body", 0.30),
                    ),
                ),
                hold_name="coast-hold",
                hold_duration_s=3.0,
            ),
            ScenarioPhase(
                name="settled-roll",
                duration_s=5.0,
                speed_start_kmh=84.0,
                speed_end_kmh=34.0,
                overrides=(
                    _state(
                        "all",
                        "rough_road",
                        scene_gain=0.24,
                        scene_noise_gain=0.98,
                        amp_scale=0.48,
                        noise_scale=0.98,
                        common_event_gain=0.08,
                    ),
                    _state(
                        "body",
                        "rear_body",
                        scene_gain=0.30,
                        scene_noise_gain=0.98,
                        amp_scale=0.58,
                        noise_scale=0.98,
                        common_event_gain=0.10,
                    ),
                ),
            ),
        ),
    ),
    "dual-fault-recovery": ScriptedScenario(
        name="dual-fault-recovery",
        description="Two temporary faults appear in sequence, then both fade back to baseline.",
        phases=(
            *_phase_with_hold(
                ScenarioPhase(
                    name="front-phase",
                    duration_s=5.0,
                    speed_start_kmh=36.0,
                    speed_end_kmh=72.0,
                    overrides=(
                        _state(
                            "all",
                            "wheel_mild_imbalance",
                            scene_gain=0.34,
                            scene_noise_gain=1.00,
                            amp_scale=0.62,
                            noise_scale=1.00,
                            common_event_gain=0.12,
                        ),
                        _state(
                            "body",
                            "rear_body",
                            scene_gain=0.40,
                            scene_noise_gain=1.00,
                            amp_scale=0.70,
                            noise_scale=1.00,
                            common_event_gain=0.14,
                        ),
                        _state(
                            "front-left",
                            "wheel_imbalance",
                            scene_gain=0.84,
                            scene_noise_gain=1.08,
                            amp_scale=1.00,
                            noise_scale=1.06,
                            common_event_gain=0.22,
                        ),
                    ),
                    pulses=(
                        _pulse(1.8, "front-left", 0.56),
                        _pulse(4.0, "front-left", 0.44),
                    ),
                ),
                hold_name="front-hold",
                hold_duration_s=3.0,
            ),
            *_phase_with_hold(
                ScenarioPhase(
                    name="rear-phase",
                    duration_s=5.0,
                    speed_start_kmh=72.0,
                    speed_end_kmh=88.0,
                    overrides=(
                        _state(
                            "all",
                            "wheel_mild_imbalance",
                            scene_gain=0.36,
                            scene_noise_gain=1.02,
                            amp_scale=0.64,
                            noise_scale=1.02,
                            common_event_gain=0.12,
                        ),
                        _state(
                            "body",
                            "rear_body",
                            scene_gain=0.46,
                            scene_noise_gain=1.04,
                            amp_scale=0.76,
                            noise_scale=1.02,
                            common_event_gain=0.16,
                        ),
                        _state(
                            "rear-right",
                            "wheel_imbalance",
                            scene_gain=0.82,
                            scene_noise_gain=1.08,
                            amp_scale=0.98,
                            noise_scale=1.06,
                            common_event_gain=0.22,
                        ),
                    ),
                    pulses=(
                        _pulse(1.5, "rear-right", 0.52),
                        _pulse(3.6, "rear-right", 0.48),
                        _pulse(4.8, "body", 0.24),
                    ),
                ),
                hold_name="rear-hold",
                hold_duration_s=3.0,
            ),
            ScenarioPhase(
                name="recovery",
                duration_s=7.0,
                speed_start_kmh=88.0,
                speed_end_kmh=58.0,
                overrides=(
                    _state(
                        "all",
                        "rough_road",
                        scene_gain=0.22,
                        scene_noise_gain=0.96,
                        amp_scale=0.44,
                        noise_scale=0.96,
                        common_event_gain=0.06,
                    ),
                    _state(
                        "body",
                        "rear_body",
                        scene_gain=0.28,
                        scene_noise_gain=0.96,
                        amp_scale=0.54,
                        noise_scale=0.96,
                        common_event_gain=0.08,
                    ),
                ),
            ),
        ),
    ),
}
