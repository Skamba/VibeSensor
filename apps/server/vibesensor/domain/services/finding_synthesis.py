"""Finding-adjacent synthesis helpers for origin semantics."""

from __future__ import annotations

from ..finding import Finding
from ..vibration_origin import VibrationOrigin


def synthesize_origin(finding: Finding) -> VibrationOrigin:
    """Build the canonical origin object for a finding."""
    if finding.origin is not None:
        return finding.origin
    return VibrationOrigin(
        suspected_source=finding.suspected_source,
        hotspot=finding.location,
        dominance_ratio=finding.dominance_ratio,
        speed_band=finding.strongest_speed_band,
        reason=finding.finding_id,
    )
