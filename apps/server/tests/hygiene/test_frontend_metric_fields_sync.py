"""Guard: frontend METRIC_FIELDS stays in sync with backend strength payload fields."""

from __future__ import annotations

import re

from tests._paths import REPO_ROOT
from vibesensor.vibration_strength import StrengthPeak as StrengthPeakTD
from vibesensor.vibration_strength import VibrationStrengthMetrics as VibrationStrengthMetricsTD

_CONSTANTS_TS = REPO_ROOT / "apps" / "ui" / "src" / "constants.ts"
_EXPECTED_METRIC_FIELDS = {
    "vibration_strength_db": "vibration_strength_db",
    "strength_bucket": "strength_bucket",
}


def _typeddict_field_names(cls: type) -> set[str]:
    return set(cls.__required_keys__ | cls.__optional_keys__)


def _frontend_metric_fields() -> dict[str, str]:
    text = _CONSTANTS_TS.read_text()
    match = re.search(
        r"export const METRIC_FIELDS = \{(?P<body>.*?)\} as const;",
        text,
        flags=re.DOTALL,
    )
    assert match is not None, "METRIC_FIELDS missing from apps/ui/src/constants.ts"
    return dict(re.findall(r'([a-z_]+):\s*"([a-z_]+)"', match.group("body")))


def test_frontend_metric_fields_match_backend_strength_fields() -> None:
    """Frontend METRIC_FIELDS must stay aligned with canonical backend strength field names."""
    backend_peak_fields = _typeddict_field_names(StrengthPeakTD)
    backend_metrics_fields = _typeddict_field_names(VibrationStrengthMetricsTD)
    expected_metric_fields = set(_EXPECTED_METRIC_FIELDS.values())

    assert expected_metric_fields <= backend_peak_fields, (
        "StrengthPeak TypedDict drifted from the canonical frontend metric fields.\n"
        f"  TypedDict fields: {sorted(backend_peak_fields)}\n"
        f"  Expected:       {sorted(expected_metric_fields)}"
    )
    assert expected_metric_fields <= backend_metrics_fields, (
        "VibrationStrengthMetrics TypedDict drifted from the canonical frontend metric fields.\n"
        f"  TypedDict fields: {sorted(backend_metrics_fields)}\n"
        f"  Expected:       {sorted(expected_metric_fields)}"
    )

    frontend_fields = _frontend_metric_fields()
    assert frontend_fields == _EXPECTED_METRIC_FIELDS, (
        "Frontend/backend METRIC_FIELDS drifted.\n"
        f"  Backend:  {_EXPECTED_METRIC_FIELDS}\n"
        f"  Frontend: {frontend_fields}"
    )
