"""Typed strength-metrics extraction for live sample construction."""

from __future__ import annotations

from vibesensor.domain.strength_metrics import StrengthMetrics
from vibesensor.shared.boundaries.strength_metrics_codec import strength_metrics_from_mapping
from vibesensor.shared.types.payload_types import ClientMetrics

__all__ = ["dominant_hz_from_strength", "extract_strength_data"]


def extract_strength_data(metrics: ClientMetrics) -> StrengthMetrics:
    """Extract strength metrics and top peaks from client metrics."""

    combined_metrics = metrics.get("combined")
    raw_strength_metrics = (
        combined_metrics.get("strength_metrics") if combined_metrics is not None else None
    )
    return strength_metrics_from_mapping(raw_strength_metrics)


def dominant_hz_from_strength(strength_metrics: StrengthMetrics) -> float | None:
    """Return the frequency of the strongest peak, or ``None``."""

    return strength_metrics.dominant_hz
