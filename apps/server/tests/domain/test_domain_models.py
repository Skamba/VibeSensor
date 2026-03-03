"""Tests for domain_models module: CarConfig, SensorConfig, SpeedSourceConfig,
RunMetadata, and SensorFrame parsing/serialization."""

from __future__ import annotations

from typing import Any

import pytest

from vibesensor.domain_models import (
    CarConfig,
    RunMetadata,
    SensorConfig,
    SensorFrame,
    SpeedSourceConfig,
    _as_float_or_none,
    _as_int_or_none,
)

# ---------------------------------------------------------------------------
# Helper parsers
# ---------------------------------------------------------------------------


class TestAsFloatOrNone:
    def test_normal_float(self) -> None:
        assert _as_float_or_none(3.14) == 3.14

    def test_int(self) -> None:
        assert _as_float_or_none(42) == 42.0

    def test_string_number(self) -> None:
        assert _as_float_or_none("3.14") == 3.14

    def test_none(self) -> None:
        assert _as_float_or_none(None) is None

    def test_empty_string(self) -> None:
        assert _as_float_or_none("") is None

    def test_nan(self) -> None:
        assert _as_float_or_none(float("nan")) is None

    def test_inf(self) -> None:
        assert _as_float_or_none(float("inf")) is None

    def test_neg_inf(self) -> None:
        assert _as_float_or_none(float("-inf")) is None

    def test_non_numeric_string(self) -> None:
        assert _as_float_or_none("abc") is None


class TestAsIntOrNone:
    def test_normal(self) -> None:
        assert _as_int_or_none(42) == 42

    def test_float_rounded(self) -> None:
        assert _as_int_or_none(3.7) == 4

    def test_nan(self) -> None:
        assert _as_int_or_none(float("nan")) is None

    def test_none(self) -> None:
        assert _as_int_or_none(None) is None


# ---------------------------------------------------------------------------
# CarConfig
# ---------------------------------------------------------------------------


class TestCarConfig:
    def test_from_dict_basic(self) -> None:
        car = CarConfig.from_dict({"id": "c1", "name": "MyCar", "type": "sedan"})
        assert car.id == "c1"
        assert car.name == "MyCar"
        assert car.type == "sedan"
        assert isinstance(car.aspects, dict)

    def test_from_dict_defaults(self) -> None:
        car = CarConfig.from_dict({})
        assert car.name == "Unnamed Car"
        assert car.type == "sedan"

    def test_name_truncated_at_64(self) -> None:
        long = "A" * 100
        car = CarConfig.from_dict({"name": long})
        assert len(car.name) <= 64

    @pytest.mark.smoke
    def test_roundtrip(self) -> None:
        car = CarConfig.from_dict({"id": "x", "name": "Test", "type": "suv"})
        d = car.to_dict()
        assert d["id"] == "x"
        assert d["name"] == "Test"

    def test_missing_id_gets_generated(self) -> None:
        car = CarConfig.from_dict({"name": "Generated"})
        assert car.name == "Generated"
        assert car.id  # non-empty UUID

    def test_aspects_sanitized(self) -> None:
        car = CarConfig.from_dict({"aspects": {"tire_width_mm": "not_a_number"}})
        # Invalid aspect should be overridden by default
        assert isinstance(car.aspects.get("tire_width_mm"), (int, float))

    def test_whitespace_only_name_falls_back(self) -> None:
        car = CarConfig.from_dict({"name": "   "})
        assert car.name == "Unnamed Car"

    def test_empty_string_name_falls_back(self) -> None:
        car = CarConfig.from_dict({"name": ""})
        assert car.name == "Unnamed Car"

    def test_whitespace_only_type_falls_back(self) -> None:
        car = CarConfig.from_dict({"type": "   "})
        assert car.type == "sedan"


# ---------------------------------------------------------------------------
# SensorConfig
# ---------------------------------------------------------------------------


class TestSensorConfig:
    def test_from_dict_basic(self) -> None:
        sc = SensorConfig.from_dict("abc123", {"name": "FL", "location": "front-left"})
        assert sc.sensor_id == "abc123"
        assert sc.name == "FL"
        assert sc.location == "front-left"

    def test_from_dict_defaults(self) -> None:
        sc = SensorConfig.from_dict("abc123", {})
        assert sc.name == "abc123"
        assert sc.location == ""

    def test_name_truncated(self) -> None:
        sc = SensorConfig.from_dict("id", {"name": "X" * 100})
        assert len(sc.name) <= 64

    def test_roundtrip(self) -> None:
        sc = SensorConfig.from_dict("id1", {"name": "Test", "location": "rear"})
        d = sc.to_dict()
        assert d["name"] == "Test"
        assert d["location"] == "rear"


# ---------------------------------------------------------------------------
# SpeedSourceConfig
# ---------------------------------------------------------------------------


