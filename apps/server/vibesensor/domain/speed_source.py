"""Speed acquisition configuration for a diagnostic run.

``SpeedSource`` describes how vehicle speed is obtained — GPS, OBD-II, or
manual entry — and owns source-kind classification and effective-speed
resolution.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "SpeedSource",
    "SpeedSourceKind",
]


class SpeedSourceKind(StrEnum):
    """How vehicle speed is acquired."""

    GPS = "gps"
    OBD2 = "obd2"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class SpeedSource:
    """How vehicle speed is obtained during a diagnostic run.

    Wraps speed-source identity (GPS / OBD2 / manual), optional manual
    override, and fallback policy.  Configuration details (stale timeouts,
    OBD2 parameters) remain in ``SpeedSourceConfig`` which acts as the
    persistence/config adapter.
    """

    kind: SpeedSourceKind = SpeedSourceKind.GPS
    manual_speed_kmh: float | None = None
    fallback_mode: str = "manual"

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SpeedSourceKind):
            object.__setattr__(self, "kind", SpeedSourceKind(self.kind))

    # -- queries -----------------------------------------------------------

    @property
    def is_manual(self) -> bool:
        return self.kind is SpeedSourceKind.MANUAL

    @property
    def is_gps(self) -> bool:
        return self.kind is SpeedSourceKind.GPS

    @property
    def is_obd2(self) -> bool:
        return self.kind is SpeedSourceKind.OBD2

    @property
    def is_live(self) -> bool:
        """Whether speed data comes from a live source (GPS or OBD-II)."""
        return self.kind in (SpeedSourceKind.GPS, SpeedSourceKind.OBD2)

    @property
    def effective_speed_kmh(self) -> float | None:
        """The manually configured speed, or ``None`` for live sources."""
        if self.is_manual:
            return self.manual_speed_kmh
        return None

    @property
    def label(self) -> str:
        """Human-readable label for this speed source."""
        labels = {
            SpeedSourceKind.GPS: "GPS",
            SpeedSourceKind.OBD2: "OBD-II",
            SpeedSourceKind.MANUAL: "Manual",
        }
        return labels.get(self.kind, self.kind.upper())
