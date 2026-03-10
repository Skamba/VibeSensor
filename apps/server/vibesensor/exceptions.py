"""Domain exception hierarchy for VibeSensor backend.

Provides a structured base class and domain-specific subclasses so that
error handling across the codebase can be narrowed from broad ``except
Exception`` to specific categories, while remaining backward-compatible
with the ad-hoc ``ValueError`` / ``RuntimeError`` patterns already in use.

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
    "RunNotFoundError",
    "UpdateError",
    "VibeSensorError",
]


class VibeSensorError(Exception):
    """Base exception for all VibeSensor domain errors."""


class ConfigurationError(VibeSensorError, ValueError):
    """Invalid or inconsistent configuration.

    Inherits from ``ValueError`` so existing ``except ValueError`` handlers
    continue to work during migration.
    """


class PersistenceError(VibeSensorError, RuntimeError):
    """Database or file-system storage failure.

    Inherits from ``RuntimeError`` for backward compatibility with code
    that catches ``RuntimeError`` for storage issues.
    """


class ProcessingError(VibeSensorError, RuntimeError):
    """Signal processing pipeline failure."""


class ProtocolError(VibeSensorError, ValueError):
    """Malformed or unexpected binary protocol message.

    Inherits from ``ValueError`` for backward compatibility with code
    that catches ``ValueError`` for parse/validation issues.
    """


class UpdateError(VibeSensorError, RuntimeError):
    """OTA update system failure."""


class RunNotFoundError(VibeSensorError, LookupError):
    """Requested run does not exist in the history database."""


class AnalysisNotReadyError(VibeSensorError):
    """Analysis is still in progress, has failed, or is not available."""

    def __init__(self, message: str, *, status: str = "unavailable") -> None:
        super().__init__(message)
        self.status = status


class DataCorruptError(VibeSensorError):
    """Persisted data is in an unexpected or corrupt format."""