class TestSpeedSourceConfig:
    @pytest.mark.smoke
    def test_default(self) -> None:
        ssc = SpeedSourceConfig.default()
        assert ssc.speed_source == "gps"
        assert ssc.manual_speed_kph is None
        assert ssc.stale_timeout_s == 10.0

    def test_from_dict_camel_case_keys(self) -> None:
        ssc = SpeedSourceConfig.from_dict(
            {
                "speedSource": "manual",
                "manualSpeedKph": 80.0,
                "staleTimeoutS": 5.0,
                "fallbackMode": "manual",
            }
        )
        assert ssc.speed_source == "manual"
        assert ssc.manual_speed_kph == 80.0
        assert ssc.stale_timeout_s == 5.0

    def test_invalid_speed_source_defaults_to_gps(self) -> None:
        ssc = SpeedSourceConfig.from_dict({"speedSource": "invalid"})
        assert ssc.speed_source == "gps"

    def test_stale_timeout_clamped(self) -> None:
        ssc = SpeedSourceConfig.from_dict({"staleTimeoutS": 0.5})
        assert ssc.stale_timeout_s == 3.0
        ssc2 = SpeedSourceConfig.from_dict({"staleTimeoutS": 9999})
        assert ssc2.stale_timeout_s == 120.0

    def test_roundtrip(self) -> None:
        ssc = SpeedSourceConfig.from_dict({"speedSource": "gps"})
        d = ssc.to_dict()
        assert d["speedSource"] == "gps"

    def test_apply_update(self) -> None:
        ssc = SpeedSourceConfig.default()
        ssc.apply_update({"speedSource": "manual", "manualSpeedKph": 50.0})
        assert ssc.speed_source == "manual"
        assert ssc.manual_speed_kph == 50.0

    def test_apply_update_partial_preserves_manual_speed(self) -> None:
        """Partial update without manualSpeedKph must NOT reset the value."""
        ssc = SpeedSourceConfig.default()
        ssc.apply_update({"speedSource": "manual", "manualSpeedKph": 80.0})
        assert ssc.manual_speed_kph == 80.0
        # Partial update that omits manualSpeedKph entirely
        ssc.apply_update({"staleTimeoutS": 5})
        assert ssc.manual_speed_kph == 80.0, "manual_speed_kph was reset by partial update"

    def test_apply_update_explicit_manual_speed_change(self) -> None:
        """Explicitly sending manualSpeedKph updates the value."""
        ssc = SpeedSourceConfig.default()
        ssc.apply_update({"manualSpeedKph": 80.0})
        assert ssc.manual_speed_kph == 80.0
        ssc.apply_update({"manualSpeedKph": 100.0})
        assert ssc.manual_speed_kph == 100.0

    def test_apply_update_explicit_null_clears_manual_speed(self) -> None:
        """Explicitly sending manualSpeedKph=None clears the value."""
        ssc = SpeedSourceConfig.default()
        ssc.apply_update({"manualSpeedKph": 80.0})
        assert ssc.manual_speed_kph == 80.0
        ssc.apply_update({"manualSpeedKph": None})
        assert ssc.manual_speed_kph is None


# ---------------------------------------------------------------------------
# RunMetadata
# ---------------------------------------------------------------------------


