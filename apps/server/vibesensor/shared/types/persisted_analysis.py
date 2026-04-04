"""App-level persisted-analysis model used across persistence and history layers."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import cast

from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.persisted_analysis_contracts import PersistedAnalysisPayload

__all__ = [
    "PERSISTED_ANALYSIS_SCHEMA_VERSION",
    "PersistedAnalysis",
    "STORAGE_SCHEMA_VERSION_KEY",
]

PERSISTED_ANALYSIS_SCHEMA_VERSION = 1
STORAGE_SCHEMA_VERSION_KEY = "_schema_version"


@dataclass(frozen=True, slots=True)
class PersistedAnalysis(Mapping[str, object]):
    """Internal persisted-analysis value object without transport/storage codecs."""

    payload: PersistedAnalysisPayload

    def __getitem__(self, key: str) -> object:
        return cast(Mapping[str, object], self.payload)[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.payload)

    def __len__(self) -> int:
        return len(self.payload)

    @classmethod
    def from_json_object(cls, payload: Mapping[str, object]) -> PersistedAnalysis:
        """Create a persisted-analysis value object from an in-memory JSON mapping."""

        return cls(
            payload=deepcopy(cast(PersistedAnalysisPayload, dict(payload))),
        )

    def to_json_object(self) -> JsonObject:
        """Return a deep-copied JSON payload for in-memory consumers."""

        return cast(JsonObject, deepcopy(self.payload))

    @property
    def language(self) -> str:
        """Return the persisted language code, or an empty string when absent."""
        value = self.payload.get("lang")
        return value if isinstance(value, str) else ""

    def __eq__(self, other: object) -> bool:
        if isinstance(other, PersistedAnalysis):
            return self.payload == other.payload
        if isinstance(other, dict):
            return self.payload == other
        return False
