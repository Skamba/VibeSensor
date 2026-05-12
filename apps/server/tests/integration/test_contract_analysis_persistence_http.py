"""Contract bridge tests: Analysis → Persistence → HTTP boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import pytest
from test_support.analysis import run_analysis
from test_support.report_helpers import report_sample

from vibesensor.adapters.history import ProjectedHistoryRunService
from vibesensor.domain import RunStatus
from vibesensor.shared.boundaries.analysis_payloads import (
    persisted_analysis_from_storage_json_object,
    persisted_analysis_to_storage_json_object,
)
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.types.history_analysis_contracts import AnalysisSummary
from vibesensor.shared.types.history_records import StoredHistoryRun
from vibesensor.shared.types.persisted_analysis import (
    PERSISTED_ANALYSIS_SCHEMA_VERSION,
    PersistedAnalysis,
)
from vibesensor.shared.types.raw_capture import (
    RawCaptureManifest,
    RawCaptureSensorRange,
    RawRunCapture,
)
from vibesensor.use_cases.history.runs import HistoryRunService

pytestmark = pytest.mark.smoke


@dataclass
class _RunPersistenceStub:
    run: StoredHistoryRun

    async def aget_run(self, run_id: str) -> StoredHistoryRun | None:
        if run_id != self.run.run_id:
            return None
        return self.run

    async def aget_raw_capture_manifest(self, _run_id: str) -> RawCaptureManifest | None:
        return None

    async def aload_raw_capture(self, _run_id: str) -> RawRunCapture | None:
        return None

    async def aload_raw_capture_sensor_range(
        self,
        _run_id: str,
        client_id: str,
        *,
        sample_start: int,
        sample_count: int,
    ) -> RawCaptureSensorRange | None:
        return RawCaptureSensorRange.missing(
            client_id=client_id,
            requested_sample_start=sample_start,
            requested_sample_count=sample_count,
        )


def _representative_summary() -> AnalysisSummary:
    return cast(
        AnalysisSummary,
        run_analysis(
            [
                report_sample(
                    0,
                    speed_kmh=55.0,
                    dominant_freq_hz=15.0,
                    peak_amp_g=0.12,
                ),
                report_sample(
                    1,
                    speed_kmh=65.0,
                    dominant_freq_hz=15.0,
                    peak_amp_g=0.14,
                ),
            ],
            language="en",
        ),
    )


def _stored_run_from_summary(
    summary: AnalysisSummary,
) -> tuple[StoredHistoryRun, AnalysisSummary]:
    persisted = PersistedAnalysis.from_json_object(summary)
    storage_payload = persisted_analysis_to_storage_json_object(persisted)
    assert storage_payload["_schema_version"] == PERSISTED_ANALYSIS_SCHEMA_VERSION

    reloaded = persisted_analysis_from_storage_json_object(storage_payload)
    restored_summary = cast(AnalysisSummary, reloaded.to_json_object())

    metadata = run_metadata_from_mapping(
        {
            "run_id": str(summary.get("run_id") or "run-1"),
            "start_time_utc": (
                str(summary.get("start_time_utc"))
                if summary.get("start_time_utc") is not None
                else "2026-01-01T00:00:00Z"
            ),
            "end_time_utc": summary.get("end_time_utc"),
            "sensor_model": str(summary.get("sensor_model") or "ADXL345"),
            "raw_sample_rate_hz": int(summary.get("raw_sample_rate_hz") or 800),
            "feature_interval_s": float(summary.get("feature_interval_s") or 1.0),
            **dict(summary.get("metadata") or {}),
        }
    )
    run = StoredHistoryRun(
        run_id=metadata.run_id or "run-1",
        status=RunStatus.COMPLETE,
        start_time_utc=metadata.start_time_utc,
        end_time_utc=metadata.end_time_utc,
        metadata=metadata,
        created_at=metadata.start_time_utc,
        sample_count=int(summary.get("rows") or 0),
        analysis=reloaded,
        analysis_completed_at=metadata.end_time_utc,
    )
    return run, restored_summary


@pytest.mark.asyncio
async def test_representative_analysis_contract_survives_persistence_and_http_layers() -> None:
    summary = _representative_summary()
    stored_run, restored_summary = _stored_run_from_summary(summary)

    service = ProjectedHistoryRunService(HistoryRunService(_RunPersistenceStub(stored_run)))

    run_response = await service.get_run(stored_run.run_id)
    insights_response = await service.get_insights(stored_run.run_id, requested_lang="en")

    assert run_response.analysis is not None
    assert insights_response is not None

    restored_analysis = restored_summary
    run_analysis_payload = run_response.analysis
    insights_payload = insights_response

    restored_top = restored_analysis["top_causes"][0]
    run_top = run_analysis_payload["top_causes"][0]
    insights_top = insights_payload["top_causes"][0]

    assert set(restored_top) == set(run_top) == set(insights_top)

    for field in ("run_id", "file_name", "lang"):
        assert run_analysis_payload[field] == restored_analysis[field]
        assert insights_payload[field] == restored_analysis[field]

    assert run_analysis_payload["top_causes"]
    assert insights_payload["top_causes"]
    assert run_analysis_payload["findings"]
    assert insights_payload["findings"]
    assert run_top["finding_id"] == restored_top["finding_id"]
    assert insights_top["finding_id"] == restored_top["finding_id"]
    assert (
        run_analysis_payload["findings"][0]["finding_id"]
        == restored_analysis["findings"][0]["finding_id"]
    )
    assert (
        insights_payload["findings"][0]["finding_id"]
        == restored_analysis["findings"][0]["finding_id"]
    )
    assert run_top == insights_top
