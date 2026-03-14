"""Run speed behaviour as a diagnostic concept.

``SpeedProfile`` captures how the vehicle was driven during a
diagnostic run: average speed, range, steadiness, and cruise coverage.
These are domain-level concerns that affect diagnosis quality and
finding confidence.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["SpeedProfile"]


@dataclass(frozen=True, slots=True)
class SpeedProfile:
    """Speed behaviour during a diagnostic run."""

    min_kmh: float = 0.0
    max_kmh: float = 0.0
    mean_kmh: float = 0.0
    stddev_kmh: float = 0.0
    steady_speed: bool = False
    has_cruise: bool = False
    cruise_fraction: float = 0.0
    sample_count: int = 0

    # -- domain queries ----------------------------------------------------

    @property
    def speed_range_kmh(self) -> float:
        """Total speed range covered during the run."""
        return max(0.0, self.max_kmh - self.min_kmh)

    @property
    def is_adequate_for_diagnosis(self) -> bool:
        """Enough speed data exists for meaningful analysis."""
        return self.sample_count >= 10 and self.max_kmh > 5.0

    @property
    def has_steady_cruise(self) -> bool:
        """Run had meaningful cruise segments (best evidence quality)."""
        return self.has_cruise and self.cruise_fraction >= 0.3

    # -- boundary adapter --------------------------------------------------

    @staticmethod
    def from_stats(
        speed_stats: dict[str, object],
        phase_summary: dict[str, object] | None = None,
    ) -> SpeedProfile:
        """Construct from speed-stats and phase-summary dicts (boundary adapter)."""
        ps = phase_summary or {}

        def _f(d: dict[str, object], key: str, default: float = 0.0) -> float:
            raw = d.get(key)
            if raw is not None:
                try:
                    return float(raw)  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    pass
            return default

        cruise_pct = _f(ps, "cruise_pct", 0.0)

        return SpeedProfile(
            min_kmh=_f(speed_stats, "min_kmh"),
            max_kmh=_f(speed_stats, "max_kmh"),
            mean_kmh=_f(speed_stats, "mean_kmh"),
            stddev_kmh=_f(speed_stats, "stddev_kmh"),
            steady_speed=bool(speed_stats.get("steady_speed", False)),
            has_cruise=bool(ps.get("has_cruise", False)),
            cruise_fraction=cruise_pct / 100.0 if cruise_pct else 0.0,
            sample_count=int(_f(speed_stats, "sample_count", 0)),
        )
