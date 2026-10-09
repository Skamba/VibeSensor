"""Physics of the simulator's road and sensor front end that the accuracy bench cannot see."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from scipy.signal import welch

from vibesensor.simulator.adxl345_front_end import Adxl345FrontEnd
from vibesensor.simulator.profiles import PROFILE_LIBRARY
from vibesensor.simulator.road_surface import RoadImpact, RoadSection, RoadSurface, uniform_road
from vibesensor.simulator.road_vibration import RoadVibration, SensorMount, mount_for_name
from vibesensor.simulator.sim_client import SimClient, make_client_id

_FS = 800
_FRAME = 200


def _vibration(mount: SensorMount, axle_share: float = 0.0, seed: int = 1) -> RoadVibration:
    return RoadVibration(
        mount=mount, axle_share=axle_share, sample_rate_hz=_FS, rng=np.random.default_rng(seed)
    )


def _drive_mg(
    vibration: RoadVibration, road: RoadSurface, speed_kmh: float, seconds: float
) -> np.ndarray:
    frames = []
    distance_m = 0.0
    for _ in range(int(seconds * _FS / _FRAME)):
        frames.append(vibration.frame_mg(road, distance_m, speed_kmh, _FRAME))
        distance_m += speed_kmh / 3.6 * _FRAME / _FS
    return np.concatenate(frames)


def _vertical_psd(signal_mg: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return welch(signal_mg[:, 2], fs=_FS, nperseg=2048)


def _band_peak_hz(freq: np.ndarray, psd: np.ndarray, low: float, high: float) -> float:
    band = (freq >= low) & (freq <= high)
    return float(freq[band][np.argmax(psd[band])])


def _band_level(freq: np.ndarray, psd: np.ndarray, low: float, high: float) -> float:
    band = (freq >= low) & (freq <= high)
    return float(np.mean(psd[band]))


def test_knuckle_rings_at_wheel_hop_and_falls_toward_200_hz() -> None:
    freq, psd = _vertical_psd(
        _drive_mg(_vibration(SensorMount.KNUCKLE), uniform_road("A"), 100, 60)
    )

    assert 10.0 <= _band_peak_hz(freq, psd, 3.0, 60.0) <= 14.0
    hop = _band_level(freq, psd, 10.0, 14.0)
    # Above wheel hop the tyre spring and the contact patch roll the road off:
    # over 15 dB less by 50 Hz, over 30 dB less by 180-200 Hz.
    assert _band_level(freq, psd, 45.0, 55.0) < hop / 30.0
    assert _band_level(freq, psd, 180.0, 200.0) < hop / 1000.0


def test_body_moves_at_the_ride_mode_and_barely_above_wheel_hop() -> None:
    body = _drive_mg(_vibration(SensorMount.BODY), uniform_road("A"), 100, 60)
    knuckle = _drive_mg(_vibration(SensorMount.KNUCKLE), uniform_road("A"), 100, 60)
    freq, body_psd = _vertical_psd(body)
    _freq, knuckle_psd = _vertical_psd(knuckle)

    assert 0.8 <= _band_peak_hz(freq, body_psd, 0.5, 5.0) <= 1.8
    # The suspension isolates the body: at 30-50 Hz it moves 30 dB less than the knuckle.
    assert (
        _band_level(freq, body_psd, 30.0, 50.0) < _band_level(freq, knuckle_psd, 30.0, 50.0) / 1000
    )


def test_powertrain_on_its_mounts_rings_near_10_hz() -> None:
    freq, psd = _vertical_psd(
        _drive_mg(_vibration(SensorMount.POWERTRAIN), uniform_road("A"), 100, 60)
    )

    assert 8.0 <= _band_peak_hz(freq, psd, 5.0, 40.0) <= 12.0


def test_each_rougher_iso_class_doubles_the_vibration() -> None:
    rms = {
        iso_class: float(
            np.std(
                _drive_mg(_vibration(SensorMount.KNUCKLE), uniform_road(iso_class), 80, 30)[:, 2]
            )
        )
        for iso_class in ("A", "B", "C")
    }

    assert rms["B"] / rms["A"] == pytest.approx(2.0, rel=0.02)
    assert rms["C"] / rms["B"] == pytest.approx(2.0, rel=0.02)


def test_vibration_grows_with_speed_and_stops_at_a_standstill() -> None:
    def rms(speed_kmh: float) -> float:
        signal = _drive_mg(_vibration(SensorMount.KNUCKLE), uniform_road("B"), speed_kmh, 30)
        return float(np.std(signal[_FS:, 2]))

    assert rms(0.0) == 0.0
    # The road's velocity input grows as sqrt(v); the contact patch passes more of it.
    assert 1.4 < rms(120.0) / rms(30.0) < 2.5


def test_a_rougher_section_shakes_harder_once_the_wheel_reaches_it() -> None:
    road = RoadSurface(sections=(RoadSection(0.0, "A"), RoadSection(500.0, "C")))
    signal = _drive_mg(_vibration(SensorMount.KNUCKLE), road, 90, 40)  # 1000 m
    half = signal.shape[0] // 2

    assert np.std(signal[half + _FS :, 2]) / np.std(signal[: half - _FS, 2]) == pytest.approx(
        4.0, rel=0.25
    )


def test_a_pothole_hits_the_front_wheels_then_the_rear_one_wheelbase_later() -> None:
    pothole = RoadImpact(at_m=20.0, depth_m=0.03, length_m=0.4)
    smooth = RoadSurface(sections=(RoadSection(0.0, "A"),), impacts=(pothole,))
    speed_kmh = 72.0  # 20 m/s: the front wheels reach the joint after 1 s
    front = _drive_mg(_vibration(SensorMount.KNUCKLE, 0.0), smooth, speed_kmh, 3)
    rear = _drive_mg(_vibration(SensorMount.KNUCKLE, 1.0), smooth, speed_kmh, 3)

    def hit_s(signal: np.ndarray) -> float:
        return float(np.argmax(np.abs(signal[:, 2]))) / _FS

    wheelbase_s = 2.7 / 20.0
    assert hit_s(front) == pytest.approx(1.0, abs=0.02)
    assert hit_s(rear) - hit_s(front) == pytest.approx(wheelbase_s, abs=0.01)
    # A 3 cm pothole jolts the knuckle by several g, far above the road's own shake.
    assert np.max(np.abs(front[:, 2])) > 5000.0
    assert np.max(np.abs(front[:, 2])) > 10 * np.std(front[: _FS // 2, 2])


@pytest.mark.parametrize(
    ("name", "mount", "axle_share"),
    [
        ("front-left", SensorMount.KNUCKLE, 0.0),
        ("VS-41 rear right", SensorMount.KNUCKLE, 1.0),
        ("rear_left_wheel", SensorMount.KNUCKLE, 1.0),
        ("VS-07 trunk", SensorMount.BODY, 1.0),
        ("VS-50 driver seat", SensorMount.BODY, 0.5),
        ("front_subframe", SensorMount.BODY, 0.0),
        ("VS-72 gearbox", SensorMount.POWERTRAIN, 0.0),
        ("engine_bay", SensorMount.POWERTRAIN, 0.0),
        ("sim-3", SensorMount.BODY, 0.5),
    ],
)
def test_mount_follows_the_sensor_name_or_location(
    name: str, mount: SensorMount, axle_share: float
) -> None:
    assert mount_for_name(name) == (mount, axle_share)


def test_front_end_clips_at_16_g_and_outputs_whole_counts() -> None:
    front_end = Adxl345FrontEnd(sample_rate_hz=_FS)
    counts = np.zeros((_FS, 3))
    counts[:, 0] = np.linspace(-6000.0, 6000.0, _FS)

    out = front_end.read(counts, np.random.default_rng(1))

    assert out.dtype == np.int16
    assert out[:, 0].min() == -4096
    assert out[:, 0].max() == 4095


def test_front_end_noise_matches_the_datasheet_at_800_hz() -> None:
    front_end = Adxl345FrontEnd(sample_rate_hz=_FS)
    out = front_end.read(np.zeros((40 * _FS, 3)), np.random.default_rng(2)).astype(np.float64)

    # 0.75 / 0.75 / 1.1 LSB rms at 50 Hz bandwidth, times sqrt(400 / 50).
    np.testing.assert_allclose(np.std(out, axis=0), [2.12, 2.12, 3.11], rtol=0.05)


def test_a_tone_above_nyquist_folds_into_the_band(monkeypatch: pytest.MonkeyPatch) -> None:
    # Gear whine at 900 Hz, 200 counts on each axis, heard standing still.
    whine = replace(
        PROFILE_LIBRARY["engine_idle"],
        name="whine",
        tones=((900.0, (200.0, 200.0, 200.0)),),
        modulation_depth=0.0,
    )
    monkeypatch.setitem(PROFILE_LIBRARY, "whine", whine)
    client = SimClient(
        name="VS-72 gearbox",
        client_id=make_client_id(5),
        control_port=0,
        sample_rate_hz=_FS,
        frame_samples=_FRAME,
        server_host="",
        server_data_port=0,
        server_control_port=0,
        profile_name="whine",
        road=uniform_road("A"),
    )
    client.current_speed_kmh = 0.0

    out = np.concatenate([client.make_frame() for _ in range(40)]).astype(np.float64)

    freq, psd = welch(out[:, 0] - out[:, 0].mean(), fs=_FS, nperseg=1600, scaling="spectrum")
    assert _band_peak_hz(freq, psd, 5.0, 400.0) == pytest.approx(100.0, abs=0.5)
    amplitude = np.sqrt(2.0 * psd[np.argmin(np.abs(freq - 100.0))])
    # The internal filter passes 900 Hz at 1 / sqrt(1 + (900 / 400)^2) = 0.41.
    assert amplitude == pytest.approx(200.0 * 0.406, rel=0.05)
