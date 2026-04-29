from __future__ import annotations

import csv
import io
import json
import zipfile

import pytest
from _history_endpoint_helpers import make_app_and_state
from fastapi.testclient import TestClient


def test_history_export_streams_zip_with_json_and_csv() -> None:
    app, _ = make_app_and_state(language="en", sample_count=3)
    with TestClient(app) as client:
        response = client.get("/api/history/run-1/export")

    body = response.content
    with zipfile.ZipFile(io.BytesIO(body), "r") as archive:
        names = set(archive.namelist())
        assert names == {"run-1.json", "run-1_raw.csv"}
        metadata = json.loads(archive.read("run-1.json").decode("utf-8"))
        assert metadata["run_id"] == "run-1"
        assert metadata["sample_count"] == 3
        rows = list(csv.DictReader(io.StringIO(archive.read("run-1_raw.csv").decode("utf-8"))))
        assert len(rows) == 3


def test_history_export_csv_nested_values_are_json() -> None:
    app, _ = make_app_and_state(language="en", sample_count=3)
    with TestClient(app) as client:
        response = client.get("/api/history/run-1/export")

    body = response.content
    with zipfile.ZipFile(io.BytesIO(body), "r") as archive:
        rows = list(csv.DictReader(io.StringIO(archive.read("run-1_raw.csv").decode("utf-8"))))
    assert len(rows) == 3
    for row in rows:
        raw = row.get("top_peaks", "")
        if raw:
            parsed = json.loads(raw)
            assert isinstance(parsed, list)
            assert all(isinstance(p, dict) for p in parsed)


def test_history_export_single_pass_fixed_columns() -> None:
    app, state = make_app_and_state(language="en", sample_count=50)
    db = state.history_db
    original_iter = db.aiter_run_samples
    call_count = 0

    def counting_iter(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return original_iter(*args, **kwargs)

    db.aiter_run_samples = counting_iter
    with TestClient(app) as client:
        response = client.get("/api/history/run-1/export")

    assert call_count == 1
    body = response.content
    with zipfile.ZipFile(io.BytesIO(body), "r") as archive:
        rows = list(csv.DictReader(io.StringIO(archive.read("run-1_raw.csv").decode("utf-8"))))
        assert len(rows) == 50


def test_history_export_uses_streaming_response() -> None:
    app, _ = make_app_and_state(language="en", sample_count=10)
    with TestClient(app) as client:
        response = client.get("/api/history/run-1/export")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    content_length = response.headers.get("content-length")
    assert content_length is not None
    assert int(content_length) > 0


def test_history_export_csv_has_fixed_columns() -> None:
    from vibesensor.use_cases.history.exports import EXPORT_CSV_COLUMNS

    app, _ = make_app_and_state(language="en", sample_count=5)
    with TestClient(app) as client:
        response = client.get("/api/history/run-1/export")

    body = response.content
    with zipfile.ZipFile(io.BytesIO(body), "r") as archive:
        reader = csv.DictReader(io.StringIO(archive.read("run-1_raw.csv").decode("utf-8")))
        assert tuple(reader.fieldnames or []) == EXPORT_CSV_COLUMNS


def test_history_export_large_run() -> None:
    app, _ = make_app_and_state(language="en", sample_count=1000)
    with TestClient(app) as client:
        response = client.get("/api/history/run-1/export")

    body = response.content
    with zipfile.ZipFile(io.BytesIO(body), "r") as archive:
        names = set(archive.namelist())
        assert "run-1_raw.csv" in names
        assert "run-1.json" in names
        metadata = json.loads(archive.read("run-1.json").decode("utf-8"))
        assert metadata["sample_count"] == 1000
        rows = list(csv.DictReader(io.StringIO(archive.read("run-1_raw.csv").decode("utf-8"))))
        assert len(rows) == 1000


def test_history_export_strips_internal_analysis_fields_from_json() -> None:
    app, state = make_app_and_state(language="en", sample_count=3)
    state.history_db.analysis["_internal"] = {"keep": "private"}
    with TestClient(app) as client:
        response = client.get("/api/history/run-1/export")

    body = response.content
    with zipfile.ZipFile(io.BytesIO(body), "r") as archive:
        metadata = json.loads(archive.read("run-1.json").decode("utf-8"))
    assert "_internal" not in metadata.get("analysis", {})


@pytest.mark.parametrize(
    ("path", "lang"),
    [
        ("/api/history/run-1/insights", None),
        ("/api/history/run-1/report.pdf", "en"),
        ("/api/history/run-1/export", None),
    ],
)
def test_history_endpoints_return_404_for_unknown_run(path: str, lang: str | None) -> None:
    app, _ = make_app_and_state(language="en")
    request_path = path.replace("run-1", "missing-run")
    params = None if lang is None else {"lang": lang}
    with TestClient(app) as client:
        response = client.get(request_path, params=params)

    assert response.status_code == 404
