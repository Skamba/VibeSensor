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
- ``UpdateError`` — OTA update system failures.
"""

from __future__ import annotations

__all__ = [
    "ConfigurationError",
    "PersistenceError",
    "ProcessingError",
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


class UpdateError(VibeSensorError, RuntimeError):
    """OTA update system failure."""
