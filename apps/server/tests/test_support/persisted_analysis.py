from __future__ import annotations

from vibesensor.shared.types.persisted_analysis import PersistedAnalysis


def make_persisted_analysis(payload: dict[str, object] | PersistedAnalysis) -> PersistedAnalysis:
    if isinstance(payload, PersistedAnalysis):
        return payload
    return PersistedAnalysis.from_json_object(dict(payload))
