from __future__ import annotations

import csv
import io
import json
import zipfile
from dataclasses import dataclass
from typing import Any

import pytest

from vibesensor.exceptions import AnalysisNotReadyError
from vibesensor.history_services.exports import HistoryExportArchiveBuilder, build_run_details_json
from vibesensor.history_services.reports import HistoryReportPdfCache, HistoryReportService
from vibesensor.history_services.runs import HistoryRunDeleteService, raise_delete_run_error


@dataclass
class _HistoryDbStub:
    run: dict[str, Any] | None = None
    delete_result: tuple[bool, str | None] = (True, None)
    samples: list[dict[str, Any]] | None = None

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        if self.run is None:
            return None
        return dict(self.run)

    def delete_run_if_safe(self, run_id: str) -> tuple[bool, str | None]:
        return self.delete_result

    def iter_run_samples(self, run_id: str, batch_size: int = 1000):
        rows = list(self.samples or [])
        for start in range(0, len(rows), batch_size):
            yield rows[start : start + batch_size]


def test_raise_delete_run_error_maps_unknown_reason_to_domain_error() -> None:
    with pytest.raises(AnalysisNotReadyError, match="Cannot delete run at this time"):
        raise_delete_run_error("locked")


@pytest.mark.asyncio
async def test_delete_service_uses_delete_reason_mapping() -> None:
    service = HistoryRunDeleteService(_HistoryDbStub(delete_result=(False, "active")))

    with pytest.raises(AnalysisNotReadyError, match="Cannot delete the active run"):
        await service.delete_run("run-1")


@pytest.mark.asyncio
async def test_report_service_load_report_request_uses_persisted_language() -> None:
    service = HistoryReportService(
        _HistoryDbStub(
            run={
                "run_id": "run-1",
                "status": "complete",
                "metadata": {"language": "en"},
                "analysis_version": 3,
                "sample_count": 12,
                "analysis": {"lang": "nl", "findings": [], "title": "X"},
            },
        ),
    )

    request = await service.load_report_request("run-1", "en")

    assert request.filename == "run-1_report.pdf"
    assert request.cache_key[1] == "nl"
    assert request.analysis_summary["lang"] == "nl"


@pytest.mark.asyncio
async def test_report_pdf_cache_builds_once_per_key() -> None:
    cache = HistoryReportPdfCache()
    calls = 0

    def _build() -> bytes:
        nonlocal calls
        calls += 1
        return b"%PDF-cache"

    first = await cache.get_or_build(("run-1", "nl"), _build, run_id="run-1")
    second = await cache.get_or_build(("run-1", "nl"), _build, run_id="run-1")

    assert calls == 1
    assert first == second == b"%PDF-cache"


def test_build_run_details_json_strips_internal_analysis_fields() -> None:
    payload = json.loads(
        build_run_details_json(
            {
                "run_id": "run-1",
                "analysis": {"visible": 1, "_internal": {"secret": True}},
            },
            sample_count=5,
            run_id="run-1",
        ),
    )

    assert payload["sample_count"] == 5
    assert payload["analysis"] == {"visible": 1}


def test_build_run_details_json_sanitizes_non_finite_floats() -> None:
    """Non-finite floats in analysis are replaced with null, producing valid JSON."""
    result = build_run_details_json(
        {
            "run_id": "run-nan",
            "analysis": {
                "score": float("nan"),
                "maximum": float("inf"),
                "minimum": float("-inf"),
                "valid": 42.5,
            },
        },
        sample_count=3,
        run_id="run-nan",
    )

    # Must be parseable by json.loads (no NaN/Infinity)
    payload = json.loads(result)
    assert payload["analysis"]["score"] is None
    assert payload["analysis"]["maximum"] is None
    assert payload["analysis"]["minimum"] is None
    assert payload["analysis"]["valid"] == 42.5


def test_export_archive_builder_creates_csv_and_json_entries() -> None:
    builder = HistoryExportArchiveBuilder(
        _HistoryDbStub(
            samples=[{"run_id": "run-1", "t_s": 1.0, "custom": "x"}],
        ),
    )

    spool = builder.build_zip_file(
        {
            "run_id": "run-1",
            "analysis": {"score": 1, "_internal": "secret"},
        },
        "run-1",
    )
    body = spool.read()
    spool.close()

    with zipfile.ZipFile(io.BytesIO(body), "r") as archive:
        assert set(archive.namelist()) == {"run-1.json", "run-1_raw.csv"}
        exported = json.loads(archive.read("run-1.json").decode("utf-8"))
        rows = list(csv.DictReader(io.StringIO(archive.read("run-1_raw.csv").decode("utf-8"))))

    assert exported["analysis"] == {"score": 1}
    assert json.loads(rows[0]["extras"]) == {"custom": "x"}
