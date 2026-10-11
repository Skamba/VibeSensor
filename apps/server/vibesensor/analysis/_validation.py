"""Diagnostics input validation helpers."""

from __future__ import annotations

import numpy as np

from vibesensor.recording.sample_columns import SampleColumns


class MissingStrengthMetricsError(ValueError):
    """The run has samples but none carries precomputed strength metrics.

    This happens when a recording is shorter than one analysis window per
    sensor. It is a property of the recorded data, not a worker bug.
    """


def _validate_required_strength_metrics(samples: SampleColumns) -> None:
    """Require at least one precomputed strength-metric sample in the run input."""
    if not len(samples) or not np.isnan(samples.vibration_strength_db).all():
        return
    raise MissingStrengthMetricsError(
        "Missing required precomputed strength metrics in sample index 0: vibration_strength_db",
    )
