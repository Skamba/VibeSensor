from __future__ import annotations

import vibesensor.shared.boundaries.analysis_payload as analysis_payload


def test_analysis_payload_module_stays_schema_only() -> None:
    assert not hasattr(analysis_payload, "matched_point_from_observation")
    assert not hasattr(analysis_payload, "OrderMatchObservation")
