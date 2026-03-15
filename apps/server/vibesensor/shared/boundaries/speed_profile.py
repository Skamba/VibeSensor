"""Boundary decoder: speed-stats / phase-summary dicts → domain SpeedProfile."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.domain.speed_profile import SpeedProfile


def speed_profile_from_stats(
    speed_stats: Mapping[str, object],
    phase_summary: Mapping[str, object] | None = None,
) -> SpeedProfile:
    """Construct a ``SpeedProfile`` from speed-stats and phase-summary dicts."""
    ps: Mapping[str, object] = phase_summary or {}

    def _f(d: Mapping[str, object], key: str, default: float = 0.0) -> float:
        raw = d.get(key)
        if raw is not None:
            try:
                return float(raw)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                pass
        return default

    def _fraction(d: Mapping[str, object], key: str, *, phase_key: str | None = None) -> float:
        raw = d.get(key)
        if raw is None and phase_key is not None:
            phase_pcts = d.get("phase_pcts")
            if isinstance(phase_pcts, Mapping):
                raw = phase_pcts.get(phase_key)
        if raw is None:
            return 0.0
        try:
            pct = float(raw) / 100.0  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0
        return min(1.0, max(0.0, pct))

    def _flag(d: Mapping[str, object], key: str, *, phase_key: str | None = None) -> bool:
        raw = d.get(key)
        if raw is not None:
            return bool(raw)
        if phase_key is None:
            return False
        phase_counts = d.get("phase_counts")
        if not isinstance(phase_counts, Mapping):
            return False
        return _f(phase_counts, phase_key, 0.0) > 0.0

    return SpeedProfile(
        min_kmh=_f(speed_stats, "min_kmh"),
        max_kmh=_f(speed_stats, "max_kmh"),
        mean_kmh=_f(speed_stats, "mean_kmh"),
        stddev_kmh=_f(speed_stats, "stddev_kmh"),
        steady_speed=bool(speed_stats.get("steady_speed", False)),
        has_cruise=_flag(ps, "has_cruise", phase_key="cruise"),
        has_acceleration=_flag(ps, "has_acceleration", phase_key="acceleration"),
        cruise_fraction=_fraction(ps, "cruise_pct", phase_key="cruise"),
        idle_fraction=_fraction(ps, "idle_pct", phase_key="idle"),
        speed_unknown_fraction=_fraction(
            ps,
            "speed_unknown_pct",
            phase_key="speed_unknown",
        ),
        sample_count=int(_f(speed_stats, "sample_count", 0)),
    )
