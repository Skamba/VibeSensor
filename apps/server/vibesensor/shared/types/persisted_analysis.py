"""App-level persisted-analysis model used across persistence and history layers."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from copy import deepcopy
from dataclasses import dataclass

from vibesensor.shared.types.json_types import JsonObject

PERSISTED_ANALYSIS_SCHEMA_VERSION = 1
_STORAGE_SCHEMA_VERSION_KEY = "_schema_version"


@dataclass(frozen=True, slots=True)
class PersistedAnalysis(Mapping[str, object]):
    """Internal persisted-analysis object with explicit payload conversion helpers."""

    _payload: JsonObject

    @classmethod
    def from_json_object(cls, payload: JsonObject) -> PersistedAnalysis:
        return cls(_payload=deepcopy(payload))

    @classmethod
    def from_storage_json_object(cls, payload: JsonObject) -> PersistedAnalysis:
        normalized = deepcopy(payload)
        raw_version = normalized.pop(_STORAGE_SCHEMA_VERSION_KEY, 0)
        if raw_version not in (0, PERSISTED_ANALYSIS_SCHEMA_VERSION):
            raise ValueError(f"Unsupported persisted analysis schema version: {raw_version!r}")
        return cls(_payload=normalized)

    def to_json_object(self) -> JsonObject:
        return deepcopy(self._payload)

    def to_storage_json_object(self) -> JsonObject:
        payload = self.to_json_object()
        payload[_STORAGE_SCHEMA_VERSION_KEY] = PERSISTED_ANALYSIS_SCHEMA_VERSION
        return payload

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
