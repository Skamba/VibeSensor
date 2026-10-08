"""Physics of the simulator's first-drive confounders that the accuracy bench cannot see."""

from __future__ import annotations

import math

import numpy as np
import pytest

from vibesensor.ingest.sensor_units import ADXL345_SCALE_G_PER_LSB
from vibesensor.simulator.confounders import (
    AccessoryTone,
    FlatSpot,
    SensorConfounders,
    SensorFixing,
)

_FS = 800
_DT = 1.0 / _FS
_COUNTS_PER_MG = 1.0 / (1000.0 * ADXL345_SCALE_G_PER_LSB)
_WHEEL_HZ_AT_100 = 14.0


def _tone_mg(counts: np.ndarray, hz: float) -> float:
    """Vertical amplitude (mg) of the sine at *hz* in a whole number of its cycles."""
    t = np.arange(len(counts)) * _DT
    return float(2.0 * abs(np.mean(counts[:, 2] * np.exp(-2j * np.pi * hz * t)))) / _COUNTS_PER_MG


def _vertical_sine(hz: float, mg: float, seconds: float) -> np.ndarray:
    t = np.arange(int(seconds * _FS)) * _DT
    signal = np.zeros((t.size, 3))
    signal[:, 2] = mg * _COUNTS_PER_MG * np.sin(2.0 * np.pi * hz * t)
    return signal


