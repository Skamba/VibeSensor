from __future__ import annotations

import asyncio

from vibesensor.adapters.simulator.scripted_scenario_library import (
    SCRIPTED_SCENARIOS,
    PhaseOverride,
    PhasePulse,
    ScenarioPhase,
    ScriptedScenario,
    is_scripted_scenario,
    phase_speed_kmh,
    scripted_scenario_help,
    scripted_scenario_names,
)
from vibesensor.adapters.simulator.scripted_speed_sync import apply_scripted_speed
from vibesensor.adapters.simulator.scripted_targeting import apply_phase, target_clients
from vibesensor.adapters.simulator.sim_client import SimClient

__all__ = [
    "SCRIPTED_SCENARIOS",
    "PhaseOverride",
    "PhasePulse",
    "ScenarioPhase",
    "ScriptedScenario",
    "apply_phase",
    "is_scripted_scenario",
    "phase_speed_kmh",
    "run_scripted_scenario",
    "scripted_scenario_help",
    "scripted_scenario_names",
]


def _pulse_order_key(pulse: PhasePulse) -> float:
    return pulse.at_s


async def run_scripted_scenario(
    clients: list[SimClient],
    scenario_name: str,
    stop_event: asyncio.Event,
    *,
    server_host: str,
    server_http_port: int,
    server_check_timeout: float,
    speed_update_period_s: float = 0.5,
) -> None:
    scenario = SCRIPTED_SCENARIOS[scenario_name]
    loop = asyncio.get_running_loop()
    server_speed_sync_enabled = True
    cycle = 0

    while not stop_event.is_set():
        cycle += 1
        print(f"[scenario] scripted={scenario.name} cycle={cycle} phases={len(scenario.phases)}")
        for phase in scenario.phases:
            if stop_event.is_set():
                return

            apply_phase(clients, scenario.name, phase)
            print(
                f"[scenario] phase={phase.name} "
                f"speed={phase.speed_start_kmh:.1f}->{phase.speed_end_kmh:.1f}km/h "
                f"duration={phase.duration_s:.1f}s"
            )
            pending_pulses = sorted(phase.pulses, key=_pulse_order_key)
            phase_start = loop.time()
            last_speed_kmh: float | None = None

            while not stop_event.is_set():
                elapsed_s = loop.time() - phase_start
                while pending_pulses and elapsed_s >= pending_pulses[0].at_s:
                    pulse = pending_pulses.pop(0)
                    for client in target_clients(clients, pulse.target):
                        client.pulse(pulse.strength)

                speed_kmh = phase_speed_kmh(phase, elapsed_s)
                if (
                    last_speed_kmh is None
                    or abs(speed_kmh - last_speed_kmh) >= 0.5
                    or elapsed_s >= phase.duration_s
                ):
                    speed_sync = await apply_scripted_speed(
                        clients,
                        speed_kmh,
                        server_host=server_host,
                        server_http_port=server_http_port,
                        server_check_timeout=server_check_timeout,
                        server_speed_sync_enabled=server_speed_sync_enabled,
                    )
                    if speed_sync.failure_message is not None:
                        print(speed_sync.failure_message)
                    server_speed_sync_enabled = speed_sync.server_speed_sync_enabled
                    last_speed_kmh = speed_kmh

                remaining_s = phase.duration_s - elapsed_s
                if remaining_s <= 0:
                    break
                await asyncio.sleep(min(speed_update_period_s, remaining_s))
