"""Focused edge-case tests for history report loading, caching, and exports."""

from __future__ import annotations

import asyncio
import csv
import io
import json
from dataclasses import dataclass
from typing import Any, cast

import pytest
from test_support.persisted_analysis import make_persisted_analysis

from vibesensor.domain import RunStatus
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frame_from_mapping
from vibesensor.shared.exceptions import AnalysisNotReadyError
from vibesensor.shared.types.history_records import StoredHistoryRun
from vibesensor.shared.types.sensor_frame import SensorFrame
from vibesensor.use_cases.history.exports import HistoryExportService
from vibesensor.use_cases.history.report_cache import (
    REPORT_PDF_CACHE_MAX_ENTRIES,
    HistoryReportPdfCache,
)
from vibesensor.use_cases.history.report_loader import HistoryReportRequestLoader


@dataclass
class _HistoryDbStub:
    run: dict[str, Any] | None = None
    samples: list[dict[str, Any]] | None = None

    async def aget_run(self, run_id: str) -> StoredHistoryRun | None:
        if self.run is None:
            return None
        return _stored_run(dict(self.run))

    async def aiter_run_samples(self, run_id: str, batch_size: int = 1000, *, stride: int = 1):
        rows = [
            row if isinstance(row, SensorFrame) else sensor_frame_from_mapping(row)
            for row in (self.samples or [])
        ]
        for start in range(0, len(rows), batch_size):
            yield rows[start : start + batch_size]


def _stored_run(run: dict[str, Any]) -> StoredHistoryRun:
    run_id = str(run.get("run_id") or "run-1")
    metadata_payload = {
        "run_id": run_id,
        "start_time_utc": str(run.get("start_time_utc") or "2026-01-01T00:00:00Z"),
        "end_time_utc": run.get("end_time_utc"),
        "sensor_model": str(run.get("sensor_model") or "ADXL345"),
        "raw_sample_rate_hz": 800,
        "sample_rate_hz": 800,
        "feature_interval_s": 1.0,
        **dict(run.get("metadata") or {}),
    }
    return StoredHistoryRun(
        run_id=run_id,
        status=RunStatus(str(run.get("status") or "complete")),
        start_time_utc=str(run.get("start_time_utc") or "2026-01-01T00:00:00Z"),
        end_time_utc=cast(str | None, run.get("end_time_utc")),
        metadata=run_metadata_from_mapping(metadata_payload),
        created_at=str(run.get("created_at") or "2026-01-01T00:00:00Z"),
        sample_count=int(run.get("sample_count") or 0),
        case_id=cast(str | None, run.get("case_id")),
        analysis=(
            make_persisted_analysis(cast(dict[str, object], run["analysis"]))
            if run.get("analysis") is not None
            else None
        ),
        analysis_corrupt=bool(run.get("analysis_corrupt", False)),
        error_message=cast(str | None, run.get("error_message")),
        analysis_started_at=cast(str | None, run.get("analysis_started_at")),
        analysis_completed_at=cast(str | None, run.get("analysis_completed_at")),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("run_payload", "expected_status", "expected_message"),
    [
        (
            {
                "status": "recording",
                "analysis": None,
            },
            "unavailable",
            "Analysis is not available while recording is still active",
        ),
        (
            {
                "status": "analyzing",
                "analysis": {"lang": "en", "findings": []},
            },
            "in_progress",
            "Analysis is still in progress",
        ),
        (
            {
                "status": "error",
                "error_message": "Analyzer crashed",
                "analysis": {"lang": "en", "findings": []},
            },
            "error",
            "Analyzer crashed",
        ),
        (
            {
                "status": "complete",
                "analysis_corrupt": True,
                "analysis": {"lang": "en", "findings": []},
            },
            "unavailable",
            "Report data unavailable for this run",
        ),
        (
            {
                "status": "complete",
                "analysis": None,
            },
            "unavailable",
            "No analysis available for this run",
        ),
    ],
)
async def test_report_loader_rejects_unavailable_report_states(
    run_payload: dict[str, object],
    expected_status: str,
    expected_message: str,
) -> None:
    loader = HistoryReportRequestLoader(
        _HistoryDbStub(
            run={
                "run_id": "run-1",
                "metadata": {"language": "en"},
                **run_payload,
            }
        )
    )

    with pytest.raises(AnalysisNotReadyError, match=expected_message) as exc_info:
        await loader.load_report_request("run-1", "en")

    assert exc_info.value.status == expected_status


