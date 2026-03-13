"""Backward-compatibility re-export shim.

This module re-exports all domain objects so that existing ``from
vibesensor.domain.core import …`` statements continue to work.
New code should import from ``vibesensor.domain`` directly.
"""

from vibesensor.domain.analysis_window import AnalysisWindow
from vibesensor.domain.car import Car
from vibesensor.domain.finding import Finding
from vibesensor.domain.history_record import HistoryRecord
from vibesensor.domain.measurement import AccelerationSample, Measurement, VibrationReading
from vibesensor.domain.report import Report
from vibesensor.domain.sensor import Sensor, SensorPlacement
from vibesensor.domain.session import DiagnosticSession, Run, SessionStatus
from vibesensor.domain.speed_source import SpeedSource, SpeedSourceKind

__all__ = [
    # Primary domain names
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
    "SpeedSourceKind",
    # Existing names (kept for backward compatibility)
    "AccelerationSample",
    "DiagnosticSession",
    "SessionStatus",
    "VibrationReading",
]
