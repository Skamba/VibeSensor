"""Boundary codecs for ``CarSnapshot``."""

from __future__ import annotations

import math
from collections.abc import Mapping

from vibesensor.domain import CarSnapshot
from vibesensor.shared.types.json_types import JsonObject


def car_snapshot_from_mapping(payload: object) -> CarSnapshot | None:
    """Decode a raw mapping into a typed car snapshot."""

    if not isinstance(payload, Mapping):
        return None
    raw_aspects = payload.get("aspects")
    aspects: dict[str, float] = {}
    if isinstance(raw_aspects, Mapping):
        for key, value in raw_aspects.items():
            if not isinstance(key, str):
                continue
            numeric = _float_or_none(value)
            if numeric is not None:
                aspects[key] = numeric
    return CarSnapshot(
        car_id=_text_or_none(payload.get("id")),
        name=_text_or_none(payload.get("name")),
        car_type=_text_or_none(payload.get("type")),
        variant=_text_or_none(payload.get("variant")),
        aspects=aspects,
    )


def car_snapshot_to_metadata(snapshot: CarSnapshot | None) -> JsonObject | None:
    """Project a typed car snapshot into the canonical persisted metadata shape."""

    if snapshot is None:
        return None
    return {
        "id": snapshot.car_id,
        "name": snapshot.name,
        "type": snapshot.car_type,
        "variant": snapshot.variant,
        "aspects": dict(snapshot.aspects),
    }


def _text_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float_or_none(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            numeric = float(text)
        except ValueError:
            return None
        return numeric if math.isfinite(numeric) else None
    return None
