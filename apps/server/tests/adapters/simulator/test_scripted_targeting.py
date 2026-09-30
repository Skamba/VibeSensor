from __future__ import annotations

from typing import cast

import pytest

from vibesensor.adapters.simulator.scripted_scenario_catalog import SCRIPTED_SCENARIOS
from vibesensor.adapters.simulator.scripted_targeting import (
    apply_phase,
    matches_scripted_target,
    target_specificity,
)
from vibesensor.adapters.simulator.sim_client import SimClient


@pytest.mark.parametrize(
    ("client_name", "target", "expected"),
    [
        ("front-left", "all", True),
        ("front-left", "front-axle", True),
        ("rear-left", "left-side", True),
        ("trunk", "body", True),
        ("front_left", "front-left", True),
        ("trunk", "front-axle", False),
        ("front-right", "rear-right", False),
    ],
)
def test_matches_scripted_target_supports_aliases_and_named_slots(
    client_name: str,
    target: str,
    expected: bool,
) -> None:
    assert matches_scripted_target(client_name, target) is expected


class _TargetClient:
    def __init__(self, name: str) -> None:
        self.name = name
        self.profile_name = "rough_road"
        self.scene_mode = ""
        self.scene_gain = 0.0
        self.scene_noise_gain = 0.0
        self.amp_scale = 0.0
        self.noise_scale = 0.0
        self.common_event_gain = 0.0


_CORNERS = ("front-left", "front-right", "rear-left", "rear-right")


def _apply(scenario_name: str, phase_name: str) -> dict[str, _TargetClient]:
    clients = [_TargetClient(name) for name in (*_CORNERS, "trunk")]
    phase = next(
        phase for phase in SCRIPTED_SCENARIOS[scenario_name].phases if phase.name == phase_name
    )
    apply_phase(cast("list[SimClient]", clients), scenario_name, phase)
    return {client.name: client for client in clients}


@pytest.mark.parametrize(
    ("scenario_name", "phase_name", "fault_corner"),
    [
        ("rear-left-cruise-rumble", "rumble-window", "rear-left"),
        ("rear-left-cruise-rumble", "rear-left-hold", "rear-left"),
        ("coastdown-rear-right-rumble", "coastdown-window", "rear-right"),
        ("coastdown-rear-right-rumble", "rear-right-hold", "rear-right"),
    ],
)
def test_named_fault_corner_is_not_overridden_by_its_side_group(
    scenario_name: str,
    phase_name: str,
    fault_corner: str,
) -> None:
    clients = _apply(scenario_name, phase_name)

    def excitation(name: str) -> float:
        return clients[name].scene_gain * clients[name].amp_scale

    assert clients[fault_corner].profile_name == "wheel_imbalance"
    assert max(_CORNERS, key=excitation) == fault_corner


@pytest.mark.parametrize("scenario_name", sorted(SCRIPTED_SCENARIOS))
def test_single_corner_overrides_win_over_group_overrides_in_every_phase(
    scenario_name: str,
) -> None:
    for phase in SCRIPTED_SCENARIOS[scenario_name].phases:
        clients = _apply(scenario_name, phase.name)
        for override in phase.overrides:
            if target_specificity(override.target) < 2:
                continue
            for name, client in clients.items():
                if not matches_scripted_target(name, override.target):
                    continue
                assert client.profile_name == override.profile_name
                assert client.scene_gain == override.scene_gain
                assert client.amp_scale == override.amp_scale


def test_target_specificity_orders_all_then_groups_then_single_targets() -> None:
    assert target_specificity("all") < target_specificity("left-side")
    assert target_specificity("body") < target_specificity("rear-left")
    assert target_specificity("front_axle") == target_specificity("wheels")
