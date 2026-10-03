"""RunMetadata and SensorFrame mapping codecs."""

from __future__ import annotations

from typing import Any

from vibesensor.domain.strength_metrics import StrengthPeak
from vibesensor.recording.run_metadata import (
    run_metadata_from_mapping,
    run_metadata_to_json_object,
)
from vibesensor.recording.run_schema import RunMetadata
from vibesensor.recording.sensor_frame import SensorFrame
from vibesensor.recording.sensor_frame_mapping import (
    sensor_frame_from_mapping,
    sensor_frame_to_json_object,
)

# ---------------------------------------------------------------------------
# RunMetadata
# ---------------------------------------------------------------------------


class TestRunMetadata:
    def test_create(self) -> None:
        rm = RunMetadata.create(
            run_id="r1",
            start_time_utc="2025-01-01T00:00:00Z",
            sensor_model="ADXL345",
            strength_algorithm_version="strength-db-scalar-v1",
            peak_detector_version="peak-band-rms-v1",
            calibration_profile_id="noise-floor-p20-v1",
            vehicle_baseline_profile_id="car-profile-1",
            raw_sample_rate_hz=800,
            feature_interval_s=1.0,
            fft_window_size_samples=1024,
            accel_scale_g_per_lsb=0.004,
        )
        assert rm.run_id == "r1"
        assert rm.sensor_model == "ADXL345"
        assert rm.accel_scale_g_per_lsb == 0.004
        assert rm.calibration_profile_id == "noise-floor-p20-v1"

    def test_from_dict_minimal(self) -> None:
        rm = run_metadata_from_mapping({"run_id": "r2", "sensor_model": "TEST"})
        assert rm.run_id == "r2"
        assert rm.sensor_model == "TEST"

    def test_from_dict_nan_fields(self) -> None:
        rm = run_metadata_from_mapping(
            {
                "run_id": "r3",
                "raw_sample_rate_hz": float("nan"),
                "feature_interval_s": float("inf"),
            },
        )
        assert rm.raw_sample_rate_hz is None
        assert rm.feature_interval_s is None

    def test_roundtrip(self) -> None:
        rm = RunMetadata.create(
            run_id="r4",
            start_time_utc="2025-01-01T00:00:00Z",
            sensor_model="X",
            strength_algorithm_version="strength-db-scalar-v1",
            peak_detector_version="peak-band-rms-v1",
            calibration_profile_id="noise-floor-p20-v1",
            vehicle_baseline_profile_id="car-profile-1",
            raw_sample_rate_hz=400,
            feature_interval_s=0.5,
            fft_window_size_samples=512,
            accel_scale_g_per_lsb=0.002,
        )
        d = run_metadata_to_json_object(rm)
        rm2 = run_metadata_from_mapping(d)
        assert rm2.run_id == rm.run_id
        assert rm2.sensor_model == rm.sensor_model
        assert rm2.raw_sample_rate_hz == rm.raw_sample_rate_hz
        assert rm2.strength_algorithm_version == "strength-db-scalar-v1"
        assert rm2.peak_detector_version == "peak-band-rms-v1"
        assert rm2.calibration_profile_id == "noise-floor-p20-v1"
        assert rm2.vehicle_baseline_profile_id == "car-profile-1"


# ---------------------------------------------------------------------------
# SensorFrame
# ---------------------------------------------------------------------------


class TestSensorFrame:
    def _minimal_record(self, **overrides: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "run_id": "run1",
            "timestamp_utc": "2025-01-01T00:00:00Z",
            "t_s": 0.0,
            "client_id": "aabb",
            "client_name": "front-left",
            "location_code": "front-left",
            "speed_kmh": 80.0,
            "accel_x_g": 0.02,
            "accel_y_g": 0.01,
            "accel_z_g": 0.10,
            "top_peaks": [{"hz": 25.0, "amp": 0.05}],
            "vibration_strength_db": 20.0,
        }
        base.update(overrides)
        return base

    def _frame(self, **overrides: Any) -> SensorFrame:
        return sensor_frame_from_mapping(self._minimal_record(**overrides))

    def test_from_dict_basic(self) -> None:
        sf = self._frame()
        assert sf.run_id == "run1"
        assert sf.speed_kmh == 80.0
        assert sf.accel_x_g == 0.02
        assert len(sf.top_peaks) == 1

    def test_nan_fields_replaced_with_none(self) -> None:
        """NaN in numeric fields should be normalized to None."""
        sf = self._frame(
            speed_kmh=float("nan"),
            accel_x_g=float("inf"),
        )
        assert sf.speed_kmh is None
        assert sf.accel_x_g is None

    def test_vibration_strength_db_zero_preserved(self) -> None:
        """0.0 is a valid measurement (signal at noise floor) and must not become None."""
        sf = self._frame(vibration_strength_db=0.0)
        assert sf.vibration_strength_db == 0.0

    def test_vibration_strength_db_zero_roundtrip(self) -> None:
        """0.0 must survive from_dict → to_dict → from_dict."""
        sf = self._frame(vibration_strength_db=0.0)
        d = sensor_frame_to_json_object(sf)
        sf2 = sensor_frame_from_mapping(d)
        assert sf2.vibration_strength_db == 0.0

    def test_top_peaks_normalized(self) -> None:
        """Invalid peaks (hz<=0, None amp) are filtered out."""
        sf = self._frame(
            top_peaks=[
                {"hz": 25.0, "amp": 0.05},
                {"hz": -1.0, "amp": 0.03},  # negative hz
                {"hz": 30.0, "amp": None},  # None amp
                {"hz": 0.0, "amp": 0.01},  # zero hz
            ],
        )
        assert len(sf.top_peaks) == 1
        assert sf.top_peaks[0] == StrengthPeak(hz=25.0, amp=0.05)

    def test_top_peaks_capped_at_10(self) -> None:
        peaks = [{"hz": float(i + 1), "amp": 0.01} for i in range(20)]
        sf = self._frame(top_peaks=peaks)
        assert len(sf.top_peaks) <= 10

    def test_roundtrip(self) -> None:
        sf = self._frame()
        d = sensor_frame_to_json_object(sf)
        sf2 = sensor_frame_from_mapping(d)
        assert sf2.run_id == sf.run_id
        assert sf2.speed_kmh == sf.speed_kmh
        assert len(sf2.top_peaks) == len(sf.top_peaks)

    def test_missing_optional_fields(self) -> None:
        """Minimal record with most fields missing should still parse."""
        sf = sensor_frame_from_mapping({"run_id": "x"})
        assert sf.run_id == "x"
        assert sf.speed_kmh is None
        assert sf.accel_x_g is None
        assert sf.top_peaks == ()
