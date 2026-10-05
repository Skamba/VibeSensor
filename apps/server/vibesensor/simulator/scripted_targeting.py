from __future__ import annotations

from vibesensor.simulator.scripted_scenario_models import ScenarioPhase
from vibesensor.simulator.sim_client import SimClient
from vibesensor.simulator.sim_scene import _normalize_wheel_slot

__all__ = ["apply_phase", "matches_scripted_target", "target_clients", "target_specificity"]


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


_GROUP_TARGETS: frozenset[str] = frozenset(
    {
        "wheels",
        "wheel",
        "body",
        "body-sensors",
        "front-axle",
        "rear-axle",
        "left-side",
        "right-side",
    }
)


def target_specificity(target: str) -> int:
    """Rank a scripted target: ``all`` < sensor groups < one named sensor/corner."""
    normalized_target = target.strip().lower().replace("_", "-").replace(" ", "-")
    if normalized_target == "all":
        return 0
    if normalized_target in _GROUP_TARGETS:
        return 1
    return 2


def apply_phase(clients: list[SimClient], scenario_name: str, phase: ScenarioPhase) -> None:
    """Apply a phase's overrides, most specific target last.

    Overrides cascade by specificity rather than file order, so a
    single-corner fault (``rear-left``) is never silently replaced by a
    broader group override that also matches it (``left-side``). File order
    is kept among overrides of equal specificity.
    """
    scene_label = f"scripted:{scenario_name}:{phase.name}"
    for client in clients:
        client.scene_mode = scene_label
        client.gear_ratio = phase.gear_ratio
    for override in sorted(phase.overrides, key=lambda item: target_specificity(item.target)):
        for client in target_clients(clients, override.target):
            client.profile_name = override.profile_name
            client.scene_gain = override.scene_gain
            client.scene_noise_gain = override.scene_noise_gain
            client.amp_scale = override.amp_scale
            client.noise_scale = override.noise_scale
