"""Road-scene controller coverage for single-active simulator behavior."""

from __future__ import annotations

import numpy as np

from vibesensor.adapters.simulator.sim_scene import RoadSceneController


class _FakeSimClient:
    def __init__(self, name: str, *, profile_name: str = "rough_road") -> None:
        self.name = name
        self.profile_name = profile_name
        self.scene_mode = ""
        self.scene_gain = 0.0
        self.scene_noise_gain = 0.0
        self.common_event_gain = 0.0
        self.amp_scale = 0.0
        self.noise_scale = 0.0
        self.bump_state = np.zeros(3, dtype=np.float32)

    def pulse(self, strength: float) -> None:
        self.bump_state += np.asarray([strength, strength, strength], dtype=np.float32)


def test_single_active_keeps_non_active_clients_alive() -> None:
    clients = [
        _FakeSimClient("front-left"),
        _FakeSimClient("front-right"),
        _FakeSimClient("rear-left"),
        _FakeSimClient("rear-right"),
    ]
    controller = RoadSceneController(clients)

    controller._apply_single_active()

    active_clients = [client for client in clients if client.profile_name == "wheel_mild_imbalance"]
    assert len(active_clients) == 1
    for client in [client for client in clients if client.profile_name != "wheel_mild_imbalance"]:
        assert client.scene_gain >= 0.35
        assert client.common_event_gain >= 0.10
