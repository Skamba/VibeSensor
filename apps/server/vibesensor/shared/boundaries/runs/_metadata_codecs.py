"""Shared field-spec codecs for run metadata boundary sections."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import cast

from vibesensor.shared.boundaries.codecs.scalars import text_or_none
from vibesensor.shared.json_utils import as_float_or_none, as_int_or_none
from vibesensor.shared.time_utils import coerce_utc_offset_seconds
from vibesensor.shared.types.json_types import JsonObject, is_json_object
from vibesensor.shared.types.run_schema import (
    RawCaptureFinalizeStatus,
    RunFinalizationStageStatus,
)

type PayloadDecoder = Callable[[Mapping[str, object]], object]
type IncludePredicate = Callable[[object], bool]


def always_include(_value: object) -> bool:
    return True


def include_if_not_none(value: object) -> bool:
    return value is not None


def include_if_nonempty_text(value: object) -> bool:
    return value is not None and bool(str(value).strip())


@dataclass(frozen=True, slots=True)
class PayloadFieldSpec:
    payload_key: str
    field_name: str
    decode: PayloadDecoder
    include: IncludePredicate = always_include


def required_text_decoder(payload_key: str, default: str = "") -> PayloadDecoder:
    def decode(payload: Mapping[str, object]) -> object:
        return text_or_none(payload.get(payload_key)) or default

    return decode


def optional_text_decoder(payload_key: str) -> PayloadDecoder:
    def decode(payload: Mapping[str, object]) -> object:
        return text_or_none(payload.get(payload_key))

    return decode


def int_decoder(payload_key: str) -> PayloadDecoder:
    def decode(payload: Mapping[str, object]) -> object:
        return as_int_or_none(payload.get(payload_key))

    return decode


def float_decoder(payload_key: str) -> PayloadDecoder:
    def decode(payload: Mapping[str, object]) -> object:
        return as_float_or_none(payload.get(payload_key))

    return decode


def bool_decoder(payload_key: str) -> PayloadDecoder:
    def decode(payload: Mapping[str, object]) -> object:
        return bool(payload.get(payload_key, False))

    return decode


def language_decoder(payload_key: str) -> PayloadDecoder:
    def decode(payload: Mapping[str, object]) -> object:
        return normalized_language(payload.get(payload_key))

    return decode


def utc_offset_decoder(payload_key: str) -> PayloadDecoder:
    def decode(payload: Mapping[str, object]) -> object:
        return coerce_utc_offset_seconds(payload.get(payload_key))

    return decode


def raw_capture_finalize_status_decoder(payload_key: str) -> PayloadDecoder:
    def decode(payload: Mapping[str, object]) -> object:
        status = text_or_none(payload.get(payload_key))
        if status not in {"completed", "not_configured", "enqueue_timeout", "timeout", "failed"}:
            return None
        return cast(RawCaptureFinalizeStatus, status)

    return decode


def finalization_stage_status_decoder(payload_key: str) -> PayloadDecoder:
    def decode(payload: Mapping[str, object]) -> object:
        status = text_or_none(payload.get(payload_key))
        if status not in {"ok", "skipped", "degraded", "failed"}:
            return None
        return cast(RunFinalizationStageStatus, status)

    return decode


def tuple_text_decoder(payload_key: str) -> PayloadDecoder:
    def decode(payload: Mapping[str, object]) -> object:
        value = payload.get(payload_key)
        if not isinstance(value, list):
            return ()
        return tuple(text for entry in value if (text := text_or_none(entry)) is not None)

    return decode


def json_object_decoder(payload_key: str) -> PayloadDecoder:
    def decode(payload: Mapping[str, object]) -> object:
        value = payload.get(payload_key)
        return value if is_json_object(value) else {}

    return decode


def decoded_values(
    payload: Mapping[str, object],
    specs: tuple[PayloadFieldSpec, ...],
) -> dict[str, object]:
    return {spec.field_name: spec.decode(payload) for spec in specs}


def project_payload_fields(
    source: object,
    specs: tuple[PayloadFieldSpec, ...],
) -> JsonObject:
    payload: dict[str, object] = {}
    for spec in specs:
        value = getattr(source, spec.field_name)
        if spec.include(value):
            payload[spec.payload_key] = value
    return cast(JsonObject, payload)


def normalized_language(value: object) -> str:
    text = text_or_none(value)
    return text.lower() if text is not None else "en"
