from __future__ import annotations

from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.use_cases.history.report_loader import HistoryReportRequestLoader


def test_report_loader_enriches_analysis_with_finalization_stage_metadata() -> None:
    metadata = run_metadata_from_mapping(
        {
            "run_id": "run-1",
            "start_time_utc": "2026-01-01T00:00:00Z",
            "sensor_model": "ADXL345",
            "finalization_stages": [
                {
                    "stage_name": "FinalizeRawCaptureStage",
                    "status": "degraded",
                    "duration_ms": 7,
                    "diagnostic_context": {"raw_capture_status": "timeout"},
                }
            ],
        }
    )
    analysis = PersistedAnalysis.from_json_object(
        {
            "run_id": "run-1",
            "metadata": {
                "run_id": "run-1",
                "sensor_model": "ADXL345",
            },
        }
    )

    enriched = HistoryReportRequestLoader._analysis_with_report_metadata(analysis, metadata)

    enriched_metadata = enriched.to_json_object()["metadata"]
    assert isinstance(enriched_metadata, dict)
    assert enriched_metadata["run_id"] == "run-1"
    assert enriched_metadata["sensor_model"] == "ADXL345"
    assert enriched_metadata["finalization_stages"] == [
        {
            "stage_name": "FinalizeRawCaptureStage",
            "status": "degraded",
            "duration_ms": 7,
            "diagnostic_context": {"raw_capture_status": "timeout"},
        }
    ]
