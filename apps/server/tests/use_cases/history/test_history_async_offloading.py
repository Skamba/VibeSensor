from __future__ import annotations

import tempfile
import threading
from dataclasses import dataclass, field

import pytest

from vibesensor.domain import RunStatus
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.types.history_records import HistoryRunListEntry, StoredHistoryRun
from vibesensor.use_cases.history.exports import HistoryExportService
from vibesensor.use_cases.history.helpers import async_require_run
from vibesensor.use_cases.history.report_cache import HistoryReportPdfCache
from vibesensor.use_cases.history.runs import HistoryRunService


def _stored_run(run_id: str = "run-1") -> StoredHistoryRun:
    return StoredHistoryRun(
        run_id=run_id,
        status=RunStatus.COMPLETE,
        start_time_utc="2026-01-01T00:00:00Z",
        end_time_utc="2026-01-01T00:01:00Z",
        metadata=run_metadata_from_mapping(
            {
                "run_id": run_id,
                "start_time_utc": "2026-01-01T00:00:00Z",
                "sensor_model": "fixture-sensor",
                "raw_sample_rate_hz": 800,
                "sample_rate_hz": 800,
                "feature_interval_s": 1.0,
                "source": "test",
            }
        ),
        created_at="2026-01-01T00:00:00Z",
        sample_count=3,
    )


@dataclass
class _HistoryDbStub:
    run: StoredHistoryRun | None = None
    runs: list[HistoryRunListEntry] | None = None
    get_run_calls: list[str] = field(default_factory=list)
    get_run_thread_id: int | None = None
    list_runs_calls: int = 0
    list_runs_thread_id: int | None = None

    async def aget_run(self, run_id: str) -> StoredHistoryRun | None:
        self.get_run_calls.append(run_id)
        self.get_run_thread_id = threading.get_ident()
        if self.run is None:
            return None
        return self.run

    async def alist_runs(self, limit: int = 500) -> list[HistoryRunListEntry]:
        self.list_runs_calls += 1
        self.list_runs_thread_id = threading.get_ident()
        return list(self.runs or [])


@pytest.mark.asyncio
async def test_async_require_run_offloads_lookup_to_worker_thread() -> None:
    history_db = _HistoryDbStub(run=_stored_run())
    main_thread_id = threading.main_thread().ident
    assert main_thread_id is not None

    run = await async_require_run(history_db, "run-1")

    assert run.run_id == "run-1"
    assert history_db.get_run_calls == ["run-1"]
    assert history_db.get_run_thread_id is not None
    assert history_db.get_run_thread_id == main_thread_id


@pytest.mark.asyncio
async def test_history_run_service_list_runs_offloads_lookup_to_worker_thread() -> None:
    expected = [
        HistoryRunListEntry(
            run_id="run-1",
            status=RunStatus.COMPLETE,
            start_time_utc="2026-01-01T00:00:00Z",
            end_time_utc="2026-01-01T00:01:00Z",
            created_at="2026-01-01T00:01:00Z",
            sample_count=3,
        )
    ]
    history_db = _HistoryDbStub(runs=expected)
    service = HistoryRunService(history_db)
    main_thread_id = threading.main_thread().ident
    assert main_thread_id is not None

    runs = await service.list_runs()

    assert runs == expected
    assert history_db.list_runs_calls == 1
    assert history_db.list_runs_thread_id is not None
    assert history_db.list_runs_thread_id == main_thread_id


@pytest.mark.asyncio
async def test_export_service_build_export_context_offloads_csv_spooling_to_worker_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_db = _HistoryDbStub(run=_stored_run("run/1"))
    service = HistoryExportService(history_db)
    spool = tempfile.SpooledTemporaryFile[bytes]()
    captured: dict[str, object] = {}
    main_thread_id = threading.main_thread().ident
    assert main_thread_id is not None

    async def _fake_build_raw_csv_spool(
        self: HistoryExportService,
        run_id: str,
    ) -> tuple[tempfile.SpooledTemporaryFile[bytes], int]:
        captured["self"] = self
        captured["run_id"] = run_id
        captured["thread_id"] = threading.get_ident()
        return spool, 7

    monkeypatch.setattr(HistoryExportService, "_build_raw_csv_spool", _fake_build_raw_csv_spool)

    context = await service.build_export_context("run/1")
    try:
        assert context.run_id == "run/1"
        assert context.safe_name == "run_1"
        assert context.sample_count == 7
        assert context.raw_csv_spool is spool
        assert history_db.get_run_calls == ["run/1"]
        assert captured["self"] is service
        assert captured["run_id"] == "run/1"
        assert captured["thread_id"] == main_thread_id
    finally:
        spool.close()


@pytest.mark.asyncio
async def test_report_pdf_cache_get_or_build_offloads_pdf_generation_to_worker_thread() -> None:
    cache = HistoryReportPdfCache()
    captured: dict[str, object] = {}
    main_thread_id = threading.main_thread().ident
    assert main_thread_id is not None

    def _build_pdf() -> bytes:
        captured["thread_id"] = threading.get_ident()
        return b"%PDF-1.7"

    pdf = await cache.get_or_build(("run-1", "en", None, 1, "{}", "none"), _build_pdf)

    assert pdf == b"%PDF-1.7"
    assert captured["thread_id"] != main_thread_id
