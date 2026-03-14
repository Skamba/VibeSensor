"""Signature recognition service."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from ..observation import Observation
from ..signature import Signature


def recognize_signatures(observations: Sequence[Observation]) -> tuple[Signature, ...]:
    grouped: dict[tuple[str, str], list[Observation]] = defaultdict(list)
    for obs in observations:
        if not obs.supports_signature:
            continue
        grouped[(str(obs.source), obs.signature_key)].append(obs)
    signatures: list[Signature] = []
    for (_source_raw, signature_key), grouped_obs in grouped.items():
        signatures.append(
            Signature(
                key=signature_key,
                source=grouped_obs[0].source,
                label=grouped_obs[0].signature_key.replace("_", " "),
                observation_ids=tuple(o.observation_id for o in grouped_obs),
                support_score=min(1.0, sum(o.support_score for o in grouped_obs)),
            )
        )
    return tuple(sorted(signatures, key=lambda s: (-s.support_score, s.key)))
