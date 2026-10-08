"""Coverage for scripted multi-phase simulator scenarios."""

from __future__ import annotations

import asyncio
import time

import numpy as np
import pytest

from vibesensor.simulator import scripted_scenarios, scripted_speed_sync
from vibesensor.simulator.profiles import PROFILE_LIBRARY
from vibesensor.simulator.scripted_scenario_catalog import (
    SCRIPTED_SCENARIOS,
    scripted_scenario_names,
)
from vibesensor.simulator.scripted_scenario_models import (
    PhaseOverride,
    PhasePulse,
    ScenarioPhase,
    ScriptedScenario,
)
from vibesensor.simulator.scripted_scenarios import run_scripted_scenario
from vibesensor.simulator.scripted_targeting import apply_phase


class _FakeSimClient:
    def __init__(self, name: str) -> None:
        self.name = name
        self.profile_name = "rough_road"
        self.scene_mode = ""
        self.scene_gain = 0.0
        self.scene_noise_gain = 0.0
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


def test_scripted_scenarios_use_known_profiles() -> None:
    for scenario in SCRIPTED_SCENARIOS.values():
        for phase in scenario.phases:
            for override in phase.overrides:
                assert override.profile_name in PROFILE_LIBRARY, (scenario.name, phase.name)


def test_fault_free_scenario_injects_no_tones() -> None:
    for phase in SCRIPTED_SCENARIOS["pothole-recovery-loop"].phases:
        for override in phase.overrides:
            profile = PROFILE_LIBRARY[override.profile_name]
            assert not profile.tones and not profile.order_tones, (phase.name, override.target)


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
                        ),
                        PhaseOverride(
                            target="front-left",
                            profile_name="wheel_mild_imbalance",
                            scene_gain=0.8,
                            scene_noise_gain=1.0,
                            amp_scale=1.0,
                            noise_scale=1.0,
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
            gps_feed=False,
            speed_update_period_s=0.01,
        )
    )
    front_left = clients[0]
    # Wait for the observable effects instead of a fixed wall-clock window: the
    # speed sync runs in a worker thread and may lag on a loaded machine.
    deadline = time.monotonic() + 10.0
    while not (speed_updates and max(speed_updates) >= 45.0 and front_left.pulses):
        if task.done() or time.monotonic() > deadline:
            break
        await asyncio.sleep(0.005)
    stop_event.set()
    await task

    assert speed_updates
    assert max(speed_updates) >= 45.0
    assert front_left.pulses
    assert float(front_left.bump_state.sum()) > 0.0


@pytest.mark.asyncio
async def test_run_scripted_scenario_retries_speed_sync_after_a_failed_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One slow server response must not freeze the server's speed for the run."""
    attempts: list[float] = []

    def flaky_set_server_speed_override_kmh(
        host: str,
        port: int,
        speed_kmh: float,
        timeout_s: float,
    ) -> float:
        attempts.append(speed_kmh)
        if len(attempts) == 1:
            raise TimeoutError("timed out")
        return speed_kmh

    monkeypatch.setattr(
        scripted_speed_sync,
        "set_server_speed_override_kmh",
        flaky_set_server_speed_override_kmh,
    )
    override = PhaseOverride(
        target="all",
        profile_name="rough_road",
        scene_gain=0.3,
        scene_noise_gain=1.0,
        amp_scale=0.6,
        noise_scale=1.0,
    )
    monkeypatch.setitem(
        SCRIPTED_SCENARIOS,
        "unit-test-hold",
        ScriptedScenario(
            name="unit-test-hold",
            description="Constant-speed hold.",
            phases=(ScenarioPhase("hold", 5.0, 60.0, 60.0, (override,)),),
        ),
    )
    stop_event = asyncio.Event()
    task = asyncio.create_task(
        run_scripted_scenario(
            _make_clients(),
            "unit-test-hold",
            stop_event,
            server_host="127.0.0.1",
            server_http_port=8000,
            server_check_timeout=0.1,
            gps_feed=False,
            speed_update_period_s=0.01,
        )
    )
    async with asyncio.timeout(5.0):
        while len(attempts) < 2:
            await asyncio.sleep(0.01)
    stop_event.set()
    await task

    assert attempts[:2] == [60.0, 60.0]


