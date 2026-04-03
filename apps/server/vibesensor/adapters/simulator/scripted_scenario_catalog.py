from __future__ import annotations

from vibesensor.adapters.simulator.scripted_scenario_loader import load_scripted_scenarios
from vibesensor.adapters.simulator.scripted_scenario_models import ScriptedScenario

__all__ = [
    "SCRIPTED_SCENARIOS",
    "get_scripted_scenario",
    "is_scripted_scenario",
    "scripted_scenario_help",
    "scripted_scenario_names",
]

SCRIPTED_SCENARIOS: dict[str, ScriptedScenario] = load_scripted_scenarios()


def get_scripted_scenario(name: str) -> ScriptedScenario:
    return SCRIPTED_SCENARIOS[name]


def is_scripted_scenario(name: str) -> bool:
    return name in SCRIPTED_SCENARIOS


def scripted_scenario_names() -> tuple[str, ...]:
    return tuple(SCRIPTED_SCENARIOS)


def scripted_scenario_help() -> str:
    return "\n".join(
        f"  {scenario.name}: {scenario.description}" for scenario in SCRIPTED_SCENARIOS.values()
    )
