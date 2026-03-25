from __future__ import annotations

import vibesensor.shared.boundaries.analysis_payload as analysis_payload
import vibesensor.shared.json_utils as json_utils
import vibesensor.shared.types.history_analysis_contracts as history_analysis_contracts


def test_analysis_payload_module_stays_schema_only() -> None:
    assert not hasattr(analysis_payload, "matched_point_from_observation")
    assert not hasattr(analysis_payload, "OrderMatchObservation")
    assert not hasattr(analysis_payload, "AnalysisSummary")


def test_analysis_summary_contract_is_owned_by_history_analysis_contracts() -> None:
    assert hasattr(history_analysis_contracts, "AnalysisSummary")


def test_payload_json_helpers_live_outside_history_analysis_contracts() -> None:
    assert not hasattr(history_analysis_contracts, "payload_value_from_json")
    assert not hasattr(history_analysis_contracts, "payload_object_from_json")
    assert not hasattr(history_analysis_contracts, "payload_objects_from_json")
    assert hasattr(json_utils, "payload_value_from_json")
    assert hasattr(json_utils, "payload_object_from_json")
    assert hasattr(json_utils, "payload_objects_from_json")
