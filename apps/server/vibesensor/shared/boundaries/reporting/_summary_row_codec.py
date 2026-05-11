"""Reusable row-codec primitives for report summary boundary payloads."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from vibesensor.shared.boundaries.codecs.scalars import (
    coerce_count,
    optional_float,
    text_or_none,
)


@dataclass(frozen=True, slots=True)
class _FieldDecoder:
    name: str
    read: Callable[[Mapping[str, object]], object]


@dataclass(frozen=True, slots=True)
class _RowDecoder[RowModelT]:
    factory: Callable[..., RowModelT]
    fields: tuple[_FieldDecoder, ...]
    required_fields: frozenset[str] = frozenset()


def _field(name: str, read: Callable[[Mapping[str, object]], object]) -> _FieldDecoder:
    return _FieldDecoder(name=name, read=read)


def _payload_field(name: str, read: Callable[[object], object]) -> _FieldDecoder:
    def read_field(row: Mapping[str, object]) -> object:
        return read(row.get(name))

    return _field(name, read_field)


def _text_field(name: str) -> _FieldDecoder:
    return _payload_field(name, text_or_none)


def _float_field(name: str) -> _FieldDecoder:
    return _payload_field(name, optional_float)


def _float_or_field(name: str, default: float = 0.0) -> _FieldDecoder:
    def read_float_or(raw: object) -> object:
        return optional_float(raw) or default

    return _payload_field(name, read_float_or)


def _count_field(name: str) -> _FieldDecoder:
    return _payload_field(name, coerce_count)


def _optional_count(raw_value: object) -> int | None:
    if raw_value is None or isinstance(raw_value, bool):
        return None
    try:
        return coerce_count(raw_value)
    except (TypeError, ValueError):
        return None


def _optional_count_field(name: str) -> _FieldDecoder:
    return _payload_field(name, _optional_count)


def _bool_field(name: str) -> _FieldDecoder:
    return _payload_field(name, bool)


def _text_tuple(raw_values: object) -> tuple[str, ...]:
    if not isinstance(raw_values, list):
        return ()
    return tuple(
        value
        for value in (text_or_none(raw_value) for raw_value in raw_values)
        if value is not None
    )


def _text_tuple_field(name: str) -> _FieldDecoder:
    return _payload_field(name, _text_tuple)


def _literal_text_or_none[LiteralTextT: str](
    raw_value: object,
    allowed: frozenset[LiteralTextT],
) -> LiteralTextT | None:
    value = text_or_none(raw_value)
    if value is None or value not in allowed:
        return None
    return value


def _enum_field[LiteralTextT: str](
    name: str,
    allowed: frozenset[LiteralTextT],
) -> _FieldDecoder:
    def read_enum(raw: object) -> object:
        return _literal_text_or_none(raw, allowed)

    return _payload_field(name, read_enum)


def _decode_row[RowModelT](
    raw: object,
    decoder: _RowDecoder[RowModelT],
) -> RowModelT | None:
    if not isinstance(raw, Mapping):
        return None
    values = {field.name: field.read(raw) for field in decoder.fields}
    if any(values[name] is None for name in decoder.required_fields):
        return None
    return decoder.factory(**values)


def _decode_rows[RowModelT](
    raw_rows: object,
    decoder: _RowDecoder[RowModelT],
) -> tuple[RowModelT, ...]:
    if not isinstance(raw_rows, list):
        return ()
    return tuple(decoded for row in raw_rows if (decoded := _decode_row(row, decoder)) is not None)


def _rows_field[RowModelT](
    name: str,
    decoder: _RowDecoder[RowModelT],
) -> _FieldDecoder:
    def read_rows(raw: object) -> object:
        return _decode_rows(raw, decoder)

    return _payload_field(name, read_rows)


def _row_field[RowModelT](
    name: str,
    decoder: _RowDecoder[RowModelT],
    default: RowModelT,
) -> _FieldDecoder:
    def read_row(raw: object) -> object:
        return _decode_row(raw, decoder) or default

    return _payload_field(name, read_row)
