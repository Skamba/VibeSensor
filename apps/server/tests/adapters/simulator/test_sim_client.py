"""Deterministic frame-generation coverage for the simulator client."""

from __future__ import annotations

import numpy as np

from vibesensor.adapters.simulator.commands import apply_one_wheel_mild_scenario
from vibesensor.adapters.simulator.profiles import DEFAULT_ORDER_HZ
from vibesensor.adapters.simulator.sim_client import SimClient, make_client_id


def _make_client(*, seed: int = 1, name: str = "front-left") -> SimClient:
    return SimClient(
        name=name,
        client_id=make_client_id(seed),
        control_port=9100 + seed,
        sample_rate_hz=800,
        frame_samples=200,
        server_host="127.0.0.1",
        server_data_port=9000,
        server_control_port=9001,
        profile_name="rough_road",
        noise_floor_std=3.5,
    )


def _measure_order_magnitude(client: SimClient, order_hz: float, *, axis: int = 0) -> float:
    frames = [client.make_frame().astype(np.float32) for _ in range(20)]
    signal = np.concatenate(frames, axis=0)
    sample_count = signal.shape[0]
    freqs = np.fft.rfftfreq(sample_count, d=1.0 / client.sample_rate_hz)
    order_index = int(np.argmin(np.abs(freqs - order_hz)))
    spectrum = np.fft.rfft(signal[:, axis])
    return float(np.abs(spectrum[order_index]) / sample_count)


def test_make_frame_is_deterministic_without_asyncio() -> None:
    client_a = _make_client(seed=1)
    client_b = _make_client(seed=1)

    np.testing.assert_array_equal(client_a.make_frame(), client_b.make_frame())


def test_make_frame_keeps_noise_floor_when_scene_gains_are_zero() -> None:
    client = _make_client(seed=2)
    client.scene_gain = 0.0
    client.scene_noise_gain = 0.0
    client.amp_scale = 0.0
    client.noise_scale = 0.0

    frame = client.make_frame()

    assert frame.dtype == np.int16
    assert np.abs(frame).sum() > 0


def test_common_shaft_tone_does_not_become_corner_dominant_in_one_wheel_runs() -> None:
    clients = [
        _make_client(seed=1, name="front-left"),
        _make_client(seed=2, name="front-right"),
        _make_client(seed=3, name="rear-left"),
        _make_client(seed=4, name="rear-right"),
        _make_client(seed=5, name="trunk"),
    ]
    apply_one_wheel_mild_scenario(clients, "front-right")

    for client in clients:
        client.noise_floor_std = 0.0
        client.scene_noise_gain = 0.0
        client.noise_scale = 0.0
        client.phase_offsets = np.zeros(3, dtype=np.float32)
        client.rng = np.random.default_rng(0)

    shaft_1x = DEFAULT_ORDER_HZ["shaft_1x"]
    magnitudes = {
        client.name: _measure_order_magnitude(client, shaft_1x)
        for client in clients
    }

    other_wheel_mean = np.mean(
        [
            magnitudes["front-left"],
            magnitudes["rear-left"],
            magnitudes["rear-right"],
        ]
    )
    assert magnitudes["front-right"] < magnitudes["front-left"] * 2.0
    assert magnitudes["front-right"] < other_wheel_mean * 2.0
