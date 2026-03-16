"""Immutable captured evidence and setup context for one completed Run.

Co-locates ConfigurationSnapshot, RunSetup, RunCapture, Measurement,
and VibrationReading — the tightly coupled value objects that together
describe what was measured and how.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType

from vibesensor.domain.car import TireSpec
from vibesensor.domain.sensor import Sensor
from vibesensor.domain.speed_source import SpeedSource
from vibesensor.strength_bands import bucket_for_strength
from vibesensor.vibration_strength import vibration_strength_db_scalar

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

    def to_vibration_reading(self, noise_floor: float) -> VibrationReading:
        from math import sqrt

        peak_amplitude = sqrt(self.x * self.x + self.y * self.y + self.z * self.z)
        intensity_db = vibration_strength_db_scalar(
            peak_band_rms_amp_g=peak_amplitude,
            floor_amp_g=noise_floor,
        )
        return VibrationReading(
            timestamp=self.timestamp,
            intensity_db=intensity_db,
            frequency_hz=0.0,
            peak_amplitude_g=peak_amplitude,
            noise_floor_g=noise_floor,
            sensor_id=self.sensor_id,
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

    def get_severity_level(self) -> str:
        return bucket_for_strength(self.intensity_db)


# ---------------------------------------------------------------------------
# ConfigurationSnapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConfigurationSnapshot:
    """Vehicle/setup state relevant for interpreting a run."""

    sensor_model: str | None = None
    firmware_version: str | None = None
    raw_sample_rate_hz: float | None = None
    feature_interval_s: float | None = None
    final_drive_ratio: float | None = None
    tire_spec: TireSpec | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, MappingProxyType):
            object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @classmethod
    def from_metadata(cls, metadata: Mapping[str, object]) -> ConfigurationSnapshot:
        def _coerce_float(value: object) -> float | None:
            if isinstance(value, bool):
                return float(value)
            if isinstance(value, int | float | str):
                return float(value)
            return None

        tire_spec = TireSpec.from_aspects(
            {
                key: coerced
                for key in ("tire_width_mm", "tire_aspect_pct", "rim_in")
                if (value := metadata.get(key)) is not None
                if (coerced := _coerce_float(value)) is not None
            },
            deflection_factor=_coerce_float(metadata.get("tire_deflection_factor", 1.0)) or 1.0,
        )

        def _as_float(key: str) -> float | None:
            return _coerce_float(metadata.get(key))

        return cls(
            sensor_model=str(metadata.get("sensor_model") or "").strip() or None,
            firmware_version=str(metadata.get("firmware_version") or "").strip() or None,
            raw_sample_rate_hz=_as_float("raw_sample_rate_hz"),
            feature_interval_s=_as_float("feature_interval_s"),
            final_drive_ratio=_as_float("final_drive_ratio"),
            tire_spec=tire_spec,
            metadata=metadata,
        )


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
    speed_source: SpeedSource = SpeedSource()
    configuration_snapshot: ConfigurationSnapshot = ConfigurationSnapshot()


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
    setup: RunSetup = RunSetup()
    analysis_settings: tuple[tuple[str, int | float | bool | str], ...] = ()
    measurements: tuple[Measurement, ...] = ()
    sample_count: int = 0
    duration_s: float = 0.0

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("RunCapture.run_id must be non-empty")
