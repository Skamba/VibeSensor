from __future__ import annotations

from vibesensor.adapters.simulator.scripted_scenario_models import ScenarioPhase
from vibesensor.adapters.simulator.sim_client import SimClient
from vibesensor.adapters.simulator.sim_scene import _normalize_wheel_slot

__all__ = ["apply_phase", "matches_scripted_target", "target_clients"]


def matches_scripted_target(client_name: str, target: str) -> bool:
    normalized_client = client_name.strip().lower().replace("_", "-").replace(" ", "-")
    normalized_target = target.strip().lower().replace("_", "-").replace(" ", "-")
    client_slot = _normalize_wheel_slot(client_name)
    target_slot = _normalize_wheel_slot(target)

    if normalized_target == "all":
        return True
    if normalized_target in {"wheels", "wheel"}:
        return client_slot is not None
    if normalized_target in {"body", "body-sensors"}:
        return client_slot is None
    if normalized_target == "front-axle":
        return client_slot is not None and client_slot.startswith("front-")
    if normalized_target == "rear-axle":
        return client_slot is not None and client_slot.startswith("rear-")
    if normalized_target == "left-side":
        return client_slot is not None and client_slot.endswith("-left")
    if normalized_target == "right-side":
        return client_slot is not None and client_slot.endswith("-right")
    if normalized_target == normalized_client:
        return True
    if target_slot is not None and client_slot == target_slot:
        return True
    return False


def target_clients(clients: list[SimClient], target: str) -> list[SimClient]:
    return [client for client in clients if matches_scripted_target(client.name, target)]


def apply_phase(clients: list[SimClient], scenario_name: str, phase: ScenarioPhase) -> None:
    scene_label = f"scripted:{scenario_name}:{phase.name}"
    for client in clients:
        client.scene_mode = scene_label
    for override in phase.overrides:
        for client in target_clients(clients, override.target):
            client.profile_name = override.profile_name
            client.scene_gain = override.scene_gain
            client.scene_noise_gain = override.scene_noise_gain
            client.amp_scale = override.amp_scale
            client.noise_scale = override.noise_scale
            client.common_event_gain = override.common_event_gain
