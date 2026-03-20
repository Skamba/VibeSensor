"""Speed-provider port used by recording use-cases.

This protocol captures the narrow ``GPSSpeedMonitor`` surface currently
consumed by ``use_cases/run/``. Issue ``#814`` will later consolidate these
focused protocols into a shared ``ports.py`` module.
"""

from __future__ import annotations

from typing import Protocol

from vibesensor.shared.types.backend_types import ResolvedSpeedSource

__all__ = ["ResolvedSpeedSnapshot", "SpeedProvider"]


class ResolvedSpeedSnapshot(Protocol):
    """Minimal resolved-speed view consumed by the recording path."""

    @property
    def speed_mps(self) -> float | None: ...

    @property
    def source(self) -> ResolvedSpeedSource: ...


class SpeedProvider(Protocol):
    """Speed access needed by recording flows."""

    speed_mps: float | None

    def resolve_speed(self) -> ResolvedSpeedSnapshot: ...
