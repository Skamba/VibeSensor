from __future__ import annotations

import csv
import io
import json
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest
from test_support.analysis import run_analysis
from test_support.persisted_analysis import make_persisted_analysis
from test_support.report_helpers import minimal_summary, report_sample

from vibesensor.common.exceptions import AnalysisNotReadyError
from vibesensor.domain.car import CarSnapshot
from vibesensor.domain.run_status import RunStatus
from vibesensor.history.exports import HistoryExportService
from vibesensor.history.records import HistoryRunListEntry, StoredHistoryRun
from vibesensor.history.runs import HistoryRunService, raise_delete_run_error
from vibesensor.recording.run_metadata import run_metadata_from_mapping
from vibesensor.recording.sensor_frame import SensorFrame
from vibesensor.recording.sensor_frame_mapping import sensor_frame_from_mapping
from vibesensor.report.cache import HistoryReportPdfCache
from vibesensor.report.service import HistoryReportService
from vibesensor.report.view_model import ReportView
from vibesensor.summary.contracts import AnalysisSummary
from vibesensor.summary.run_context_warning import (
    WARNING_CODE_CAR_SETTINGS_CHANGED,
    WARNING_CODE_REFERENCE_CONTEXT_INCOMPLETE,
)
from vibesensor.web.history_services import (
    ProjectedHistoryExportService,
    ProjectedHistoryRunService,
)

_WINDOWS_CSV = "run-1_analysis_windows.csv"


@dataclass
class _HistoryDbStub:
    run: dict[str, Any] | None = None
    delete_result: tuple[bool, str | None] = (True, None)
    samples: list[dict[str, Any]] | None = None
    runs: list[HistoryRunListEntry] | None = None
    list_runs_error: Exception | None = None

    # Export spools land next to the database; these stubs keep no raw capture.
    db_path: Path = Path(tempfile.gettempdir()) / "history.db"

    def raw_capture_files(self, run_id: str) -> tuple[Path, ...]:
        return ()

    def get_run(self, run_id: str) -> StoredHistoryRun | None:
        if self.run is None:
            return None
        return _stored_run(dict(self.run))

    def list_runs(self) -> list[HistoryRunListEntry]:
        if self.list_runs_error is not None:
            raise self.list_runs_error
        return list(self.runs or [])

    def delete_run_if_safe(self, run_id: str) -> tuple[bool, str | None]:
        return self.delete_result

    def iter_run_samples(self, run_id: str, batch_size: int = 1000, *, stride: int = 1):
        rows = [
            row if isinstance(row, SensorFrame) else sensor_frame_from_mapping(row)
            for row in (self.samples or [])
        ]
        for start in range(0, len(rows), batch_size):
            yield rows[start : start + batch_size]


@dataclass
class _SettingsStoreStub:
    active_car: CarSnapshot | None

    def active_car_snapshot(self) -> CarSnapshot | None:
        return self.active_car


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


def _projectable_analysis(**overrides: object) -> dict[str, object]:
    summary = run_analysis(
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
    )
    summary.update(overrides)
    return cast(dict[str, object], summary)


def _projected_run_service(
    run: dict[str, Any],
    *,
    active_car: CarSnapshot | None = None,
) -> ProjectedHistoryRunService:
    service = HistoryRunService(
        _HistoryDbStub(run=run),
    )
    if active_car is None:
        return ProjectedHistoryRunService(service)
    return ProjectedHistoryRunService(
        service,
        current_car_reader=_SettingsStoreStub(active_car=active_car),
    )


def test_raise_delete_run_error_maps_unknown_reason_to_domain_error() -> None:
    with pytest.raises(AnalysisNotReadyError, match="Cannot delete run at this time"):
        raise_delete_run_error("locked")


@pytest.mark.asyncio
async def test_delete_service_uses_delete_reason_mapping() -> None:
    service = HistoryRunService(
        _HistoryDbStub(delete_result=(False, "active")),
    )

    with pytest.raises(AnalysisNotReadyError, match="Cannot delete the active run"):
        await service.delete_run("run-1")


@pytest.mark.asyncio
async def test_report_service_keeps_persisted_summary_immutable() -> None:
    persisted_analysis = cast(
        AnalysisSummary,
        minimal_summary(
            lang="en",
            warnings=[
                {
                    "code": WARNING_CODE_REFERENCE_CONTEXT_INCOMPLETE,
                    "severity": "warn",
                    "applies_to": "order_analysis",
                    "title": "Persisted warning",
                }
            ],
            metadata={
                "run_id": "run-1",
                "active_car_snapshot": {"id": "car-a", "name": "Track Car", "type": "coupe"},
            },
        ),
    )
    history_db = _HistoryDbStub(
        run={
            "run_id": "run-1",
            "status": "complete",
            "metadata": {"language": "en"},
            "analysis": persisted_analysis,
        }
    )
    views: list[ReportView] = []

    def renderer(view: ReportView) -> bytes:
        views.append(view)
        return b"%PDF"

    pdf = await HistoryReportService(history_db, pdf_renderer=renderer).build_pdf("run-1", "en")

    assert pdf.filename == "run-1_report.pdf"
    stored = history_db.get_run("run-1")
    assert stored is not None and stored.analysis is not None
    assert [warning["code"] for warning in stored.analysis["warnings"]] == [
        WARNING_CODE_REFERENCE_CONTEXT_INCOMPLETE,
    ]
    assert views[0].quality.warnings
    assert not views[0].quality.all_passed


