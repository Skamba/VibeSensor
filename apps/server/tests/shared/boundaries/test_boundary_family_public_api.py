from __future__ import annotations

import vibesensor.shared.boundaries.analysis_payloads as analysis_payloads
import vibesensor.shared.boundaries.analysis_payloads.reconstruction as reconstruction
import vibesensor.shared.boundaries.sensor_frames as sensor_frames


def test_analysis_payloads_package_exposes_canonical_entrypoints() -> None:
    assert callable(analysis_payloads.analysis_result_to_summary)
    assert callable(analysis_payloads.analysis_summary_with_warnings)
    assert callable(analysis_payloads.project_analysis_summary)
    assert callable(analysis_payloads.project_persisted_analysis)
    assert callable(analysis_payloads.persisted_analysis_from_storage_json_object)
    assert callable(analysis_payloads.persisted_analysis_to_storage_json_object)
    assert callable(reconstruction.test_run_from_summary)
    assert callable(reconstruction.test_run_from_persisted_analysis)


def test_sensor_frames_package_keeps_shared_field_list_public() -> None:
    assert sensor_frames.SENSOR_FRAME_FIELD_NAMES[-1] == "top_peaks"
    assert callable(sensor_frames.sensor_frame_from_mapping)
    assert callable(sensor_frames.sensor_frame_to_json_object)
    assert callable(sensor_frames.sensor_frame_from_row)
    assert callable(sensor_frames.sensor_frame_to_row_values)