class TestRunMetadata:
    def test_create(self) -> None:
        rm = RunMetadata.create(
            run_id="r1",
            start_time_utc="2025-01-01T00:00:00Z",
            sensor_model="ADXL345",
            raw_sample_rate_hz=800,
            feature_interval_s=1.0,
            fft_window_size_samples=1024,
            fft_window_type="hann",
            peak_picker_method="local_max",
            accel_scale_g_per_lsb=0.004,
        )
        assert rm.run_id == "r1"
        assert rm.sensor_model == "ADXL345"
        assert "g" in rm.units.get("accel_x_g", "")

    def test_from_dict_minimal(self) -> None:
        rm = RunMetadata.from_dict({"run_id": "r2", "sensor_model": "TEST"})
        assert rm.run_id == "r2"
        assert rm.sensor_model == "TEST"

    def test_from_dict_nan_fields(self) -> None:
        rm = RunMetadata.from_dict(
            {
                "run_id": "r3",
                "raw_sample_rate_hz": float("nan"),
                "feature_interval_s": float("inf"),
            }
        )
        assert rm.raw_sample_rate_hz is None
        assert rm.feature_interval_s is None

    @pytest.mark.smoke
    def test_roundtrip(self) -> None:
        rm = RunMetadata.create(
            run_id="r4",
            start_time_utc="2025-01-01T00:00:00Z",
            sensor_model="X",
            raw_sample_rate_hz=400,
            feature_interval_s=0.5,
            fft_window_size_samples=512,
            fft_window_type="hann",
            peak_picker_method="maxima",
            accel_scale_g_per_lsb=0.002,
        )
        d = rm.to_dict()
        rm2 = RunMetadata.from_dict(d)
        assert rm2.run_id == rm.run_id
        assert rm2.sensor_model == rm.sensor_model
        assert rm2.raw_sample_rate_hz == rm.raw_sample_rate_hz

    def test_default_phase_metadata(self) -> None:
        rm = RunMetadata.from_dict({"run_id": "old"})
        assert "version" in rm.phase_metadata


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
            "location": "front-left",
            "speed_kmh": 80.0,
            "accel_x_g": 0.02,
            "accel_y_g": 0.01,
            "accel_z_g": 0.10,
            "top_peaks": [{"hz": 25.0, "amp": 0.05}],
            "vibration_strength_db": 20.0,
        }
        base.update(overrides)
        return base

    @pytest.mark.smoke
    def test_from_dict_basic(self) -> None:
        sf = SensorFrame.from_dict(self._minimal_record())
        assert sf.run_id == "run1"
        assert sf.speed_kmh == 80.0
        assert sf.accel_x_g == 0.02
        assert len(sf.top_peaks) == 1
        assert sf.top_peaks_x == []
        assert sf.top_peaks_y == []
        assert sf.top_peaks_z == []

    def test_nan_fields_replaced_with_none(self) -> None:
        """NaN in numeric fields should be normalized to None."""
        sf = SensorFrame.from_dict(
            self._minimal_record(
                speed_kmh=float("nan"),
                accel_x_g=float("inf"),
            )
        )
        assert sf.speed_kmh is None
        assert sf.accel_x_g is None

    def test_vibration_strength_db_zero_preserved(self) -> None:
        """0.0 is a valid measurement (signal at noise floor) and must not become None."""
        sf = SensorFrame.from_dict(self._minimal_record(vibration_strength_db=0.0))
        assert sf.vibration_strength_db == 0.0

    def test_vibration_strength_db_zero_roundtrip(self) -> None:
        """0.0 must survive from_dict → to_dict → from_dict."""
        sf = SensorFrame.from_dict(self._minimal_record(vibration_strength_db=0.0))
        d = sf.to_dict()
        sf2 = SensorFrame.from_dict(d)
        assert sf2.vibration_strength_db == 0.0

    def test_top_peaks_normalized(self) -> None:
        """Invalid peaks (hz<=0, None amp) are filtered out."""
        record = self._minimal_record(
            top_peaks=[
                {"hz": 25.0, "amp": 0.05},
                {"hz": -1.0, "amp": 0.03},  # negative hz
                {"hz": 30.0, "amp": None},  # None amp
                {"hz": 0.0, "amp": 0.01},  # zero hz
            ]
        )
        sf = SensorFrame.from_dict(record)
        assert len(sf.top_peaks) == 1
        assert sf.top_peaks[0]["hz"] == 25.0

    def test_top_peaks_capped_at_10(self) -> None:
        peaks = [{"hz": float(i + 1), "amp": 0.01} for i in range(20)]
        sf = SensorFrame.from_dict(self._minimal_record(top_peaks=peaks))
        assert len(sf.top_peaks) <= 10

    def test_axis_top_peaks_normalized_and_capped_at_3(self) -> None:
        axis_peaks = [{"hz": float(i + 1), "amp": 0.01} for i in range(8)]
        sf = SensorFrame.from_dict(
            self._minimal_record(
                top_peaks_x=axis_peaks,
                top_peaks_y=[{"hz": 0.0, "amp": 0.01}, {"hz": 5.0, "amp": 0.02}],
                top_peaks_z=[{"hz": 7.0, "amp": None}, {"hz": 6.0, "amp": 0.03}],
            )
        )
        assert len(sf.top_peaks_x) == 3
        assert sf.top_peaks_y == [{"hz": 5.0, "amp": 0.02}]
        assert sf.top_peaks_z == [{"hz": 6.0, "amp": 0.03}]

    def test_roundtrip(self) -> None:
        sf = SensorFrame.from_dict(
            self._minimal_record(
                top_peaks_x=[{"hz": 24.0, "amp": 0.04}],
                top_peaks_y=[{"hz": 25.0, "amp": 0.03}],
                top_peaks_z=[{"hz": 26.0, "amp": 0.02}],
            )
        )
        d = sf.to_dict()
        sf2 = SensorFrame.from_dict(d)
        assert sf2.run_id == sf.run_id
        assert sf2.speed_kmh == sf.speed_kmh
        assert len(sf2.top_peaks) == len(sf.top_peaks)
        assert sf2.top_peaks_x == sf.top_peaks_x
        assert sf2.top_peaks_y == sf.top_peaks_y
        assert sf2.top_peaks_z == sf.top_peaks_z

    def test_missing_optional_fields(self) -> None:
        """Minimal record with most fields missing should still parse."""
        sf = SensorFrame.from_dict({"run_id": "x"})
        assert sf.run_id == "x"
        assert sf.speed_kmh is None
        assert sf.accel_x_g is None
        assert sf.top_peaks == []
