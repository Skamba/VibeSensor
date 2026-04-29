"""Shared JSON helpers for whole-run contracts and persisted artifacts."""

from __future__ import annotations

from collections.abc import Callable

from vibesensor.shared.types.json_types import JsonObject, JsonValue


def set_optional_value(payload: JsonObject, key: str, value: JsonValue | None) -> None:
    if value is not None:
        payload[key] = value


def non_empty_text_or_none(
    value: object,
    *,
    strict: bool = False,
    invalid_message: str = "optional text field must be a string or null",
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        if strict:
            raise ValueError(invalid_message)
        return None
    text = value.strip()
    return text or None


def required_non_empty_text(
    data: JsonObject,
    field_name: str,
    *,
    invalid_message: str,
) -> str:
    text = non_empty_text_or_none(data.get(field_name))
    if text is None:
        raise ValueError(invalid_message)
    return text


def required_bool_field(
    data: JsonObject,
    field_name: str,
    *,
    invalid_message: str,
) -> bool:
    value = data.get(field_name)
    if not isinstance(value, bool):
        raise ValueError(invalid_message)
    return value


def required_int_field(
    data: JsonObject,
    field_name: str,
    *,
    invalid_message: str,
) -> int:
    value = data.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(invalid_message)
    return value


def required_float_field(
    data: JsonObject,
    field_name: str,
    *,
    invalid_message: str,
) -> float:
    value = optional_float_or_none(data.get(field_name))
    if value is None:
        raise ValueError(invalid_message)
    return value


def optional_int_or_none(
    value: object,
    *,
    strict: bool = False,
    invalid_message: str = "optional int field must be an int or null",
) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        if strict:
            raise ValueError(invalid_message)
        return None
    return value


def optional_float_or_none(
    value: object,
    *,
    strict: bool = False,
    invalid_message: str = "optional numeric field must be a number or null",
) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        if strict:
            raise ValueError(invalid_message)
        return None
    return float(value)


def coerce_int_or_none(value: JsonValue | object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, str)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return None


def coerce_int_or_default(value: JsonValue | object, default: int = 0) -> int:
    parsed = coerce_int_or_none(value)
    return parsed if parsed is not None else default


def coerce_float_or_none(value: JsonValue | object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None


def coerce_float_or_default(value: JsonValue | object, default: float = 0.0) -> float:
    parsed = coerce_float_or_none(value)
    return parsed if parsed is not None else default


def json_text_or_default(value: JsonValue | object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def json_text_or_none(value: JsonValue | object) -> str | None:
    return value if isinstance(value, str) else None


def tuple_from_mapping_list_field[T](
    data: JsonObject,
    field_name: str,
    row_from_mapping: Callable[[JsonObject], T],
) -> tuple[T, ...]:
    raw_rows = data.get(field_name)
    if not isinstance(raw_rows, list):
        return ()
    return tuple(row_from_mapping(row) for row in raw_rows if isinstance(row, dict))