def _through(fixing: SensorFixing, signal: np.ndarray) -> np.ndarray:
    """The signal read through *fixing*, frame by frame as the simulator does."""
    confounders = SensorConfounders(fixing=fixing)
    return np.concatenate(
        [confounders.through_fixing(frame, _FS) for frame in np.split(signal, len(signal) // 200)]
    )


@pytest.mark.parametrize(("hz", "low", "high"), [(5.0, 0.98, 1.02), (60.0, 9.6, 10.4)])
def test_springy_fixing_follows_the_car_below_its_ring_and_amplifies_at_it(
    hz: float, low: float, high: float
) -> None:
    # Base-excited oscillator: |T| = 1 well below resonance, about 1 / (2 zeta) at it.
    read = _through(SensorFixing(60.0, 0.05), _vertical_sine(hz, 10.0, 6.0))

    assert low <= _tone_mg(read[_FS * 2 :], hz) / 10.0 <= high


def test_springy_fixing_isolates_above_its_ring() -> None:
    read = _through(SensorFixing(60.0, 0.05), _vertical_sine(200.0, 10.0, 4.0))

    # Analytically 0.10 at 200 Hz; the bilinear warp only lowers it.
    assert _tone_mg(read[_FS:], 200.0) / 10.0 < 0.11


def test_loose_fixing_reads_like_a_firm_one_until_the_shake_lifts_it() -> None:
    loose = SensorFixing(35.0, 0.06, rattle_g=0.1)
    springy = SensorFixing(35.0, 0.06)
    gentle = _vertical_sine(15.0, 20.0, 2.0)

    np.testing.assert_allclose(_through(loose, gentle), _through(springy, gentle), atol=1e-9)


def test_loose_fixing_clips_and_rattles_past_its_hold_down() -> None:
    hold_counts = 100.0 * _COUNTS_PER_MG
    shake = _vertical_sine(15.0, 300.0, 4.0)
    loose = _through(SensorFixing(35.0, 0.06, rattle_g=0.1), shake)[_FS:]
    springy = _through(SensorFixing(35.0, 0.06), shake)[_FS:]

    # The 15 Hz shake reads under what the housing really feels (0.36 g) ...
    assert _tone_mg(loose, 15.0) < 0.8 * _tone_mg(springy, 15.0)
    # ... every landing rings the housing far past the hold-down ...
    assert np.max(np.abs(loose[:, 2])) > 10.0 * hold_counts
    # ... and lifting off symmetrically adds odd harmonics a linear fixing cannot, no even ones.
    assert _tone_mg(loose, 45.0) > 50.0
    assert _tone_mg(springy, 45.0) < 1.0
    assert _tone_mg(loose, 30.0) < 1.0


def _drive_flat_spot(spot: FlatSpot, km: float) -> tuple[SensorConfounders, np.ndarray]:
    """Drive *km* at 100 km/h; return the confounders and the last second's signal."""
    confounders = SensorConfounders(flat_spot=spot)
    frame = np.zeros((_FS, 3))
    for _ in range(max(1, round(km / 100.0 * 3600.0))):
        frame = confounders.mechanical(
            wheel_hz=_WHEEL_HZ_AT_100, engine_hz=40.0, speed_kmh=100.0, samples=_FS, dt=_DT
        )
    return confounders, frame


def test_flat_spot_shakes_at_the_first_wheel_orders_alike() -> None:
    _, first_second = _drive_flat_spot(FlatSpot(t1_mg=(0.0, 0.0, 80.0)), 0.0)

    assert _tone_mg(first_second, _WHEEL_HZ_AT_100) == pytest.approx(80.0, rel=0.02)
    for order in (2, 3, 4):
        # A dip one contact patch long is nearly an impulse: its harmonics fall off slowly.
        assert _tone_mg(first_second, order * _WHEEL_HZ_AT_100) > 0.9 * 80.0
    assert _tone_mg(first_second, 5 * _WHEEL_HZ_AT_100) < 1.0


@pytest.mark.parametrize(("km", "low", "high"), [(2.0, 0.5, 0.65), (24.0, 0.0, 0.05)])
def test_flat_spot_fades_over_the_first_kilometres(km: float, low: float, high: float) -> None:
    # The rubber's half recovers over 2 km, the cords' over 8 km (US 7,377,155 B2):
    # over 40 % gone after 2 km, gone after about 24 km of highway (Tire Rack).
    confounders, last_second = _drive_flat_spot(FlatSpot(t1_mg=(0.0, 0.0, 80.0)), km)

    assert confounders.distance_km == pytest.approx(km, rel=0.01)
    assert low <= _tone_mg(last_second, _WHEEL_HZ_AT_100) / 80.0 <= high


def _brake(confounders: SensorConfounders, decel_g: float, seconds: float) -> np.ndarray:
    """Brake from 120 km/h at *decel_g*; return the last half second's signal."""
    speed = 120.0
    frames = []
    for _ in range(int(seconds * 4)):
        speed -= decel_g * 9.80665 * 3.6 * 0.25
        frames.append(
            confounders.mechanical(
                wheel_hz=0.0, engine_hz=30.0, speed_kmh=speed, samples=200, dt=_DT
            )
        )
    return np.concatenate(frames[-2:])


@pytest.mark.parametrize(("decel_g", "expected_mg"), [(0.0, 0.0), (0.3, 0.0), (0.7, 20.0)])
def test_abs_pump_runs_only_in_a_stop_hard_enough_for_abs(
    decel_g: float, expected_mg: float
) -> None:
    pump = AccessoryTone(level_mg=(0.0, 0.0, 20.0), hz=60.0, min_decel_g=0.5)

    read = _brake(SensorConfounders(accessories=(pump,)), decel_g, 2.0)

    assert _tone_mg(read, 60.0) == pytest.approx(expected_mg, abs=0.5)


def test_engine_driven_compressor_follows_the_crank_and_its_clutch() -> None:
    compressor = AccessoryTone(level_mg=(0.0, 0.0, 8.0), engine_order=1.25, on_s=20.0, off_s=10.0)
    confounders = SensorConfounders(accessories=(compressor,))
    engine_hz = 40.0
    seconds = [
        confounders.mechanical(
            wheel_hz=0.0, engine_hz=engine_hz, speed_kmh=0.0, samples=_FS, dt=_DT
        )
        for _ in range(30)
    ]

    assert _tone_mg(seconds[5], 1.25 * engine_hz) == pytest.approx(8.0, rel=0.02)
    assert _tone_mg(seconds[25], 1.25 * engine_hz) == pytest.approx(0.0, abs=0.05)
    assert math.isclose(confounders.drive_s, 30.0)
