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

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SpeedSourceKind):
            object.__setattr__(self, "kind", SpeedSourceKind(self.kind))
        if self.kind is SpeedSourceKind.MANUAL:
            if self.manual_speed_kmh is None:
                raise ValueError("SpeedSource with kind=MANUAL requires a manual_speed_kmh value")
            if self.manual_speed_kmh <= 0:
                raise ValueError(
                    f"SpeedSource with kind=MANUAL requires a positive manual_speed_kmh, "
                    f"got {self.manual_speed_kmh}"
                )

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

    @staticmethod
    def resolve_basis_label(
        selected_source: str,
        *,
        gps_enabled: bool,
        fallback_active: bool,
        resolution_source: str | None = None,
    ) -> str:
        """Resolve the basis speed-source label for rotational display.

        Pure decision logic extracted from infra — no I/O or runtime objects.
        """
        src = selected_source.strip().lower()
        if src == "manual":
            return "manual"
        if src == "obd2":
            return "obd2"
        if resolution_source is not None:
            if resolution_source == "fallback_manual":
                return "fallback_manual"
            if gps_enabled:
                return "gps"
        else:
            if fallback_active:
                return "fallback_manual"
            if gps_enabled:
                return "gps"
        return "unknown"
