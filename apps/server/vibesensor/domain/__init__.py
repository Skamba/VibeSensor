"""Domain model package — rich, DDD-aligned value objects and aggregates.

This package exposes the core domain types for vibration diagnostics,
strictly decoupled from FastAPI, UDP transport, or persistence concerns.

Public API
----------
AccelerationSample
    Value object representing a single multi-axis acceleration sample.
VibrationReading
    Value object representing a processed vibration measurement in dB.
DiagnosticSession
    Aggregate root representing a complete diagnostic measurement session.
"""

from .core import AccelerationSample, DiagnosticSession, SessionStatus, VibrationReading

__all__ = [
    "AccelerationSample",
    "DiagnosticSession",
    "SessionStatus",
    "VibrationReading",
]
