"""Guard: shared metric field names stay aligned with backend strength payload fields."""

from __future__ import annotations

from vibesensor.shared.strength_fields import METRIC_FIELDS
from vibesensor.vibration_strength import StrengthPeak as StrengthPeakTD
from vibesensor.vibration_strength import VibrationStrengthMetrics as VibrationStrengthMetricsTD


def _typeddict_field_names(cls: type) -> set[str]:
    return set(cls.__required_keys__ | cls.__optional_keys__)


def test_backend_metric_fields_match_strength_payload_fields() -> None:
    """Shared METRIC_FIELDS must stay aligned with backend strength payload fields."""
    backend_peak_fields = _typeddict_field_names(StrengthPeakTD)
    backend_metrics_fields = _typeddict_field_names(VibrationStrengthMetricsTD)
    expected_metric_fields = set(METRIC_FIELDS.values())

    assert expected_metric_fields, "METRIC_FIELDS must not be empty."
    assert expected_metric_fields <= backend_peak_fields, (
        "StrengthPeak TypedDict drifted from the shared frontend metric fields.\n"
        f"  TypedDict fields: {sorted(backend_peak_fields)}\n"
        f"  Expected:       {sorted(expected_metric_fields)}"
    )
    assert expected_metric_fields <= backend_metrics_fields, (
        "VibrationStrengthMetrics TypedDict drifted from the shared frontend metric fields.\n"
        f"  TypedDict fields: {sorted(backend_metrics_fields)}\n"
        f"  Expected:       {sorted(expected_metric_fields)}"
    )
