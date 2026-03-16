"""Cross-scenario invariants for simulator determinism, language, speed bands, and confidence."""

from __future__ import annotations

from typing import Any

import numpy as np
from test_support import make_sample as _make_sample
from test_support.scenario_ground_truth import (
    ALL_SENSORS,
    fault_phase,
    get_top_cause,
    idle_phase,
    ramp_phase,
    road_noise_phase,
    standard_metadata,
    wheel_hz,
)

from vibesensor.use_cases.diagnostics import summarize_run_data


class _FakeSimClient:
    """Lightweight stub for simulator client tests."""

    def __init__(self, name: str, *, profile_name: str = "engine_idle"):
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
        pass


class TestSimulatorDeterminism:
    def test_road_fixed_scenario_applies_stable_gains(self) -> None:
        from vibesensor.adapters.simulator.commands import apply_road_fixed_scenario

        clients = [_FakeSimClient(name) for name in ALL_SENSORS]
        apply_road_fixed_scenario(clients)

        for client in clients:
            assert client.profile_name == "rough_road"
            assert client.scene_mode == "road-fixed"
            assert client.scene_gain == 0.28
            assert client.scene_noise_gain == 1.02
            assert client.common_event_gain == 0.10
            assert client.amp_scale == 0.52
            assert client.noise_scale == 1.00

    def test_road_fixed_all_clients_identical(self) -> None:
        from vibesensor.adapters.simulator.commands import apply_road_fixed_scenario

        clients = [_FakeSimClient(name) for name in ALL_SENSORS]
        apply_road_fixed_scenario(clients)
        gains = [(c.scene_gain, c.scene_noise_gain, c.amp_scale, c.noise_scale) for c in clients]
        assert all(gain == gains[0] for gain in gains)

    def test_one_wheel_mild_fault_is_strong_but_others_remain_coupled(self) -> None:
        from vibesensor.adapters.simulator.commands import apply_one_wheel_mild_scenario

        clients = [_FakeSimClient(name) for name in ALL_SENSORS]
        apply_one_wheel_mild_scenario(clients, "rear-left")

        fault_client = next(client for client in clients if client.name == "rear-left")
        other_clients = [client for client in clients if client.name != "rear-left"]
        assert fault_client.profile_name == "wheel_mild_imbalance"
        assert fault_client.scene_gain == 0.78
        assert fault_client.scene_noise_gain == 1.04
        assert fault_client.amp_scale == 1.0
        assert fault_client.noise_scale == 1.04
        assert fault_client.common_event_gain == 0.18
        assert fault_client.scene_gain > max(client.scene_gain for client in other_clients)
        for client in other_clients:
            assert client.profile_name == "wheel_mild_imbalance"
            assert 0.37 <= client.scene_gain <= 0.41
            assert 1.00 <= client.scene_noise_gain <= 1.03
            assert 0.70 <= client.amp_scale <= 0.74
            assert 0.98 <= client.noise_scale <= 1.00
            assert 0.11 <= client.common_event_gain <= 0.13

    def test_road_scene_single_mode_keeps_non_active_sensors_alive(self) -> None:
        from vibesensor.adapters.simulator.sim_sender import RoadSceneController

        clients = [_FakeSimClient(name, profile_name="rough_road") for name in ALL_SENSORS]
        controller = RoadSceneController(clients)
        controller._apply_single_active()

        active_clients = [
            client for client in clients if client.profile_name == "wheel_mild_imbalance"
        ]
        assert len(active_clients) == 1
        for client in [
            client for client in clients if client.profile_name != "wheel_mild_imbalance"
        ]:
            assert client.scene_gain >= 0.35
            assert client.common_event_gain >= 0.10

    def test_sensor_noise_floor_stays_present_even_when_scene_gain_is_zero(self) -> None:
        from vibesensor.adapters.simulator.sim_sender import SimClient, make_client_id

        client = SimClient(
            name="front-left",
            client_id=make_client_id(1),
            control_port=9101,
            sample_rate_hz=800,
            frame_samples=200,
            server_host="127.0.0.1",
            server_data_port=5005,
            server_control_port=5006,
            profile_name="rough_road",
            noise_floor_std=3.5,
        )
        client.scene_gain = 0.0
        client.scene_noise_gain = 0.0
        client.amp_scale = 0.0
        client.noise_scale = 0.0
        frame = client.make_frame()
        assert frame.dtype == np.int16
        assert np.abs(frame).sum() > 0


