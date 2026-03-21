from __future__ import annotations

import numpy as np

from vibesensor.adapters.simulator.sim_client import SimClient, make_client_id


def _make_client(*, seed: int = 1) -> SimClient:
    return SimClient(
        name="front-left",
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
