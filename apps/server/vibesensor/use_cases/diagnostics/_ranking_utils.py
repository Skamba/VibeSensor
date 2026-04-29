"""Shared ranking helpers for diagnostics summarization."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable


def dominant_weighted_value(*, values: Iterable[tuple[str, float]]) -> str | None:
    items = tuple(values)
    if not items:
        return None
    counts = Counter(value for value, _weight in items)
    weights: dict[str, float] = defaultdict(float)
    for value, weight in items:
        weights[value] += float(weight)
    return max(
        counts,
        key=lambda value: (counts[value], weights[value], value),
    )


def sortable_optional_metric(value: float | None) -> float:
    return value if value is not None else float("-inf")
