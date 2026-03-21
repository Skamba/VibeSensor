from __future__ import annotations

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vibesensor.adapters.simulator.sim_client import SimClient

__all__ = ["RoadSceneController"]

_WHEEL_SLOT_ALIASES: dict[str, str] = {
    "fl": "front-left",
    "fr": "front-right",
    "rl": "rear-left",
    "rr": "rear-right",
}


class RoadSceneController:
    def __init__(self, clients: list[SimClient]):
        self.clients = clients
        self.rng = random.Random(2026)

    @staticmethod
    def _normalize_wheel_slot(name: str) -> str | None:
        normalized = name.strip().lower().replace("_", "-").replace(" ", "-")
        if normalized in _WHEEL_SLOT_ALIASES:
            return _WHEEL_SLOT_ALIASES[normalized]
        axle = "front" if "front" in normalized else "rear" if "rear" in normalized else None
        side = "left" if "left" in normalized else "right" if "right" in normalized else None
        if axle and side:
            return f"{axle}-{side}"
        return None

    @classmethod
    def _cross_corner_coupling(cls, source_name: str, sink_name: str) -> float:
        source = cls._normalize_wheel_slot(source_name)
        sink = cls._normalize_wheel_slot(sink_name)
        if source is None or sink is None:
            return 0.34
        if source == sink:
            return 1.0
        source_axle, source_side = source.split("-", maxsplit=1)
        sink_axle, sink_side = sink.split("-", maxsplit=1)
        if source_side == sink_side and source_axle != sink_axle:
            return 0.52
        if source_axle == sink_axle and source_side != sink_side:
            return 0.48
        return 0.40

    @staticmethod
    def _baseline_profile(name: str) -> str:
        normalized = name.strip().lower()
        if "rear" in normalized or "trunk" in normalized:
            return "rear_body"
        return "rough_road"

    def _apply_quiet(self) -> None:
        for client in self.clients:
            client.scene_mode = "quiet"
            client.profile_name = self._baseline_profile(client.name)
            client.scene_gain = self.rng.uniform(0.18, 0.30)
            client.scene_noise_gain = self.rng.uniform(0.88, 1.04)
            client.common_event_gain = self.rng.uniform(0.02, 0.06)
            client.amp_scale = self.rng.uniform(0.36, 0.55)
            client.noise_scale = self.rng.uniform(0.94, 1.08)

    def _apply_single_active(self) -> None:
        active_idx = self.rng.randrange(0, len(self.clients))
        active_name = self.clients[active_idx].name
        for i, client in enumerate(self.clients):
            client.scene_mode = "single"
            coupling = self._cross_corner_coupling(active_name, client.name)
            if i == active_idx:
                client.profile_name = "wheel_mild_imbalance"
                client.scene_gain = self.rng.uniform(0.78, 1.05)
                client.scene_noise_gain = self.rng.uniform(0.98, 1.14)
                client.amp_scale = self.rng.uniform(0.90, 1.08)
                client.noise_scale = self.rng.uniform(1.00, 1.12)
                client.common_event_gain = self.rng.uniform(0.18, 0.32)
                client.pulse(self.rng.uniform(0.28, 0.85))
            else:
                client.profile_name = self._baseline_profile(client.name)
                client.scene_gain = self.rng.uniform(0.28, 0.40) + 0.18 * coupling
                client.scene_noise_gain = self.rng.uniform(0.92, 1.08) + 0.06 * coupling
                client.amp_scale = self.rng.uniform(0.52, 0.70) + 0.22 * coupling
                client.noise_scale = self.rng.uniform(0.95, 1.06)
                client.common_event_gain = self.rng.uniform(0.06, 0.12) + 0.10 * coupling

    def _apply_all_active(self) -> None:
        pulse_strength = self.rng.uniform(0.22, 0.60)
        for client in self.clients:
            client.scene_mode = "all"
            client.profile_name = self._baseline_profile(client.name)
            client.scene_gain = self.rng.uniform(0.48, 0.74)
            client.scene_noise_gain = self.rng.uniform(0.94, 1.14)
            client.common_event_gain = self.rng.uniform(0.16, 0.34)
            client.amp_scale = self.rng.uniform(0.70, 0.94)
            client.noise_scale = self.rng.uniform(0.98, 1.12)
            client.pulse(pulse_strength * self.rng.uniform(0.90, 1.10))

    def _apply_all_sync_event(self) -> None:
        # Explicit synchronized but moderate all-sensor event for multi-sensor detection testing.
        base = self.rng.uniform(0.38, 0.58)
        pulse_strength = self.rng.uniform(0.25, 0.55)
        for client in self.clients:
            client.scene_mode = "all-sync"
            client.profile_name = self._baseline_profile(client.name)
            client.scene_gain = self.rng.uniform(0.52, 0.80)
            client.scene_noise_gain = self.rng.uniform(0.92, 1.12)
            client.common_event_gain = max(0.0, base + self.rng.uniform(-0.03, 0.03))
            client.amp_scale = self.rng.uniform(0.76, 0.98)
            client.noise_scale = self.rng.uniform(0.98, 1.10)
            client.pulse(pulse_strength * self.rng.uniform(0.90, 1.10))

    def _apply_highway_100_sync(self) -> None:
        # 640i-like synchronized event around 100 km/h across all sensors.
        base = self.rng.uniform(0.46, 0.70)
        pulse_strength = self.rng.uniform(0.20, 0.50)
        for client in self.clients:
            client.scene_mode = "highway100-sync"
            client.profile_name = (
                "wheel_mild_imbalance"
                if self._normalize_wheel_slot(client.name) is not None
                else "rear_body"
            )
            client.scene_gain = self.rng.uniform(0.54, 0.78)
            client.scene_noise_gain = self.rng.uniform(0.90, 1.08)
            client.common_event_gain = max(0.0, base + self.rng.uniform(-0.04, 0.04))
            client.amp_scale = self.rng.uniform(0.78, 1.00)
            client.noise_scale = self.rng.uniform(0.96, 1.08)
            client.pulse(pulse_strength * self.rng.uniform(0.85, 1.15))

    def next_scene(self) -> tuple[str, float]:
        mode = self.rng.choices(
            ["quiet", "single", "all", "all_sync", "highway100"],
            weights=[0.26, 0.24, 0.22, 0.16, 0.12],
            k=1,
        )[0]
        if mode == "quiet":
            self._apply_quiet()
            return mode, self.rng.uniform(5.0, 10.0)
        if mode == "single":
            self._apply_single_active()
            return mode, self.rng.uniform(4.5, 9.0)
        if mode == "all_sync":
            self._apply_all_sync_event()
            return mode, self.rng.uniform(2.4, 4.8)
        if mode == "highway100":
            self._apply_highway_100_sync()
            return mode, self.rng.uniform(3.2, 6.4)
        self._apply_all_active()
        return mode, self.rng.uniform(4.0, 8.0)
