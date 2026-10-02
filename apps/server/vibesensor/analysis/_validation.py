"""Diagnostics input validation helpers."""

from __future__ import annotations

from collections.abc import Sequence

from vibesensor.analysis._types import Sample


class MissingStrengthMetricsError(ValueError):
    """The run has samples but none carries precomputed strength metrics.

    This happens when a recording is shorter than one analysis window per
    sensor. It is a property of the recorded data, not a worker bug.
    """


def _validate_required_strength_metrics(samples: Sequence[Sample]) -> None:
    """Require at least one precomputed strength-metric sample in the run input."""
    if not samples:
        return
    first_bad_idx: int | None = None
    for idx, sample in enumerate(samples):
        if sample.vibration_strength_db is not None:
            return
        if first_bad_idx is None:
            first_bad_idx = idx
    raise MissingStrengthMetricsError(
        f"Missing required precomputed strength metrics in sample index "
        f"{first_bad_idx}: vibration_strength_db",
    )
