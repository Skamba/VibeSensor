"""App-level persisted-analysis model used across persistence and history layers."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import cast

from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.persisted_analysis_contracts import PersistedAnalysisPayload

PERSISTED_ANALYSIS_SCHEMA_VERSION = 1
_STORAGE_SCHEMA_VERSION_KEY = "_schema_version"


@dataclass(frozen=True, slots=True)
class PersistedAnalysis(Mapping[str, object]):
    """Internal persisted-analysis object with storage-owned payload helpers."""

    _payload: PersistedAnalysisPayload

    @classmethod
    def from_payload(cls, payload: PersistedAnalysisPayload) -> PersistedAnalysis:
        """Build a persisted-analysis wrapper from a storage-owned payload."""
        return cls(_payload=deepcopy(payload))

    @classmethod
    def from_json_object(cls, payload: JsonObject) -> PersistedAnalysis:
        """Build a persisted-analysis wrapper from a raw JSON payload."""
        return cls.from_payload(cast(PersistedAnalysisPayload, payload))

    @classmethod
    def from_storage_json_object(cls, payload: JsonObject) -> PersistedAnalysis:
        """Build from storage JSON, validating and stripping the schema-version field."""
        normalized = deepcopy(payload)
        raw_version = normalized.pop(_STORAGE_SCHEMA_VERSION_KEY, 0)
        if raw_version not in (0, PERSISTED_ANALYSIS_SCHEMA_VERSION):
            raise ValueError(f"Unsupported persisted analysis schema version: {raw_version!r}")
        return cls.from_payload(cast(PersistedAnalysisPayload, normalized))

    def to_payload(self) -> PersistedAnalysisPayload:
        """Return a deep-copied storage-owned payload for persisted consumers."""
        return deepcopy(self._payload)

    def to_json_object(self) -> JsonObject:
        """Return a deep-copied JSON payload for in-memory consumers."""
        return cast(JsonObject, self.to_payload())

    def to_storage_json_object(self) -> JsonObject:
        """Return a storage payload with the persisted-analysis schema version attached."""
        payload = self.to_json_object()
        payload[_STORAGE_SCHEMA_VERSION_KEY] = PERSISTED_ANALYSIS_SCHEMA_VERSION
        return payload

    def __getitem__(self, key: str) -> object:
        return cast(Mapping[str, object], self._payload)[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._payload)

    def __len__(self) -> int:
        return len(self._payload)

    @property
    def language(self) -> str:
        """Return the persisted language code, or an empty string when absent."""
        value = self._payload.get("lang")
        return value if isinstance(value, str) else ""

    def __eq__(self, other: object) -> bool:
        if isinstance(other, PersistedAnalysis):
            return self._payload == other._payload
        if isinstance(other, dict):
            return self._payload == other
        return False
