"""Domain model package — rich, DDD-aligned value objects and aggregates.

This package exposes the core domain types for vibration diagnostics,
strictly decoupled from FastAPI, UDP transport, or persistence concerns.

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
    (``DiagnosticSession`` is kept as a compatibility alias.)
Measurement
    Value object representing a single multi-axis acceleration sample.
    (``AccelerationSample`` is kept as a compatibility alias.)
SpeedSource
    How vehicle speed is obtained during a run.
AnalysisWindow
    A contiguous aligned chunk of samples for analysis.
Finding
    One diagnostic conclusion or cause candidate.
Report
    The assembled output of a diagnostic run.
HistoryRecord
    A persisted run with its analysis results.
VibrationReading
    Value object representing a processed vibration measurement in dB.
"""

from .core import (
    AccelerationSample,
    AnalysisWindow,
    Car,
    DiagnosticSession,
    Finding,
    HistoryRecord,
    Measurement,
    Report,
    Run,
    Sensor,
    SensorPlacement,
    SessionStatus,
    SpeedSource,
    VibrationReading,
)

__all__ = [
    # Primary domain names (prefer these)
    "AnalysisWindow",
    "Car",
    "Finding",
    "HistoryRecord",
    "Measurement",
    "Report",
    "Run",
    "Sensor",
    "SensorPlacement",
    "SpeedSource",
    # Existing names (backward compatibility)
    "AccelerationSample",
    "DiagnosticSession",
    "SessionStatus",
    "VibrationReading",
]
