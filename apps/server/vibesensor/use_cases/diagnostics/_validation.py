"""Diagnostics input validation helpers."""

from __future__ import annotations

from collections.abc import Sequence

from ._types import AnalysisSampleInput, ensure_analysis_sample


def _validate_required_strength_metrics(samples: Sequence[AnalysisSampleInput]) -> None:
    """Require at least one precomputed strength-metric sample in the run input."""
    typed_samples = [ensure_analysis_sample(sample) for sample in samples]
    if not typed_samples:
        return
    first_bad_idx: int | None = None
    for idx, sample in enumerate(typed_samples):
        if sample.vibration_strength_db is not None:
            return
        if first_bad_idx is None:
            first_bad_idx = idx
    raise ValueError(
        f"Missing required precomputed strength metrics in sample index "
        f"{first_bad_idx}: vibration_strength_db",
    )
