"""Boundary decoding helpers for ``FindingEvidence`` payloads."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.domain import FindingEvidence
from vibesensor.shared.boundaries.codecs.scalars import float_or, optional_float, text_or_none

__all__ = ["finding_evidence_from_mapping"]


def finding_evidence_from_mapping(payload: Mapping[str, object]) -> FindingEvidence:
    """Decode a canonical evidence payload into a domain ``FindingEvidence``."""

    phase_conf = payload.get("per_phase_confidence")
    phase_items: tuple[tuple[str, float], ...] = ()
    if isinstance(phase_conf, dict):
        phase_items = tuple(
            (str(key), confidence)
            for key, value in sorted(phase_conf.items())
            if (confidence := optional_float(value)) is not None
        )

    focused_speed_band = payload.get("focused_speed_band")
    possible_samples = payload.get("possible_samples")
    matched_samples = payload.get("matched_samples")
    phases_with_evidence = payload.get("phases_with_evidence")
    return FindingEvidence(
        match_rate=float_or(payload.get("match_rate")),
        global_match_rate=optional_float(payload.get("global_match_rate")),
        focused_speed_band=text_or_none(focused_speed_band),
        mean_relative_error=optional_float(payload.get("mean_relative_error")),
        mean_noise_floor_db=optional_float(payload.get("mean_noise_floor_db")),
        possible_samples=(
            int(possible_samples) if isinstance(possible_samples, (int, float)) else None
        ),
        matched_samples=(
            int(matched_samples) if isinstance(matched_samples, (int, float)) else None
        ),
        snr_db=optional_float(payload.get("snr_db")),
        presence_ratio=float_or(payload.get("presence_ratio")),
        burstiness=float_or(payload.get("burstiness")),
        spatial_concentration=float_or(payload.get("spatial_concentration")),
        frequency_correlation=float_or(payload.get("frequency_correlation")),
        speed_uniformity=float_or(payload.get("speed_uniformity")),
        spatial_uniformity=float_or(payload.get("spatial_uniformity")),
        phases_with_evidence=(
            int(phases_with_evidence) if isinstance(phases_with_evidence, (int, float)) else None
        ),
        phase_confidences=phase_items,
        vibration_strength_db=optional_float(payload.get("vibration_strength_db")),
    )
