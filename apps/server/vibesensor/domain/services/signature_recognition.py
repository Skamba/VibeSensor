"""Signature recognition service."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from ..observation import Observation
from ..signature import Signature


def recognize_signatures(observations: Sequence[Observation]) -> tuple[Signature, ...]:
    grouped: dict[tuple[str, str], list[Observation]] = defaultdict(list)
    for observation in observations:
        grouped[(str(observation.source), observation.signature_key)].append(observation)
    signatures: list[Signature] = []
    for (_source_raw, signature_key), grouped_observations in grouped.items():
        signatures.append(
            Signature(
                key=signature_key,
                source=grouped_observations[0].source,
                label=grouped_observations[0].signature_key.replace("_", " "),
                observation_ids=tuple(obs.observation_id for obs in grouped_observations),
                support_score=max(obs.support_score for obs in grouped_observations),
            )
        )
    return tuple(sorted(signatures, key=lambda item: (-item.support_score, item.key)))