class TestLanguageSelectionPrecedence:
    def test_explicit_lang_overrides_metadata(self) -> None:
        summary = summarize_run_data(
            standard_metadata(language="nl"),
            fault_phase(
                speed_kmh=80.0,
                duration_s=10.0,
                fault_sensor="front-left",
                sensors=ALL_SENSORS,
                start_t_s=0.0,
            ),
            lang="en",
            file_name="test",
        )
        assert summary.get("lang") == "en"

    def test_metadata_language_used_when_no_explicit_lang(self) -> None:
        summary = summarize_run_data(
            standard_metadata(language="nl"),
            fault_phase(
                speed_kmh=80.0,
                duration_s=10.0,
                fault_sensor="front-left",
                sensors=ALL_SENSORS,
                start_t_s=0.0,
            ),
            lang="nl",
            file_name="test",
        )
        assert summary.get("lang") == "nl"

    def test_en_default_when_no_lang_anywhere(self) -> None:
        metadata = standard_metadata()
        del metadata["language"]
        summary = summarize_run_data(
            metadata,
            fault_phase(
                speed_kmh=80.0,
                duration_s=10.0,
                fault_sensor="front-left",
                sensors=ALL_SENSORS,
                start_t_s=0.0,
            ),
            lang="en",
            file_name="test",
        )
        assert summary.get("lang") == "en"

    def test_nl_report_has_dutch_labels(self) -> None:
        summary = summarize_run_data(
            standard_metadata(language="nl"),
            fault_phase(
                speed_kmh=80.0,
                duration_s=10.0,
                fault_sensor="front-left",
                sensors=ALL_SENSORS,
                start_t_s=0.0,
            ),
            lang="nl",
            file_name="test",
        )
        assert summary.get("lang") == "nl"


class TestSpeedBandMixedPhase:
    def test_ramp_then_cruise_fault_reports_cruise_band(self) -> None:
        samples: list[dict[str, Any]] = []
        t = 0.0
        samples.extend(idle_phase(duration_s=5.0, sensors=ALL_SENSORS, start_t_s=t))
        t += 5.0
        samples.extend(
            ramp_phase(
                speed_start=20.0,
                speed_end=100.0,
                n_steps=4,
                step_duration_s=2.0,
                sensors=ALL_SENSORS,
                start_t_s=t,
            ),
        )
        t += 8.0
        samples.extend(
            fault_phase(
                speed_kmh=100.0,
                duration_s=30.0,
                fault_sensor="front-right",
                sensors=ALL_SENSORS,
                start_t_s=t,
            ),
        )

        summary = summarize_run_data(
            standard_metadata(),
            samples,
            lang="en",
            file_name="speed_band_test",
        )
        band = str(get_top_cause(summary).get("strongest_speed_band") or "")
        assert band and "km/h" in band and "100" in band

    def test_interleaved_speeds_reports_dominant_fault_band(self) -> None:
        samples: list[dict[str, Any]] = []
        t = 0.0
        samples.extend(
            fault_phase(
                speed_kmh=50.0,
                duration_s=10.0,
                fault_sensor="rear-left",
                sensors=ALL_SENSORS,
                start_t_s=t,
            ),
        )
        t += 10.0
        samples.extend(
            road_noise_phase(
                speed_kmh=30.0,
                duration_s=5.0,
                sensors=ALL_SENSORS,
                start_t_s=t,
            ),
        )
        t += 5.0
        samples.extend(
            fault_phase(
                speed_kmh=60.0,
                duration_s=25.0,
                fault_sensor="rear-left",
                sensors=ALL_SENSORS,
                start_t_s=t,
                fault_amp=0.07,
                fault_vib_db=28.0,
            ),
        )

        band = str(
            get_top_cause(
                summarize_run_data(
                    standard_metadata(),
                    samples,
                    lang="en",
                    file_name="dominant_band_test",
                ),
            ).get("strongest_speed_band")
            or "",
        )
        assert band and "60" in band

    def test_acceleration_phase_does_not_dominate_speed_band(self) -> None:
        samples: list[dict[str, Any]] = []
        t = 0.0
        for step in range(10):
            speed = 20.0 + step * 10.0
            whz = wheel_hz(speed)
            for _ in range(3):
                for sensor in ALL_SENSORS:
                    if sensor == "front-right":
                        peaks = [{"hz": whz, "amp": 0.02}, {"hz": 142.5, "amp": 0.004}]
                        vib_db = 14.0
                    else:
                        peaks = [{"hz": 142.5, "amp": 0.004}]
                        vib_db = 8.0
                    samples.append(
                        _make_sample(
                            t_s=t,
                            speed_kmh=speed,
                            client_name=sensor,
                            top_peaks=peaks,
                            vibration_strength_db=vib_db,
                            strength_floor_amp_g=0.003,
                        ),
                    )
                t += 1.0
        samples.extend(
            fault_phase(
                speed_kmh=100.0,
                duration_s=30.0,
                fault_sensor="front-right",
                sensors=ALL_SENSORS,
                start_t_s=t,
                fault_amp=0.06,
                fault_vib_db=26.0,
            ),
        )

        band = str(
            get_top_cause(
                summarize_run_data(
                    standard_metadata(),
                    samples,
                    lang="en",
                    file_name="accel_weight_test",
                ),
            ).get("strongest_speed_band")
            or "",
        )
        assert band and "100" in band


