"""Immutable captured evidence and setup context for one completed Run.

Co-locates ConfigurationSnapshot, RunSetup, RunCapture, Measurement,
and VibrationReading — the tightly coupled value objects that together
describe what was measured and how.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from math import sqrt

from vibesensor.domain.sensor import Sensor
from vibesensor.domain.speed_source import SpeedSource
from vibesensor.domain.tire_spec import TireSpec

__all__ = ["ConfigurationSnapshot", "Measurement", "RunCapture", "RunSetup", "VibrationReading"]


# ---------------------------------------------------------------------------
# Measurement / VibrationReading
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Measurement:
    """A single multi-axis acceleration measurement from an ESP32 sensor."""

    x: float
    y: float
    z: float
    timestamp: datetime
    sample_rate_hz: int
    sensor_id: str = ""

    def __post_init__(self) -> None:
        if self.sample_rate_hz <= 0:
            raise ValueError(f"sample_rate_hz must be positive, got {self.sample_rate_hz}")

    def peak_amplitude_g(self) -> float:
        """Return the Euclidean acceleration magnitude in g."""
        return sqrt(self.x * self.x + self.y * self.y + self.z * self.z)

    def to_vibration_reading(
        self,
        noise_floor: float,
        *,
        intensity_db: float,
        strength_bucket: str | None = None,
    ) -> VibrationReading:
        peak_amplitude = self.peak_amplitude_g()
        return VibrationReading(
            timestamp=self.timestamp,
            intensity_db=intensity_db,
            frequency_hz=0.0,
            peak_amplitude_g=peak_amplitude,
            noise_floor_g=noise_floor,
            sensor_id=self.sensor_id,
            strength_bucket=strength_bucket,
        )


@dataclass(frozen=True, slots=True)
class VibrationReading:
    """A processed vibration measurement expressed in dB."""

    timestamp: datetime
    intensity_db: float
    frequency_hz: float
    peak_amplitude_g: float = 0.0
    noise_floor_g: float = 0.0
    sensor_id: str = ""
    strength_bucket: str | None = None

    def get_severity_level(self) -> str:
        return self.strength_bucket or "l0"


# ---------------------------------------------------------------------------
# ConfigurationSnapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConfigurationSnapshot:
    """Vehicle/setup state relevant for interpreting a run."""

    sensor_model: str | None = None
    firmware_version: str | None = None
    strength_algorithm_version: str | None = None
    peak_detector_version: str | None = None
    calibration_profile_id: str | None = None
    vehicle_baseline_profile_id: str | None = None
    raw_sample_rate_hz: float | None = None
    feature_interval_s: float | None = None
    final_drive_ratio: float | None = None
    tire_spec: TireSpec | None = None


# ---------------------------------------------------------------------------
# RunSetup
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunSetup:
    """Immutable setup context for one diagnostic run.

    Captures how the run was conducted: which sensors were used, how speed
    was acquired, and firmware/sample-rate configuration.  Does NOT contain
    ``Car`` — car is case-scoped context owned by ``DiagnosticCase``.
    """

    sensors: tuple[Sensor, ...] = ()
    speed_source: SpeedSource = field(default_factory=SpeedSource)
    configuration_snapshot: ConfigurationSnapshot = field(default_factory=ConfigurationSnapshot)


# ---------------------------------------------------------------------------
# RunCapture
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunCapture:
    """Immutable captured evidence from one completed Run.

    RunCapture is the bridge between capture lifecycle (Run) and analyzed
    diagnostic meaning (TestRun). It holds captured evidence and setup
    context, interpreted within the case-scoped Car context.

    Note: ``measurements`` defaults to an empty tuple. The analysis pipeline
    works with raw numpy arrays for DSP performance; converting thousands of
    samples to Measurement domain objects is prohibitively expensive and
    currently has no consumer. The structural relationship exists but is not
    populated for performance reasons.
    """

    run_id: str
    setup: RunSetup = field(default_factory=RunSetup)
    analysis_settings: tuple[tuple[str, int | float | bool | str], ...] = ()
    measurements: tuple[Measurement, ...] = ()
    sample_count: int = 0
    duration_s: float = 0.0

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("RunCapture.run_id must be non-empty")
