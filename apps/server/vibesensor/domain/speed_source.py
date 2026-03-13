"""Speed acquisition configuration for a diagnostic run.

``SpeedSource`` describes how vehicle speed is obtained — GPS, OBD-II, or
manual entry — and owns source-kind classification and effective-speed
resolution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = [
    "SpeedSource",
    "SpeedSourceKind",
]

SpeedSourceKind = Literal["gps", "obd2", "manual"]


@dataclass(frozen=True, slots=True)
class SpeedSource:
    """How vehicle speed is obtained during a diagnostic run.

    Wraps speed-source identity (GPS / OBD2 / manual), optional manual
    override, and fallback policy.  Configuration details (stale timeouts,
    OBD2 parameters) remain in ``SpeedSourceConfig`` which acts as the
    persistence/config adapter.
    """

    kind: SpeedSourceKind = "gps"
    manual_speed_kmh: float | None = None
    fallback_mode: str = "manual"

    # -- queries -----------------------------------------------------------

    @property
    def is_manual(self) -> bool:
        return self.kind == "manual"

    @property
    def is_gps(self) -> bool:
        return self.kind == "gps"

    @property
    def is_obd2(self) -> bool:
        return self.kind == "obd2"

    @property
    def is_live(self) -> bool:
        """Whether speed data comes from a live source (GPS or OBD-II)."""
        return self.kind in ("gps", "obd2")

    @property
    def effective_speed_kmh(self) -> float | None:
        """The manually configured speed, or ``None`` for live sources."""
        if self.is_manual:
            return self.manual_speed_kmh
        return None

    @property
    def label(self) -> str:
        """Human-readable label for this speed source."""
        labels = {"gps": "GPS", "obd2": "OBD-II", "manual": "Manual"}
        return labels.get(self.kind, self.kind.upper())
