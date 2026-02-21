from __future__ import annotations

from vibesensor_core.vibration_strength import compute_vibration_strength_db
from vibesensor_shared.contracts import METRIC_FIELDS


def test_core_processing_produces_canonical_metric_fields() -> None:
    freq_hz = [10.0, 12.0, 14.0, 16.0]
    combined = [0.01, 0.12, 0.02, 0.01]
    result = compute_vibration_strength_db(freq_hz=freq_hz, combined_spectrum_amp_g_values=combined)

    assert METRIC_FIELDS["vibration_strength_db"] in result
    assert METRIC_FIELDS["strength_bucket"] in result
    assert isinstance(result[METRIC_FIELDS["vibration_strength_db"]], float)
