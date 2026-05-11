"""Coverage for scripted multi-phase simulator scenarios."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from vibesensor.adapters.simulator import scripted_speed_sync
from vibesensor.adapters.simulator.scripted_scenario_catalog import (
    SCRIPTED_SCENARIOS,
    scripted_scenario_names,
)
from vibesensor.adapters.simulator.scripted_scenario_models import (
    PhaseOverride,
    PhasePulse,
    ScenarioPhase,
    ScriptedScenario,
)
from vibesensor.adapters.simulator.scripted_scenarios import run_scripted_scenario
from vibesensor.adapters.simulator.scripted_targeting import apply_phase


class _FakeSimClient:
    def __init__(self, name: str) -> None:
        self.name = name
        self.profile_name = "rough_road"
        self.scene_mode = ""
        self.scene_gain = 0.0
        self.scene_noise_gain = 0.0
        self.common_event_gain = 0.0
        self.amp_scale = 0.0
        self.noise_scale = 0.0
        self.current_speed_kmh = 0.0
        self.bump_state = np.zeros(3, dtype=np.float32)
        self.pulses: list[float] = []

    def pulse(self, strength: float) -> None:
        self.pulses.append(strength)
        self.bump_state += np.asarray([strength, strength, strength], dtype=np.float32)


def _make_clients() -> list[_FakeSimClient]:
    return [
        _FakeSimClient("front-left"),
        _FakeSimClient("front-right"),
        _FakeSimClient("rear-left"),
        _FakeSimClient("rear-right"),
        _FakeSimClient("trunk"),
    ]


def test_scripted_scenario_catalog_exposes_ten_complex_runs() -> None:
    assert {
        "accel-front-left-surge",
        "coastdown-rear-right-rumble",
        "highway-window-shudder",
        "launch-engine-flare",
        "pothole-recovery-loop",
        "lane-change-left-right",
        "rear-left-cruise-rumble",
        "front-right-cruise-shimmy",
        "driveline-coastdown",
        "dual-fault-recovery",
    } <= set(scripted_scenario_names())


def test_scripted_scenarios_include_explicit_steady_speed_hold_phases() -> None:
    assert all(
        any(phase.speed_start_kmh == phase.speed_end_kmh for phase in scenario.phases)
        for scenario in SCRIPTED_SCENARIOS.values()
    )


def test_accel_front_left_surge_phase_targets_front_left_and_body_sensors() -> None:
    clients = _make_clients()
    phase = SCRIPTED_SCENARIOS["accel-front-left-surge"].phases[1]

    apply_phase(clients, "accel-front-left-surge", phase)

    front_left = next(client for client in clients if client.name == "front-left")
    front_right = next(client for client in clients if client.name == "front-right")
    trunk = next(client for client in clients if client.name == "trunk")

    assert front_left.profile_name == "wheel_imbalance"
    assert front_left.scene_gain > front_right.scene_gain
    assert trunk.profile_name == "rear_body"
    assert all(
        client.scene_mode == "scripted:accel-front-left-surge:surge-window" for client in clients
    )


@pytest.mark.asyncio
async def test_run_scripted_scenario_advances_speed_and_fires_temporary_pulses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients = [_FakeSimClient("front-left"), _FakeSimClient("trunk")]
    speed_updates: list[float] = []

    def fake_set_server_speed_override_kmh(
        host: str,
        port: int,
        speed_kmh: float,
        timeout_s: float,
    ) -> float:
        speed_updates.append(speed_kmh)
        return speed_kmh

    monkeypatch.setattr(
        scripted_speed_sync,
        "set_server_speed_override_kmh",
        fake_set_server_speed_override_kmh,
    )
    monkeypatch.setitem(
        SCRIPTED_SCENARIOS,
        "unit-test-scripted",
        ScriptedScenario(
            name="unit-test-scripted",
            description="Short async test scenario.",
            phases=(
                ScenarioPhase(
                    name="burst",
                    duration_s=0.05,
                    speed_start_kmh=20.0,
                    speed_end_kmh=50.0,
                    overrides=(
                        PhaseOverride(
                            target="all",
                            profile_name="rough_road",
                            scene_gain=0.3,
                            scene_noise_gain=1.0,
                            amp_scale=0.6,
                            noise_scale=1.0,
                            common_event_gain=0.1,
                        ),
                        PhaseOverride(
                            target="front-left",
                            profile_name="wheel_mild_imbalance",
                            scene_gain=0.8,
                            scene_noise_gain=1.0,
                            amp_scale=1.0,
                            noise_scale=1.0,
                            common_event_gain=0.2,
                        ),
                    ),
                    pulses=(PhasePulse(at_s=0.02, target="front-left", strength=0.4),),
                ),
            ),
        ),
    )

    stop_event = asyncio.Event()
    task = asyncio.create_task(
        run_scripted_scenario(
            clients,
            "unit-test-scripted",
            stop_event,
            server_host="127.0.0.1",
            server_http_port=8000,
            server_check_timeout=0.1,
            speed_update_period_s=0.01,
        )
    )
    await asyncio.sleep(0.08)
    stop_event.set()
    await task

    front_left = clients[0]
    assert speed_updates
    assert max(speed_updates) >= 45.0
    assert front_left.pulses
    assert float(front_left.bump_state.sum()) > 0.0
