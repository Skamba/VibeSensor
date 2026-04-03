"""Domain exception hierarchy for VibeSensor backend.

Provides a structured base class and domain-specific subclasses so that
error handling across the codebase can be narrowed from broad ``except
Exception`` to specific categories.

All domain exceptions inherit exclusively from ``VibeSensorError``;
callers should catch ``VibeSensorError`` (or a specific subclass) rather
than stdlib types like ``ValueError`` or ``RuntimeError``.

Hierarchy
---------
- ``VibeSensorError`` — base for all VibeSensor domain exceptions.
- ``ConfigurationError`` — invalid or inconsistent configuration.
- ``PersistenceError`` — database / storage failures.
- ``ProcessingError`` — signal processing pipeline failures.
- ``ProtocolError`` — malformed or unexpected binary protocol message.
- ``UpdateError`` — OTA update system failures.
- ``RunNotFoundError`` — requested run does not exist.
- ``AnalysisNotReadyError`` — analysis is in progress or failed.
- ``DataCorruptError`` — persisted data is in an unexpected format.
"""

from __future__ import annotations

__all__ = [
    "AnalysisNotReadyError",
    "ConfigurationError",
    "DataCorruptError",
    "PersistenceError",
    "ProcessingError",
    "ProtocolError",
    "UpdateCancelledError",
    "UpdateCleanupError",
    "UpdatePreparationError",
    "UpdateReleaseError",
    "UpdateTransportError",
    "RunNotFoundError",
    "UpdateError",
    "VibeSensorError",
]


class VibeSensorError(Exception):
    """Base exception for all VibeSensor domain errors."""


class ConfigurationError(VibeSensorError):
    """Invalid or inconsistent configuration."""


class PersistenceError(VibeSensorError):
    """Database or file-system storage failure."""


class ProcessingError(VibeSensorError):
    """Signal processing pipeline failure."""


class ProtocolError(VibeSensorError):
    """Malformed or unexpected binary protocol message."""


class UpdateError(VibeSensorError):
    """OTA update system failure."""

    def __init__(self, message: str, *, status: str = "error") -> None:
        super().__init__(message)
        self.status = status


class UpdateCleanupError(UpdateError):
    """Updater cleanup failed after the main workflow had already exited."""


class UpdatePreparationError(UpdateError):
    """Update preflight or transport preparation failed."""


class UpdateTransportError(UpdateError):
    """Transport-specific update setup or finalization failed."""


class UpdateReleaseError(UpdateError):
    """Release discovery, staging, or installation failed."""


class UpdateCancelledError(UpdateError):
    """Update execution was cancelled intentionally."""

    def __init__(self, message: str = "Update was cancelled") -> None:
        super().__init__(message, status="cancelled")


class RunNotFoundError(VibeSensorError):
    """Requested run does not exist in the history database."""


class AnalysisNotReadyError(VibeSensorError):
    """Analysis is still in progress, has failed, or is not available."""

    def __init__(self, message: str, *, status: str = "unavailable") -> None:
        super().__init__(message)
        self.status = status


class DataCorruptError(VibeSensorError):
    """Persisted data is in an unexpected or corrupt format."""
