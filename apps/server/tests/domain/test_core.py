"""Tests for the DDD domain models: Measurement, VibrationReading, Run."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from vibesensor.domain import (
    Measurement,
    Run,
    RunStatus,
    SessionStatus,
    VibrationReading,
    transition_run,
)
from vibesensor.strength_bands import BANDS
from vibesensor.vibration_strength import vibration_strength_db_scalar

_NOW = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------


class TestMeasurement:
    """Value-object behaviour for Measurement."""

    def test_fields_are_accessible(self) -> None:
        sample = Measurement(
            x=0.01, y=-0.02, z=1.0, timestamp=_NOW, sample_rate_hz=4096, sensor_id="aabb01"
        )
        assert sample.x == 0.01
        assert sample.y == -0.02
        assert sample.z == 1.0
        assert sample.timestamp == _NOW
        assert sample.sample_rate_hz == 4096
        assert sample.sensor_id == "aabb01"

    def test_frozen(self) -> None:
        sample = Measurement(x=0.0, y=0.0, z=0.0, timestamp=_NOW, sample_rate_hz=4096)
        with pytest.raises(AttributeError):
            sample.x = 1.0  # type: ignore[misc]

    def test_to_vibration_reading_db_formula(self) -> None:
        """Verify the dB conversion matches the canonical formula."""
        sample = Measurement(x=0.1, y=0.0, z=0.0, timestamp=_NOW, sample_rate_hz=4096)
        noise_floor = 0.001
        reading = sample.to_vibration_reading(noise_floor)

        peak = math.sqrt(0.1**2)
        expected_db = vibration_strength_db_scalar(
            peak_band_rms_amp_g=peak,
            floor_amp_g=noise_floor,
        )
        assert reading.intensity_db == pytest.approx(expected_db)
        assert reading.peak_amplitude_g == pytest.approx(peak)
        assert reading.noise_floor_g == noise_floor

    def test_to_vibration_reading_multi_axis(self) -> None:
        """Peak amplitude is the Euclidean magnitude across all three axes."""
        sample = Measurement(x=0.03, y=0.04, z=0.0, timestamp=_NOW, sample_rate_hz=4096)
        reading = sample.to_vibration_reading(noise_floor=0.001)
        expected_peak = math.sqrt(0.03**2 + 0.04**2)
        assert reading.peak_amplitude_g == pytest.approx(expected_peak)

    def test_to_vibration_reading_zero_noise_floor(self) -> None:
        """Zero noise floor should not cause a math error."""
        sample = Measurement(x=0.05, y=0.0, z=0.0, timestamp=_NOW, sample_rate_hz=4096)
        reading = sample.to_vibration_reading(noise_floor=0.0)
        assert math.isfinite(reading.intensity_db)

    def test_to_vibration_reading_frequency_is_zero(self) -> None:
        """Single-sample readings carry no spectral info → frequency_hz == 0."""
        sample = Measurement(x=0.1, y=0.0, z=0.0, timestamp=_NOW, sample_rate_hz=4096)
        reading = sample.to_vibration_reading(noise_floor=0.001)
        assert reading.frequency_hz == 0.0

    def test_to_vibration_reading_preserves_sensor_id(self) -> None:
        sample = Measurement(
            x=0.1, y=0.0, z=0.0, timestamp=_NOW, sample_rate_hz=4096, sensor_id="abc123"
        )
        reading = sample.to_vibration_reading(noise_floor=0.001)
        assert reading.sensor_id == "abc123"

    def test_to_vibration_reading_preserves_timestamp(self) -> None:
        sample = Measurement(x=0.1, y=0.0, z=0.0, timestamp=_NOW, sample_rate_hz=4096)
        reading = sample.to_vibration_reading(noise_floor=0.001)
        assert reading.timestamp == _NOW


# ---------------------------------------------------------------------------
# VibrationReading
# ---------------------------------------------------------------------------


class TestVibrationReading:
    """Value-object behaviour for VibrationReading."""

    def test_frozen(self) -> None:
        reading = VibrationReading(timestamp=_NOW, intensity_db=10.0, frequency_hz=50.0)
        with pytest.raises(AttributeError):
            reading.intensity_db = 20.0  # type: ignore[misc]

    @pytest.mark.parametrize(
        ("db", "expected_level"),
        [
            (-5.0, "l0"),
            (0.0, "l0"),
            (7.9, "l0"),
            (8.0, "l1"),
            (15.9, "l1"),
            (16.0, "l2"),
            (25.9, "l2"),
            (26.0, "l3"),
            (35.9, "l3"),
            (36.0, "l4"),
            (45.9, "l4"),
            (46.0, "l5"),
            (100.0, "l5"),
        ],
    )
    def test_get_severity_level_matches_bands(self, db: float, expected_level: str) -> None:
        reading = VibrationReading(timestamp=_NOW, intensity_db=db, frequency_hz=50.0)
        assert reading.get_severity_level() == expected_level

    def test_severity_level_boundary_values(self) -> None:
        """Every BANDS entry should match its own min_db."""
        for band in BANDS:
            reading = VibrationReading(
                timestamp=_NOW, intensity_db=band["min_db"], frequency_hz=50.0
            )
            assert reading.get_severity_level() == band["key"]

    def test_compute_db_matches_scalar_function(self) -> None:
        """VibrationReading.compute_db must match vibration_strength_db_scalar."""
        result = VibrationReading.compute_db(0.05, 0.001)
        expected = vibration_strength_db_scalar(peak_band_rms_amp_g=0.05, floor_amp_g=0.001)
        assert result == pytest.approx(expected)

    def test_compute_db_zero_floor(self) -> None:
        """compute_db handles zero noise floor without error."""
        result = VibrationReading.compute_db(0.05, 0.0)
        assert math.isfinite(result)

    def test_compute_db_or_none_returns_none_for_missing(self) -> None:
        assert VibrationReading.compute_db_or_none(None, 0.001) is None
        assert VibrationReading.compute_db_or_none(0.05, None) is None
        assert VibrationReading.compute_db_or_none(None, None) is None

    def test_compute_db_or_none_returns_float_for_valid(self) -> None:
        result = VibrationReading.compute_db_or_none(0.05, 0.001)
        assert result is not None
        expected = VibrationReading.compute_db(0.05, 0.001)
        assert result == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


class TestRun:
    """Aggregate-root behaviour for Run."""

    def test_initial_state_is_pending(self) -> None:
        session = Run()
        assert session.status is SessionStatus.PENDING

    def test_session_id_is_unique(self) -> None:
        s1 = Run()
        s2 = Run()
        assert s1.session_id != s2.session_id

    def test_start_transitions_to_running(self) -> None:
        session = Run()
        session.start()
        assert session.status is SessionStatus.RUNNING

    def test_start_when_already_running_raises(self) -> None:
        session = Run()
        session.start()
        with pytest.raises(RuntimeError, match="Cannot start session"):
            session.start()

    def test_analysis_settings(self) -> None:
        settings = {"tire_width_mm": 285.0, "final_drive_ratio": 3.08}
        session = Run(analysis_settings=settings)
        assert session.analysis_settings == settings


# ---------------------------------------------------------------------------
# transition_run
# ---------------------------------------------------------------------------


class TestTransitionRun:
    """Enforcing run-status transition function."""

    def test_valid_recording_to_analyzing(self) -> None:
        result = transition_run(RunStatus.RECORDING, RunStatus.ANALYZING)
        assert result is RunStatus.ANALYZING

    def test_valid_recording_to_complete(self) -> None:
        result = transition_run(RunStatus.RECORDING, RunStatus.COMPLETE)
        assert result is RunStatus.COMPLETE

    def test_valid_recording_to_error(self) -> None:
        result = transition_run(RunStatus.RECORDING, RunStatus.ERROR)
        assert result is RunStatus.ERROR

    def test_valid_analyzing_to_complete(self) -> None:
        result = transition_run(RunStatus.ANALYZING, RunStatus.COMPLETE)
        assert result is RunStatus.COMPLETE

    def test_valid_analyzing_to_error(self) -> None:
        result = transition_run(RunStatus.ANALYZING, RunStatus.ERROR)
        assert result is RunStatus.ERROR

    def test_valid_none_to_recording(self) -> None:
        result = transition_run(None, RunStatus.RECORDING)
        assert result is RunStatus.RECORDING

    def test_invalid_complete_to_recording_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid run transition"):
            transition_run(RunStatus.COMPLETE, RunStatus.RECORDING)

    def test_invalid_error_to_recording_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid run transition"):
            transition_run(RunStatus.ERROR, RunStatus.RECORDING)

    def test_invalid_none_to_analyzing_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid run transition"):
            transition_run(None, RunStatus.ANALYZING)

    def test_accepts_plain_strings(self) -> None:
        result = transition_run("recording", "analyzing")
        assert result is RunStatus.ANALYZING
