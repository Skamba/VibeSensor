"""Simulated order tones must follow the server's active car, not the default profile."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import numpy as np
import pytest
from pytest_httpx import HTTPXMock
from test_support.httpx import add_json_response

from vibesensor.common.units import KMH_TO_MPS
from vibesensor.domain.analysis_settings import ANALYSIS_SETTINGS_DEFAULTS
from vibesensor.dsp.order_bands import vehicle_orders_hz
from vibesensor.settings.analysis_settings_codec import (
    analysis_settings_snapshot_from_mapping,
)
from vibesensor.simulator import sim_runtime
from vibesensor.simulator.profiles import DEFAULT_SPEED_KMH, SIMULATOR_CAR
from vibesensor.simulator.server_http import fetch_active_car
from vibesensor.simulator.sim_client import SimClient, make_client_id
from vibesensor.simulator.wheel_kinematics import DriveState, SimTire

_BMW_F30_320I = {
    **ANALYSIS_SETTINGS_DEFAULTS,
    "tire_width_mm": 225.0,
    "tire_aspect_pct": 45.0,
    "rim_in": 18.0,
    "final_drive_ratio": 3.077,
    "current_gear_ratio": 0.64,
}


def _bmw_orders_hz(speed_kmh: float) -> dict[str, float]:
    orders = vehicle_orders_hz(
        speed_mps=speed_kmh * KMH_TO_MPS,
        settings=analysis_settings_snapshot_from_mapping(_BMW_F30_320I),
    )
    assert orders is not None
    return orders


def test_fetch_active_car_drives_the_active_cars_tires_and_ratios(httpx_mock: HTTPXMock) -> None:
    add_json_response(
        httpx_mock,
        url="http://127.0.0.1:8000/api/settings/analysis",
        payload=_BMW_F30_320I,
    )

    car = fetch_active_car("127.0.0.1", 8000, 1.0)

    # New tires at their reference load roll as the analysis assumes for them,
    # to within the analysis's own 1 % tire-diameter uncertainty.
    expected = _bmw_orders_hz(DEFAULT_SPEED_KMH)
    cruise = DriveState(DEFAULT_SPEED_KMH)
    assert car is not None
    assert car.wheel_hz(None, cruise) == pytest.approx(expected["wheel_hz"], rel=0.01)
    assert car.shaft_hz(cruise) == pytest.approx(expected["drive_hz"], rel=0.01)
    assert car.engine_hz(cruise) == pytest.approx(expected["engine_hz"], rel=0.01)
    # The default car profile is several percent away from this car's wheel order.
    assert abs(car.wheel_hz(None, cruise) / SIMULATOR_CAR.wheel_hz(None, cruise) - 1.0) > 0.03


@pytest.mark.asyncio
async def test_active_car_order_loop_moves_wheel_tone_onto_active_car_wheel_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bmw = replace(
        SIMULATOR_CAR,
        tires=(SimTire(225.0, 45.0, 18.0),) * 4,
        final_drive_ratio=3.077,
        top_gear_ratio=0.64,
    )
    monkeypatch.setattr(sim_runtime, "fetch_active_car", lambda _host, _port, _timeout: bmw)
    client = SimClient(
        name="rear-left",
        client_id=make_client_id(3),
        control_port=9103,
        sample_rate_hz=800,
        frame_samples=200,
        server_host="127.0.0.1",
        server_data_port=9000,
        server_control_port=9001,
        profile_name="wheel_imbalance",
        noise_floor_std=0.0,
    )
    client.noise_scale = 0.0
    client.current_speed_kmh = 90.0
    stop_event = asyncio.Event()

    task = asyncio.create_task(
        sim_runtime.active_car_order_loop(
            [client],
            stop_event,
            server_host="127.0.0.1",
            server_http_port=8000,
            server_check_timeout=0.5,
            poll_interval_s=0.01,
        )
    )
    await asyncio.sleep(0.05)
    stop_event.set()
    await task

    assert client.car == bmw
    signal = np.concatenate([client.make_frame()[:, 0] for _ in range(40)]).astype(np.float64)
    freqs = np.fft.rfftfreq(signal.size, d=1.0 / client.sample_rate_hz)
    spectrum = np.abs(np.fft.rfft(signal))
    peak_hz = float(freqs[int(np.argmax(spectrum[1:])) + 1])
    expected_wheel_hz = _bmw_orders_hz(90.0)["wheel_hz"]
    assert peak_hz == pytest.approx(expected_wheel_hz, rel=0.01)
