"""Final finding projection for scored peak bins."""

from __future__ import annotations

from vibesensor.domain import Finding as DomainFinding
from vibesensor.domain import (
    FindingEvidence,
    FindingKind,
    VibrationSource,
)

from ..phase_segmentation import DrivingPhase
from ..speed_profile_helpers import _speed_profile_from_points
from .scoring import PeakBin

_CRUISE_PHASE_VAL: str = DrivingPhase.CRUISE.value


def assemble_peak_finding(peak_bin: PeakBin) -> DomainFinding:
    """Export a scored peak bin as a canonical domain finding."""
    _, _, derived_speed_band = _speed_profile_from_points(peak_bin.speed_amp_pairs)
    speed_band = derived_speed_band or "-"

    total_phase_hits = sum(peak_bin.phases_for_bin.values())
    cruise_hits = peak_bin.phases_for_bin.get(_CRUISE_PHASE_VAL, 0)
    cruise_fraction = cruise_hits / total_phase_hits if total_phase_hits > 0 else 0.0

    suspected_source = (
        VibrationSource.BASELINE_NOISE
        if peak_bin.peak_type == "baseline_noise"
        else VibrationSource.TRANSIENT_IMPACT
        if peak_bin.peak_type == "transient"
        else VibrationSource.UNKNOWN_RESONANCE
    )
    return DomainFinding(
        finding_id="F_PEAK",
        finding_key=f"peak_{peak_bin.bin_center:.0f}hz",
        suspected_source=suspected_source,
        confidence=peak_bin.confidence,
        order=f"{peak_bin.bin_center:.1f} Hz",
        severity="info" if peak_bin.peak_type == "transient" else "diagnostic",
        strongest_speed_band=speed_band if speed_band != "-" else None,
        peak_classification=peak_bin.peak_type,
        kind=(
            FindingKind.INFORMATIONAL
            if peak_bin.peak_type == "transient"
            else FindingKind.DIAGNOSTIC
        ),
        ranking_score=peak_bin.ranking_score,
        vibration_strength_db=peak_bin.peak_strength_db,
        cruise_fraction=cruise_fraction,
        evidence=FindingEvidence(
            match_rate=peak_bin.presence_ratio,
            possible_samples=peak_bin.total_sample_count,
            matched_samples=peak_bin.sample_count,
            presence_ratio=peak_bin.presence_ratio,
            burstiness=peak_bin.burstiness,
            spatial_concentration=peak_bin.spatial_concentration,
            spatial_uniformity=peak_bin.spatial_uniformity or 0.0,
            speed_uniformity=peak_bin.speed_uniformity or 0.0,
            vibration_strength_db=max(0.0, peak_bin.peak_strength_db),
        ),
    )
