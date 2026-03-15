from __future__ import annotations

import csv
import io
import json
import zipfile
from dataclasses import dataclass

import pytest
from _history_endpoint_helpers import (
    FakeHistoryDB,
    FakeState,
    FakeWsHub,
    make_metadata,
    make_router_and_state,
    read_streaming_body,
    route_endpoint,
    sample,
)
from fastapi import HTTPException

from vibesensor.use_cases.diagnostics import summarize_run_data
from vibesensor.adapters.http import create_router


@pytest.mark.asyncio
async def test_history_export_streams_zip_with_json_and_csv() -> None:
    router, _ = make_router_and_state(language="en", sample_count=1000)
    endpoint = route_endpoint(router, "/api/history/{run_id}/export")
    response = await endpoint("run-1")
    body = await read_streaming_body(response)
    with zipfile.ZipFile(io.BytesIO(body), "r") as archive:
        names = set(archive.namelist())
        assert names == {"run-1.json", "run-1_raw.csv"}
        metadata = json.loads(archive.read("run-1.json").decode("utf-8"))
        assert metadata["run_id"] == "run-1"
        assert metadata["sample_count"] == 1000
        rows = list(csv.DictReader(io.StringIO(archive.read("run-1_raw.csv").decode("utf-8"))))
        assert len(rows) == 1000


@pytest.mark.asyncio
async def test_history_export_csv_nested_values_are_json() -> None:
    router, _ = make_router_and_state(language="en", sample_count=3)
    endpoint = route_endpoint(router, "/api/history/{run_id}/export")
    response = await endpoint("run-1")
    body = await read_streaming_body(response)
    with zipfile.ZipFile(io.BytesIO(body), "r") as archive:
        rows = list(csv.DictReader(io.StringIO(archive.read("run-1_raw.csv").decode("utf-8"))))
    assert len(rows) == 3
    for row in rows:
        raw = row.get("top_peaks", "")
        if raw:
            parsed = json.loads(raw)
            assert isinstance(parsed, list)
            assert all(isinstance(p, dict) for p in parsed)


@pytest.mark.asyncio
async def test_history_export_single_pass_fixed_columns() -> None:
    router, state = make_router_and_state(language="en", sample_count=50)
    db = state.history_db
    original_iter = db.iter_run_samples
    call_count = 0

    def counting_iter(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return original_iter(*args, **kwargs)

    db.iter_run_samples = counting_iter  # type: ignore[assignment]
    endpoint = route_endpoint(router, "/api/history/{run_id}/export")
    response = await endpoint("run-1")
    assert call_count == 1
    body = await read_streaming_body(response)
    with zipfile.ZipFile(io.BytesIO(body), "r") as archive:
        rows = list(csv.DictReader(io.StringIO(archive.read("run-1_raw.csv").decode("utf-8"))))
        assert len(rows) == 50


@pytest.mark.asyncio
async def test_history_export_uses_streaming_response() -> None:
    from starlette.responses import StreamingResponse

    router, _ = make_router_and_state(language="en", sample_count=10)
    endpoint = route_endpoint(router, "/api/history/{run_id}/export")
    response = await endpoint("run-1")
    assert isinstance(response, StreamingResponse)
    assert response.media_type == "application/zip"
    content_length = response.headers.get("content-length")
    assert content_length is not None
    assert int(content_length) > 0


@pytest.mark.asyncio
async def test_history_export_csv_has_fixed_columns() -> None:
    from vibesensor.use_cases.history.exports import EXPORT_CSV_COLUMNS

    router, _ = make_router_and_state(language="en", sample_count=5)
    endpoint = route_endpoint(router, "/api/history/{run_id}/export")
    response = await endpoint("run-1")
    body = await read_streaming_body(response)
    with zipfile.ZipFile(io.BytesIO(body), "r") as archive:
        reader = csv.DictReader(io.StringIO(archive.read("run-1_raw.csv").decode("utf-8")))
        assert tuple(reader.fieldnames or []) == EXPORT_CSV_COLUMNS


@pytest.mark.asyncio
async def test_history_export_large_run() -> None:
    router, _ = make_router_and_state(language="en", sample_count=1000)
    endpoint = route_endpoint(router, "/api/history/{run_id}/export")
    response = await endpoint("run-1")
    body = await read_streaming_body(response)
    with zipfile.ZipFile(io.BytesIO(body), "r") as archive:
        names = set(archive.namelist())
        assert "run-1_raw.csv" in names
        assert "run-1.json" in names
        metadata = json.loads(archive.read("run-1.json").decode("utf-8"))
        assert metadata["sample_count"] == 1000
        rows = list(csv.DictReader(io.StringIO(archive.read("run-1_raw.csv").decode("utf-8"))))
        assert len(rows) == 1000


@pytest.mark.asyncio
async def test_history_export_strips_internal_analysis_fields_from_json() -> None:
    router, state = make_router_and_state(language="en", sample_count=3)
    state.history_db.analysis["_internal"] = {"keep": "private"}
    endpoint = route_endpoint(router, "/api/history/{run_id}/export")
    response = await endpoint("run-1")
    body = await read_streaming_body(response)
    with zipfile.ZipFile(io.BytesIO(body), "r") as archive:
        metadata = json.loads(archive.read("run-1.json").decode("utf-8"))
    assert "_internal" not in metadata.get("analysis", {})


@pytest.mark.asyncio
async def test_history_export_sanitizes_filename_from_run_id() -> None:
    run_id = "../bad:name*id"
    metadata = make_metadata(run_id=run_id)
    samples = [sample(i) for i in range(2)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)

    @dataclass
    class NamedRunDB(FakeHistoryDB):
        accepted_run_id: str = run_id

        def get_run(self, queried_run_id: str) -> dict[str, object] | None:
            if queried_run_id != self.accepted_run_id:
                return None
            result = super().get_run("run-1")
            assert result is not None
            result["run_id"] = queried_run_id
            return result

        def iter_run_samples(self, queried_run_id: str, batch_size: int = 1000):
            if queried_run_id != self.accepted_run_id:
                return
            yield from super().iter_run_samples("run-1", batch_size=batch_size)

    db = NamedRunDB(metadata, samples, analysis)
    router = create_router(FakeState(db, FakeWsHub()))
    endpoint = route_endpoint(router, "/api/history/{run_id}/export")
    response = await endpoint(run_id)
    body = await read_streaming_body(response)
    with zipfile.ZipFile(io.BytesIO(body), "r") as archive:
        assert set(archive.namelist()) == {"_bad_name_id.json", "_bad_name_id_raw.csv"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "lang"),
    [
        ("/api/history/{run_id}/insights", None),
        ("/api/history/{run_id}/report.pdf", "en"),
        ("/api/history/{run_id}/export", None),
    ],
)
async def test_history_endpoints_return_404_for_unknown_run(path: str, lang: str | None) -> None:
    router, _ = make_router_and_state(language="en")
    endpoint = route_endpoint(router, path)

    with pytest.raises(HTTPException) as exc_info:
        if lang is None:
            await endpoint("missing-run")
        else:
            await endpoint("missing-run", lang)
    assert exc_info.value.status_code == 404
