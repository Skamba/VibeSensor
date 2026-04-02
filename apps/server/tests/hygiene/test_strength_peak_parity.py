"""Hygiene test: field parity between hot-path TypedDicts and domain dataclasses.

The processing pipeline uses ``StrengthPeak`` / ``VibrationStrengthMetrics``
TypedDicts in ``vibration_strength.py`` for zero-overhead dict construction in
the real-time FFT loop.  The analysis layer uses frozen dataclass equivalents
in ``domain/strength_metrics.py``.  Both must share identical field names so
that the strength-metrics boundary codec can ingest pipeline output without
silent data loss.
"""

from __future__ import annotations

import dataclasses

from vibesensor.domain.strength_metrics import (
    StrengthMetrics as StrengthMetricsDC,
)
from vibesensor.domain.strength_metrics import (
    StrengthPeak as StrengthPeakDC,
)
from vibesensor.vibration_strength import (
    StrengthPeak as StrengthPeakTD,
)
from vibesensor.vibration_strength import (
    VibrationStrengthMetrics as VibrationStrengthMetricsTD,
)


def _dataclass_field_names(cls: type) -> set[str]:
    return {f.name for f in dataclasses.fields(cls)}


def _typeddict_field_names(cls: type) -> set[str]:
    return set(cls.__required_keys__ | cls.__optional_keys__)


class TestStrengthPeakFieldParity:
    """StrengthPeak TypedDict must have the same fields as the dataclass."""

    def test_field_names_match(self) -> None:
        dc_fields = _dataclass_field_names(StrengthPeakDC)
        td_fields = _typeddict_field_names(StrengthPeakTD)
        assert dc_fields == td_fields, (
            f"StrengthPeak field drift!\n"
            f"  dataclass-only: {dc_fields - td_fields}\n"
            f"  TypedDict-only: {td_fields - dc_fields}"
        )


class TestStrengthMetricsFieldParity:
    """VibrationStrengthMetrics TypedDict must have the same fields as StrengthMetrics dataclass."""

    def test_field_names_match(self) -> None:
        dc_fields = _dataclass_field_names(StrengthMetricsDC)
        td_fields = _typeddict_field_names(VibrationStrengthMetricsTD)
        assert dc_fields == td_fields, (
            f"StrengthMetrics field drift!\n"
            f"  dataclass-only: {dc_fields - td_fields}\n"
            f"  TypedDict-only: {td_fields - dc_fields}"
        )
