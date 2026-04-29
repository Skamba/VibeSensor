"""Shared JSONL sidecar serialization helpers for whole-run diagnostics artifacts."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

from vibesensor.shared.json_utils import safe_json_dumps, safe_json_loads
from vibesensor.shared.types.json_types import JsonObject, is_json_object


class _JsonSidecarObject(Protocol):
    def to_json_object(self) -> JsonObject: ...


def jsonl_bytes_from_objects(objects: Sequence[_JsonSidecarObject]) -> bytes:
    if not objects:
        return b""
    lines = [safe_json_dumps(obj.to_json_object()).encode("utf-8") for obj in objects]
    return b"\n".join(lines) + b"\n"


def jsonl_objects_from_bytes[T](
    payload: bytes,
    *,
    context: str,
    line_description: str,
    from_mapping: Callable[[JsonObject], T],
) -> tuple[T, ...]:
    if not payload:
        return ()
    objects: list[T] = []
    for raw_line in payload.decode("utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parsed = safe_json_loads(line, context=context)
        if not is_json_object(parsed):
            raise ValueError(f"{line_description} must decode to a JSON object")
        objects.append(from_mapping(parsed))
    return tuple(objects)