@pytest.mark.asyncio
async def test_report_loader_uses_requested_lang_when_persisted_lang_is_blank() -> None:
    loader = HistoryReportRequestLoader(
        _HistoryDbStub(
            run={
                "run_id": "run/1 sample",
                "status": "complete",
                "metadata": {"language": "en"},
                "analysis": {
                    "lang": "   ",
                    "findings": [],
                    "top_causes": [],
                    "test_plan": [],
                    "run_suitability": [],
                    "most_likely_origin": {},
                },
            }
        )
    )

    request = await loader.load_report_request("run/1 sample", " NL ")

    assert request.prepared.language == "nl"
    assert request.cache_key[1] == "nl"
    assert request.filename == "run_1_sample_report.pdf"


@pytest.mark.asyncio
async def test_report_pdf_cache_retries_after_build_failure() -> None:
    cache = HistoryReportPdfCache()
    cache_key = ("run-1", "en", None, 12, "{}", "analysis", "none")
    calls = 0

    def _build() -> bytes:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")
        return b"%PDF-success"

    with pytest.raises(RuntimeError, match="boom"):
        await cache.get_or_build(cache_key, _build)

    assert cache.get(cache_key) is None

    pdf = await cache.get_or_build(cache_key, _build)

    assert pdf == b"%PDF-success"
    assert calls == 2


def test_report_pdf_cache_evicts_lru_entries_and_drops_evicted_locks() -> None:
    cache = HistoryReportPdfCache()
    keys = [
        (f"run-{index}", "en", None, index, "{}", f"analysis-{index}", "none")
        for index in range(REPORT_PDF_CACHE_MAX_ENTRIES + 1)
    ]

    for index, key in enumerate(keys[:-1]):
        cache._locks[key] = asyncio.Lock()
        cache._put(key, f"%PDF-{index}".encode())

    assert cache.get(keys[0]) == b"%PDF-0"

    cache._locks[keys[-1]] = asyncio.Lock()
    cache._put(keys[-1], b"%PDF-new")

    assert cache.get(keys[1]) is None
    assert keys[1] not in cache._locks
    assert cache.get(keys[0]) == b"%PDF-0"
    assert keys[0] in cache._locks


@pytest.mark.asyncio
async def test_export_service_build_export_context_shapes_raw_csv_and_safe_name() -> None:
    service = HistoryExportService(
        _HistoryDbStub(
            run={
                "run_id": "run/1 sample",
                "status": "complete",
            },
            samples=[
                {
                    "run_id": "run/1 sample",
                    "timestamp_utc": "2026-01-01T00:00:01Z",
                    "t_s": 1.0,
                    "client_id": "sensor-1",
                    "top_peaks": [{"hz": 30.0, "amp": 0.1}],
                    "vibration_strength_db": 21.5,
                    "custom": "drop-me",
                },
                {
                    "run_id": "run/1 sample",
                    "timestamp_utc": "2026-01-01T00:00:02Z",
                    "t_s": 2.0,
                    "client_id": "sensor-1",
                    "speed_kmh": 50.0,
                    "vibration_strength_db": 18.0,
                },
            ],
        )
    )

    export = await service.build_export_context("run/1 sample")
    try:
        csv_text = export.raw_csv_spool.read().decode("utf-8")
    finally:
        export.raw_csv_spool.close()

    rows = list(csv.DictReader(io.StringIO(csv_text)))

    assert export.safe_name == "run_1_sample"
    assert export.sample_count == 2
    assert len(rows) == 2
    assert json.loads(rows[0]["top_peaks"]) == [{"hz": 30.0, "amp": 0.1}]
    assert rows[0]["vibration_strength_db"] == "21.5"
    assert "custom" not in rows[0]
