from __future__ import annotations

from vibesensor.shared.boundaries.persisted_analysis_codec import (
    persisted_analysis_from_json_object,
)
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis


def make_persisted_analysis(payload: dict[str, object] | PersistedAnalysis) -> PersistedAnalysis:
    if isinstance(payload, PersistedAnalysis):
        return payload
    return persisted_analysis_from_json_object(dict(payload))
