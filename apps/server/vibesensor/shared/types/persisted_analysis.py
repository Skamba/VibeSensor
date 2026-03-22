"""App-level persisted-analysis model used across persistence and history layers."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from copy import deepcopy
from dataclasses import dataclass

from vibesensor.shared.types.json_types import JsonObject


@dataclass(frozen=True, slots=True)
class PersistedAnalysis(Mapping[str, object]):
    """Internal persisted-analysis object with explicit payload conversion helpers."""

    _payload: JsonObject

    @classmethod
    def from_json_object(cls, payload: JsonObject) -> PersistedAnalysis:
        return cls(_payload=deepcopy(payload))

    def to_json_object(self) -> JsonObject:
        return deepcopy(self._payload)

    def __getitem__(self, key: str) -> object:
        return self._payload[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._payload)

    def __len__(self) -> int:
        return len(self._payload)

    @property
    def language(self) -> str:
        value = self._payload.get("lang")
        return value if isinstance(value, str) else ""

    def __eq__(self, other: object) -> bool:
        if isinstance(other, PersistedAnalysis):
            return self._payload == other._payload
        if isinstance(other, dict):
            return self._payload == other
        return False