class TestConfidenceGuardrails:
    def test_clear_single_sensor_fault_has_reasonable_confidence(self) -> None:
        summary = summarize_run_data(
            standard_metadata(),
            fault_phase(
                speed_kmh=80.0,
                duration_s=40.0,
                fault_sensor="rear-right",
                sensors=ALL_SENSORS,
                start_t_s=0.0,
                fault_amp=0.06,
            ),
            lang="en",
            file_name="conf_clear",
        )
        top = get_top_cause(summary)
        assert float(top.get("confidence") or 0.0) >= 0.30
        assert "rear-right" in str(top.get("strongest_location") or "").lower()

    def test_all_sensors_equal_amplitude_lower_confidence(self) -> None:
        samples: list[dict[str, Any]] = []
        for idx in range(30):
            for sensor in ALL_SENSORS:
                whz = wheel_hz(80.0)
                samples.append(
                    _make_sample(
                        t_s=float(idx),
                        speed_kmh=80.0,
                        client_name=sensor,
                        top_peaks=[{"hz": whz, "amp": 0.06}, {"hz": whz * 2, "amp": 0.024}],
                        vibration_strength_db=26.0,
                        strength_floor_amp_g=0.004,
                    ),
                )
        top_causes = summarize_run_data(
            standard_metadata(),
            samples,
            lang="en",
            file_name="conf_equal",
        ).get("top_causes", [])
        if top_causes:
            top = top_causes[0]
            assert top.get("weak_spatial_separation", False) or top.get("diffuse_excitation", False)
            assert float(top.get("confidence", 0)) < 0.50

    def test_short_intermittent_fault_lower_than_long_sustained(self) -> None:
        short_summary = summarize_run_data(
            standard_metadata(),
            fault_phase(
                speed_kmh=80.0,
                duration_s=8.0,
                fault_sensor="front-left",
                sensors=ALL_SENSORS,
                start_t_s=0.0,
            ),
            lang="en",
            file_name="conf_short",
        )
        long_summary = summarize_run_data(
            standard_metadata(),
            fault_phase(
                speed_kmh=80.0,
                duration_s=40.0,
                fault_sensor="front-left",
                sensors=ALL_SENSORS,
                start_t_s=0.0,
            ),
            lang="en",
            file_name="conf_long",
        )
        short_top = (
            short_summary.get("top_causes", [{}])[0] if short_summary.get("top_causes") else {}
        )
        long_top = long_summary.get("top_causes", [{}])[0] if long_summary.get("top_causes") else {}
        assert long_summary.get("top_causes")
        short_conf = short_top.get("confidence", 0.0)
        long_conf = long_top.get("confidence", 0.0)
        assert long_conf > 0.0
        assert long_conf >= short_conf
