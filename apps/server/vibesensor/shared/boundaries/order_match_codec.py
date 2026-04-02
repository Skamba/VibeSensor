"""Boundary codecs for ``OrderMatchObservation`` payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from vibesensor.domain import OrderMatchObservation, coerce_float

__all__ = [
    "order_match_observation_from_mapping",
    "order_match_observations_from_sequence",
]


def order_match_observation_from_mapping(raw: Mapping[str, object]) -> OrderMatchObservation:
    """Decode one raw mapping into a typed order-match observation."""

    def _opt_float(key: str) -> float | None:
        value = raw.get(key)
        if value is None:
            return None
        try:
            return coerce_float(value)
        except (TypeError, ValueError):
            return None

    def _float(key: str, default: float = 0.0) -> float:
        value = raw.get(key)
        if value is None:
            return default
        try:
            return coerce_float(value)
        except (TypeError, ValueError):
            return default

    return OrderMatchObservation(
        predicted_hz=_float("predicted_hz"),
        matched_hz=_float("matched_hz"),
        rel_error=_float("rel_error"),
        amp=_float("amp"),
        location=str(raw.get("location", "")),
        t_s=_opt_float("t_s"),
        speed_kmh=_opt_float("speed_kmh"),
        phase=str(raw["phase"]) if raw.get("phase") is not None else None,
    )


def order_match_observations_from_sequence(
    payload: Sequence[object],
) -> tuple[OrderMatchObservation, ...]:
    """Decode a sequence of raw payload rows into typed observations."""
    return tuple(
        order_match_observation_from_mapping(item) for item in payload if isinstance(item, Mapping)
    )
