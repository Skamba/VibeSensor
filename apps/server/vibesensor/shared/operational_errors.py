"""Operational exception hierarchy for runtime and external-dependency failures.

These exceptions represent failures caused by environment state, external
commands, or service availability rather than domain invariants. They are kept
separate from ``vibesensor.shared.exceptions`` so HTTP and runtime boundaries
can distinguish operational recovery cases from programmer/domain faults.
"""

from __future__ import annotations

__all__ = [
    "ExternalCommandError",
    "OperationalError",
    "ServiceUnavailableError",
]


class OperationalError(Exception):
    """Base exception for non-domain operational failures."""


class ServiceUnavailableError(OperationalError):
    """An external dependency or runtime capability is currently unavailable."""


class ExternalCommandError(ServiceUnavailableError):
    """A subprocess or privileged helper command could not complete successfully."""
