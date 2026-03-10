from __future__ import annotations

import math

from vibesensor.core.vibration_strength import compute_vibration_strength_db


def test_core_processing_produces_canonical_metric_fields() -> None:
    freq_hz = [10.0, 12.0, 14.0, 16.0]
    combined = [0.01, 0.12, 0.02, 0.01]
    result = compute_vibration_strength_db(freq_hz=freq_hz, combined_spectrum_amp_g_values=combined)

    assert "vibration_strength_db" in result
    assert "strength_bucket" in result
    db_val = result["vibration_strength_db"]
    assert isinstance(db_val, float)
    assert math.isfinite(db_val), f"vibration_strength_db must be finite, got {db_val}"
    assert db_val >= 0, f"vibration_strength_db must be non-negative, got {db_val}"
