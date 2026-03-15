"""Finding-adjacent synthesis helpers for origin semantics."""

from __future__ import annotations

from ..finding import VibrationSource
from ..location_hotspot import LocationHotspot
from ..vibration_origin import VibrationOrigin


def synthesize_origin(
    *,
    suspected_source: VibrationSource,
    hotspot: LocationHotspot | None = None,
    dominance_ratio: float | None = None,
    speed_band: str | None = None,
    dominant_phase: str | None = None,
    reason: str = "",
) -> VibrationOrigin:
    """Build a canonical origin object from typed pre-finding inputs."""
    return VibrationOrigin.from_analysis_inputs(
        suspected_source=suspected_source,
        hotspot=hotspot,
        dominance_ratio=dominance_ratio,
        speed_band=speed_band,
        dominant_phase=dominant_phase,
        reason=reason,
    )