@pytest.mark.asyncio
async def test_run_scripted_scenario_marks_guided_phases_on_the_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marks: list[str | None] = []
    monkeypatch.setattr(scripted_speed_sync, "set_server_speed_override_kmh", lambda *_args: None)
    monkeypatch.setattr(
        scripted_scenarios,
        "mark_server_guided_phase",
        lambda _host, _port, phase, _timeout: marks.append(phase),
    )
    override = PhaseOverride(
        target="all",
        profile_name="rough_road",
        scene_gain=0.3,
        scene_noise_gain=1.0,
        amp_scale=0.6,
        noise_scale=1.0,
    )
    monkeypatch.setitem(
        SCRIPTED_SCENARIOS,
        "unit-test-guided",
        ScriptedScenario(
            name="unit-test-guided",
            description="Guided phases then an unguided cool-down.",
            phases=(
                ScenarioPhase("sweep", 0.02, 50.0, 90.0, (override,), guided_phase="sweep"),
                ScenarioPhase("coast", 0.02, 90.0, 70.0, (override,), guided_phase="coast_down"),
                ScenarioPhase("cool-down", 0.02, 70.0, 70.0, (override,)),
            ),
        ),
    )
    stop_event = asyncio.Event()
    task = asyncio.create_task(
        run_scripted_scenario(
            _make_clients(),
            "unit-test-guided",
            stop_event,
            server_host="127.0.0.1",
            server_http_port=8000,
            server_check_timeout=0.1,
            gps_feed=False,
            speed_update_period_s=0.01,
        )
    )
    async with asyncio.timeout(5.0):
        while len(marks) < 3:
            await asyncio.sleep(0.01)
    stop_event.set()
    await task

    assert marks[:3] == ["sweep", "coast_down", None]


@pytest.mark.asyncio
async def test_unguided_scenario_never_marks_guided_phases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marks: list[str | None] = []
    monkeypatch.setattr(scripted_speed_sync, "set_server_speed_override_kmh", lambda *_args: None)
    monkeypatch.setattr(
        scripted_scenarios,
        "mark_server_guided_phase",
        lambda _host, _port, phase, _timeout: marks.append(phase),
    )
    stop_event = asyncio.Event()
    task = asyncio.create_task(
        run_scripted_scenario(
            _make_clients(),
            "rear-left-cruise-rumble",
            stop_event,
            server_host="127.0.0.1",
            server_http_port=8000,
            server_check_timeout=0.1,
            gps_feed=False,
            speed_update_period_s=0.01,
        )
    )
    await asyncio.sleep(0.02)
    stop_event.set()
    await task

    assert marks == []


@pytest.mark.asyncio
async def test_a_slow_guided_step_marker_marks_each_step_once_and_never_stretches_the_drive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A loaded server takes 0.3 s to take each mark. The drive keeps its script:
    # four 0.2 s phases still take 0.8 s, and the brake step is marked once, as
    # the driver taps it, not at each of its phases.
    marks: list[tuple[str | None, float]] = []
    started = time.monotonic()

    def slow_mark(_host: str, _port: int, phase: str | None, _timeout: float) -> None:
        marks.append((phase, time.monotonic() - started))
        time.sleep(0.3)

    monkeypatch.setattr(scripted_speed_sync, "set_server_speed_override_kmh", lambda *_args: None)
    monkeypatch.setattr(scripted_scenarios, "mark_server_guided_phase", slow_mark)
    override = PhaseOverride(
        target="all",
        profile_name="rough_road",
        scene_gain=0.3,
        scene_noise_gain=1.0,
        amp_scale=0.6,
        noise_scale=1.0,
    )
    monkeypatch.setitem(
        SCRIPTED_SCENARIOS,
        "unit-test-brake-step",
        ScriptedScenario(
            name="unit-test-brake-step",
            description="A sweep, then a brake step of three phases.",
            phases=(
                ScenarioPhase("sweep", 0.2, 50.0, 90.0, (override,), guided_phase="sweep"),
                ScenarioPhase("slow-down", 0.2, 90.0, 80.0, (override,), guided_phase="brake"),
                ScenarioPhase("stop", 0.2, 80.0, 20.0, (override,), guided_phase="brake"),
                ScenarioPhase("speed-up", 0.2, 20.0, 80.0, (override,), guided_phase="brake"),
            ),
        ),
    )
    stop_event = asyncio.Event()
    task = asyncio.create_task(
        run_scripted_scenario(
            _make_clients(),
            "unit-test-brake-step",
            stop_event,
            server_host="127.0.0.1",
            server_http_port=8000,
            server_check_timeout=0.1,
            gps_feed=False,
            speed_update_period_s=0.01,
        )
    )
    async with asyncio.timeout(5.0):
        while len(marks) < 3:
            await asyncio.sleep(0.01)
    stop_event.set()
    await task

    assert [phase for phase, _ in marks] == ["sweep", "brake", "sweep"]
    # The second pass starts on schedule at 0.8 s; marking every phase and
    # starting each after its mark took 2 s.
    assert marks[2][1] < 1.4
