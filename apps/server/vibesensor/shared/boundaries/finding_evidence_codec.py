"""Boundary decoding helpers for ``FindingEvidence`` payloads."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.domain import FindingEvidence, coerce_float

__all__ = ["finding_evidence_from_mapping"]


def finding_evidence_from_mapping(payload: Mapping[str, object]) -> FindingEvidence:
    """Decode a canonical evidence payload into a domain ``FindingEvidence``."""

    def _float(key: str) -> float:
        raw = payload.get(key)
        if raw is None:
            return 0.0
        try:
            return coerce_float(raw)
        except (TypeError, ValueError):
            return 0.0

    def _float_or_none(key: str) -> float | None:
        raw = payload.get(key)
        if raw is None:
            return None
        try:
            return coerce_float(raw)
        except (TypeError, ValueError):
            return None

    phase_conf = payload.get("per_phase_confidence")
    phase_items: tuple[tuple[str, float], ...] = ()
    if isinstance(phase_conf, dict):
        phase_items = tuple(
            (str(key), float(value))
            for key, value in sorted(phase_conf.items())
            if isinstance(value, (int, float))
        )

    focused_speed_band = payload.get("focused_speed_band")
    possible_samples = payload.get("possible_samples")
    matched_samples = payload.get("matched_samples")
    phases_with_evidence = payload.get("phases_with_evidence")
    return FindingEvidence(
        match_rate=_float("match_rate"),
        global_match_rate=_float_or_none("global_match_rate"),
        focused_speed_band=(
            str(focused_speed_band).strip() if focused_speed_band is not None else None
        ),
        mean_relative_error=_float_or_none("mean_relative_error"),
        mean_noise_floor_db=_float_or_none("mean_noise_floor_db"),
        possible_samples=(
            int(possible_samples) if isinstance(possible_samples, (int, float)) else None
        ),
        matched_samples=(
            int(matched_samples) if isinstance(matched_samples, (int, float)) else None
        ),
        snr_db=_float_or_none("snr_db"),
        presence_ratio=_float("presence_ratio"),
        burstiness=_float("burstiness"),
        spatial_concentration=_float("spatial_concentration"),
        frequency_correlation=_float("frequency_correlation"),
        speed_uniformity=_float("speed_uniformity"),
        spatial_uniformity=_float("spatial_uniformity"),
        phases_with_evidence=(
            int(phases_with_evidence) if isinstance(phases_with_evidence, (int, float)) else None
        ),
        phase_confidences=phase_items,
        vibration_strength_db=_float_or_none("vibration_strength_db"),
    )