@pytest.mark.asyncio
async def test_projected_run_service_adds_current_context_overlay_explicitly() -> None:
    metadata = {
        "analysis_settings_snapshot": {
            "tire_width_mm": 245.0,
            "tire_aspect_pct": 40.0,
            "rim_in": 19.0,
        },
        "active_car_snapshot": {
            "id": "car-a",
            "name": "Track Car",
            "type": "coupe",
        },
        "incomplete_for_order_analysis": True,
    }
    persisted_analysis = cast(
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
            metadata=metadata,
            lang="en",
        ),
    )
    service = _projected_run_service(
        {
            "run_id": "run-1",
            "status": "complete",
            "metadata": {"language": "en"},
            "analysis": persisted_analysis,
        },
        active_car=CarSnapshot(
            car_id="car-b",
            name="Daily Car",
            car_type="wagon",
            aspects={"tire_width_mm": 225.0},
        ),
    )

    payload = await service.get_insights("run-1", requested_lang="en")

    assert payload is not None
    assert [
        warning["code"]
        for warning in payload["warnings"]
        if warning["applies_to"] != "run_suitability"
    ] == [
        WARNING_CODE_REFERENCE_CONTEXT_INCOMPLETE,
        WARNING_CODE_CAR_SETTINGS_CHANGED,
    ]


@pytest.mark.asyncio
async def test_projected_run_service_projects_persisted_summary_through_domain() -> None:
    service = _projected_run_service(
        {
            "run_id": "run-1",
            "status": "complete",
            "analysis": _projectable_analysis(
                lang="en",
                findings=[
                    {
                        "finding_id": "F001",
                        "suspected_source": "wheel/tire",
                        "strongest_location": "front-left",
                        "strongest_speed_band": "50-80 km/h",
                        "confidence": 0.71,
                        "evidence_metrics": {"vibration_strength_db": 21.0},
                    },
                ],
                top_causes=[],
                run_suitability=[],
                most_likely_origin={},
                _internal={"secret": True},
            ),
        }
    )

    run = await service.get_run("run-1")

    analysis = run.analysis
    assert analysis is not None
    assert analysis["top_causes"][0]["finding_id"] == "F001"
    assert analysis["most_likely_origin"]["suspected_source"] == "wheel/tire"
    assert "_internal" not in analysis


@pytest.mark.asyncio
async def test_projected_run_service_drops_persisted_origin_without_primary_finding() -> None:
    service = _projected_run_service(
        {
            "run_id": "run-1",
            "status": "complete",
            "analysis": _projectable_analysis(
                lang="en",
                findings=[],
                top_causes=[],
                run_suitability=[],
                most_likely_origin={
                    "location": "rear left",
                    "suspected_source": "wheel/tire",
                    "weak_spatial_separation": True,
                },
                _internal={"secret": True},
            ),
        }
    )

    run = await service.get_run("run-1")

    analysis = run.analysis
    assert analysis is not None
    assert analysis["most_likely_origin"] == {}
    assert "_internal" not in analysis


@pytest.mark.asyncio
async def test_export_archive_builder_creates_csv_and_json_entries() -> None:
    service = ProjectedHistoryExportService(
        HistoryExportService(
            _HistoryDbStub(
                run={
                    "run_id": "run-1",
                    "analysis": {"score": 1, "_internal": "secret"},
                },
                samples=[
                    {"run_id": "run-1", "t_s": 1.0, "location": "front_left_wheel", "custom": "x"}
                ],
            ),
        )
    )

    export = await service.build_export("run-1")
    body = b"".join(export.iter_bytes())

    with zipfile.ZipFile(io.BytesIO(body), "r") as archive:
        assert set(archive.namelist()) == {"run-1.json", _WINDOWS_CSV}
        exported = json.loads(archive.read("run-1.json").decode("utf-8"))
        rows = list(csv.DictReader(io.StringIO(archive.read(_WINDOWS_CSV).decode("utf-8"))))

    assert exported["analysis"] == {"score": 1}
    assert rows[0]["t_s"] == "1.0"
    assert rows[0]["location"] == "front_left_wheel"
    assert "extras" not in rows[0]
    assert "custom" not in rows[0]


@pytest.mark.asyncio
async def test_report_pdf_cache_builds_once_per_key() -> None:
    cache = HistoryReportPdfCache()
    calls = 0

    def _build() -> bytes:
        nonlocal calls
        calls += 1
        return b"%PDF-cache"

    cache_key = ("run-1", "nl", None, None)
    first = await cache.get_or_build(cache_key, _build)
    second = await cache.get_or_build(cache_key, _build)

    assert calls == 1
    assert first == second == b"%PDF-cache"
