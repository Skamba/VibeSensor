from __future__ import annotations

import vibesensor.shared.boundaries.analysis_payloads as analysis_payloads
import vibesensor.shared.boundaries.analysis_payloads.reconstruction as reconstruction
import vibesensor.shared.boundaries.clients as clients
import vibesensor.shared.boundaries.runs as runs
import vibesensor.shared.boundaries.sensor_frames as sensor_frames
import vibesensor.shared.boundaries.settings as settings
import vibesensor.shared.boundaries.summary_fields as summary_fields


def test_analysis_payloads_package_exposes_canonical_entrypoints() -> None:
    assert callable(analysis_payloads.analysis_result_to_summary)
    assert callable(analysis_payloads.analysis_summary_with_warnings)
    assert callable(analysis_payloads.project_analysis_summary)
    assert callable(analysis_payloads.project_persisted_analysis)
    assert callable(analysis_payloads.persisted_analysis_from_storage_json_object)
    assert callable(analysis_payloads.persisted_analysis_to_storage_json_object)
    assert callable(reconstruction.diagnostic_case_from_summary)
    assert callable(reconstruction.test_run_from_summary)
    assert callable(reconstruction.test_run_from_persisted_analysis)


def test_sensor_frames_package_keeps_shared_field_list_public() -> None:
    assert sensor_frames.SENSOR_FRAME_FIELD_NAMES[-1] == "top_peaks"
    assert callable(sensor_frames.sensor_frame_from_mapping)
    assert callable(sensor_frames.sensor_frame_to_json_object)
    assert callable(sensor_frames.sensor_frame_from_row)
    assert callable(sensor_frames.sensor_frame_to_row_values)


def test_clients_package_exposes_canonical_entrypoints() -> None:
    assert callable(clients.build_client_api_row)
    assert callable(clients.build_client_api_rows)
    assert callable(clients.snapshot_for_api)


def test_runs_package_exposes_canonical_entrypoints() -> None:
    assert callable(runs.run_metadata_from_mapping)
    assert callable(runs.run_metadata_to_json_object)
    assert callable(runs.configuration_snapshot_from_run_metadata)
    assert callable(runs.car_from_run_metadata)
    assert callable(runs.symptom_from_run_metadata)
    assert callable(runs.run_suitability_from_payload)
    assert callable(runs.run_suitability_payload)
    assert callable(runs.read_jsonl_run)


def test_summary_fields_package_exposes_canonical_entrypoints() -> None:
    assert callable(summary_fields.finding_from_payload)
    assert callable(summary_fields.finding_payload_from_domain)
    assert callable(summary_fields.location_hotspot_from_payload)
    assert callable(summary_fields.origin_payload_from_finding)
    assert callable(summary_fields.summary_warning_payloads)
    assert callable(summary_fields.step_payloads_from_plan)
    assert callable(summary_fields.build_evidence_metrics)


def test_settings_package_exposes_settings_codecs() -> None:
    assert callable(settings.analysis_settings_response_payload)
    assert callable(settings.analysis_settings_update_payload_from_mapping)
    assert callable(settings.car_config_update_payload_from_mapping)
    assert callable(settings.cars_response_payload)
    assert callable(settings.language_response_payload)
    assert callable(settings.speed_source_response_payload)
    assert callable(settings.speed_source_update_payload_from_mapping)
    assert callable(settings.speed_unit_response_payload)
