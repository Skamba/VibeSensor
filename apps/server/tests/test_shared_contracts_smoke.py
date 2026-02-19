from __future__ import annotations

import json
from pathlib import Path

from vibesensor.analysis.vibration_strength import compute_vibration_strength_db
from vibesensor.shared_contracts import METRIC_FIELDS, validate_ingestion_payload


def test_ingestion_payload_fixture_validates() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[3]
        / "libs"
        / "shared"
        / "fixtures"
        / "ingestion_payload.sample.json"
    )
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    ok, message = validate_ingestion_payload(payload)
    assert ok, message


def test_core_processing_produces_canonical_metric_fields() -> None:
    freq_hz = [10.0, 12.0, 14.0, 16.0]
    combined = [0.01, 0.12, 0.02, 0.01]
    result = compute_vibration_strength_db(freq_hz=freq_hz, combined_spectrum_amp_g_values=combined)

    assert METRIC_FIELDS["vibration_strength_db"] in result
    assert METRIC_FIELDS["strength_bucket"] in result
    assert isinstance(result[METRIC_FIELDS["vibration_strength_db"]], float)
