"""Domain model package — rich, DDD-aligned value objects and aggregates.

This package exposes the core domain types for vibration diagnostics,
strictly decoupled from FastAPI, UDP transport, or persistence concerns.

Each primary domain object lives in its own dedicated file.  Consumers
should import from ``vibesensor.domain`` rather than from individual
module files.

Primary domain concepts
-----------------------
Car
    The vehicle under test.
Sensor
    A physical accelerometer node attached to the vehicle.
SensorPlacement
    A sensor's mounting position on the vehicle.
Run
    Aggregate root representing a complete diagnostic measurement session.
Measurement
    Value object representing a single multi-axis acceleration sample.
SpeedSource
    How vehicle speed is obtained during a run.
Finding
    One diagnostic conclusion or cause candidate.
Report
    The assembled output of a diagnostic run.
VibrationReading
    Value object representing a processed vibration measurement in dB.
"""

from .car import Car, TireSpec
from .driving_phase import DrivingPhase
from .finding import (
    Finding,
    FindingKind,
    VibrationSource,
    speed_band_sort_key,
    speed_bin_label,
)
from .measurement import Measurement, VibrationReading
from .report import Report
from .run import Run
from .run_status import RUN_TRANSITIONS, RunStatus, transition_run
from .sensor import Sensor, SensorPlacement
from .speed_source import SpeedSource, SpeedSourceKind

__all__ = [
    # Primary domain names (prefer these)
    "Car",
    "DrivingPhase",
    "Finding",
    "FindingKind",
    "Measurement",
    "RUN_TRANSITIONS",
    "Report",
    "Run",
    "RunStatus",
    "Sensor",
    "SensorPlacement",
    "speed_band_sort_key",
    "speed_bin_label",
    "SpeedSource",
    "SpeedSourceKind",
    "TireSpec",
    "VibrationSource",
    "transition_run",
    # Existing names
    "VibrationReading",
]
