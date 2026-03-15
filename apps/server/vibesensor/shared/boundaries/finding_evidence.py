"""Boundary decoder: metrics dict → domain FindingEvidence."""

from __future__ import annotations

from vibesensor.domain.finding_evidence import FindingEvidence


def finding_evidence_from_metrics(d: dict[str, object]) -> FindingEvidence:
    """Construct a ``FindingEvidence`` from a ``FindingEvidenceMetrics`` dict."""
    phase_conf = d.get("per_phase_confidence")
    phase_items: tuple[tuple[str, float], ...] = ()
    if isinstance(phase_conf, dict):
        phase_items = tuple(
            (str(k), float(v)) for k, v in sorted(phase_conf.items()) if isinstance(v, (int, float))
        )

    def _float(key: str, *fallbacks: str) -> float:
        for k in (key, *fallbacks):
            raw = d.get(k)
            if raw is not None:
                try:
                    return float(raw)  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    pass
        return 0.0

    def _float_or_none(key: str, *fallbacks: str) -> float | None:
        for k in (key, *fallbacks):
            raw = d.get(k)
            if raw is not None:
                try:
                    return float(raw)  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    pass
        return None

    return FindingEvidence(
        match_rate=_float("match_rate"),
        snr_db=_float_or_none("snr_db", "snr_ratio"),
        presence_ratio=_float("presence_ratio"),
        burstiness=_float("burstiness"),
        spatial_concentration=_float("spatial_concentration"),
        frequency_correlation=_float("frequency_correlation"),
        speed_uniformity=_float("speed_uniformity"),
        spatial_uniformity=_float("spatial_uniformity"),
        phase_confidences=phase_items,
        vibration_strength_db=_float_or_none("vibration_strength_db"),
    )
