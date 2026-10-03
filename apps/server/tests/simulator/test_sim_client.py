"""Deterministic frame-generation coverage for the simulator client."""

from __future__ import annotations

import numpy as np
import pytest

from vibesensor.live.compute import SignalMetricsComputer
from vibesensor.live.models import ProcessorConfig
from vibesensor.simulator.commands import (
    apply_one_wheel_mild_scenario,
    apply_road_fixed_scenario,
)
from vibesensor.simulator.profiles import DEFAULT_ORDER_HZ
from vibesensor.simulator.sim_client import SimClient, make_client_id

_TEST_PROCESSOR_CONFIG = ProcessorConfig(
    sample_rate_hz=800,
    waveform_seconds=4,
    waveform_display_hz=4,
    fft_n=200,
    spectrum_min_hz=0.0,
    spectrum_max_hz=200.0,
    accel_scale_g_per_lsb=None,
)


_SENSORS = ("front-left", "front-right", "rear-left", "rear-right", "trunk")


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


def _measure_p95_strength_db(
    client: SimClient,
    *,
    frames: int = 60,
) -> float:
    computer = SignalMetricsComputer(_TEST_PROCESSOR_CONFIG)
    strengths: list[float] = []
    for _ in range(frames):
        frame = client.make_frame().astype(np.float32).T
        result = computer.compute_fft_spectrum(frame, client.sample_rate_hz)
        strengths.append(float(result["strength_metrics"]["vibration_strength_db"]))
    return float(np.percentile(strengths, 95))


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


def _order_prominence(client: SimClient, order_hz: float) -> float:
    """Return the order bin's magnitude over the median of its +/-5 Hz neighbourhood."""
    frames = [client.make_frame().astype(np.float32) for _ in range(20)]
    signal = np.concatenate(frames, axis=0)[:, 0]
    freqs = np.fft.rfftfreq(signal.shape[0], d=1.0 / client.sample_rate_hz)
    spectrum = np.abs(np.fft.rfft(signal))
    order_index = int(np.argmin(np.abs(freqs - order_hz)))
    neighbourhood = spectrum[(np.abs(freqs - order_hz) <= 5.0) & (np.abs(freqs - order_hz) > 1.0)]
    return float(spectrum[order_index] / np.median(neighbourhood))


def test_fault_free_road_carries_no_order_tones() -> None:
    clients = [_make_client(seed=seed, name=name) for seed, name in enumerate(_SENSORS, start=1)]
    apply_road_fixed_scenario(clients)

    for client in clients:
        for order_key, order_hz in DEFAULT_ORDER_HZ.items():
            prominence = _order_prominence(client, order_hz)
            assert prominence < 4.0, (client.name, order_key, prominence)


def test_one_wheel_fault_injects_only_wheel_orders() -> None:
    clients = [_make_client(seed=seed, name=name) for seed, name in enumerate(_SENSORS, start=1)]
    apply_one_wheel_mild_scenario(clients, "front-right")
    fault = next(client for client in clients if client.name == "front-right")

    assert _order_prominence(fault, DEFAULT_ORDER_HZ["wheel_1x"]) > 20.0
    # engine_1x is left out: on the default car it sits within 0.4 Hz of wheel_2x.
    for client in clients:
        for order_key in ("shaft_1x", "engine_2x"):
            prominence = _order_prominence(client, DEFAULT_ORDER_HZ[order_key])
            assert prominence < 4.0, (client.name, order_key, prominence)


@pytest.mark.parametrize("fault_wheel", ["front-left", "front-right", "rear-left"])
def test_one_wheel_runs_keep_fault_corner_strongest_by_p95(fault_wheel: str) -> None:
    clients = [
        _make_client(seed=1, name="front-left"),
        _make_client(seed=2, name="front-right"),
        _make_client(seed=3, name="rear-left"),
        _make_client(seed=4, name="rear-right"),
    ]
    apply_one_wheel_mild_scenario(clients, fault_wheel)

    p95_by_name = {client.name: _measure_p95_strength_db(client) for client in clients}

    assert max(p95_by_name, key=p95_by_name.get) == fault_wheel
