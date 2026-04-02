"""Boundary codecs for ``CarSnapshot``."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.domain import CarSnapshot
from vibesensor.shared.order_reference_settings import normalize_order_reference_mapping
from vibesensor.shared.types.json_types import JsonObject


def car_snapshot_from_mapping(payload: object) -> CarSnapshot | None:
    """Decode a raw mapping into a typed car snapshot."""

    if not isinstance(payload, Mapping):
        return None
    raw_aspects = payload.get("aspects")
    aspects = (
        normalize_order_reference_mapping(raw_aspects) if isinstance(raw_aspects, Mapping) else {}
    )
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
    normalized_aspects: JsonObject = {
        key: value for key, value in normalize_order_reference_mapping(snapshot.aspects).items()
    }
    return {
        "id": snapshot.car_id,
        "name": snapshot.name,
        "type": snapshot.car_type,
        "variant": snapshot.variant,
        "aspects": normalized_aspects,
    }


def _text_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
