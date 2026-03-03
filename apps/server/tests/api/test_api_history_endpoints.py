from __future__ import annotations

import csv
import io
import json
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI, WebSocketDisconnect

from vibesensor.analysis import summarize_run_data
from vibesensor.api import create_router


def _sample(i: int) -> dict[str, Any]:
    return {
        "record_type": "sample",
        "run_id": "run-1",
        "timestamp_utc": f"2026-01-01T00:00:{i:02d}Z",
        "t_s": float(i),
        "client_id": "aabbccddeeff",
        "client_name": "front-left wheel",
        "speed_kmh": 60.0 + i,
        "accel_x_g": 0.02,
        "accel_y_g": 0.02,
        "accel_z_g": 0.02,
        "dominant_freq_hz": 15.0,
        "dominant_axis": "x",
        "top_peaks": [
            {
                "hz": 15.0,
                "amp": 0.1,
                "vibration_strength_db": 12.0,
                "strength_bucket": "l2",
            }
        ],
        "vibration_strength_db": 12.0,
        "strength_bucket": "l2",
    }


@dataclass
class _FakeHistoryDB:
    metadata: dict[str, Any]
    samples: list[dict[str, Any]]
    analysis: dict[str, Any]
    analysis_version: int | None = 1
    analysis_completed_at: str | None = "2026-01-01T00:01:00Z"

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        if run_id != "run-1":
            return None
        result = {
            "run_id": run_id,
            "status": "complete",
            "metadata": self.metadata,
            "analysis": self.analysis,
        }
        if self.analysis_version is not None:
            result["analysis_version"] = self.analysis_version
        if self.analysis_completed_at is not None:
            result["analysis_completed_at"] = self.analysis_completed_at
        result["sample_count"] = len(self.samples)
        return result

    def iter_run_samples(self, run_id: str, batch_size: int = 1000):
        if run_id != "run-1":
            return
        for start in range(0, len(self.samples), batch_size):
            yield self.samples[start : start + batch_size]

    def get_run_samples(self, run_id: str) -> list[dict[str, Any]]:
        if run_id != "run-1":
            return []
        return list(self.samples)

    @contextmanager
    def read_transaction(self):
        yield

    def list_runs(self) -> list[dict[str, Any]]:
        return []

    def get_active_run_id(self) -> str | None:
        return None

    def get_run_status(self, run_id: str) -> str | None:
        if run_id == "run-1":
            return "complete"
        return None

    def delete_run(self, run_id: str) -> bool:
        return False

    def delete_run_if_safe(self, run_id: str) -> tuple[bool, str | None]:
        if run_id != "run-1":
            return False, "not_found"
        return True, None


@dataclass
class _FakeWsHub:
    selected_updates: list[str | None] = field(default_factory=list)

    async def add(self, websocket, selected_client_id: str | None) -> None:
        self.selected_updates.append(selected_client_id)

    async def remove(self, websocket) -> None:
        return None

    async def update_selected_client(self, websocket, client_id: str | None) -> None:
        self.selected_updates.append(client_id)


class _FakeWs:
    def __init__(self, messages: list[str], selected_query: str | None = None) -> None:
        self.query_params = {}
        if selected_query is not None:
            self.query_params["client_id"] = selected_query
        self._messages = list(messages)

    async def accept(self) -> None:
        return None

    async def receive_text(self) -> str:
        if not self._messages:
            raise WebSocketDisconnect()
        return self._messages.pop(0)


class _FakeState:
    def __init__(self, history_db: _FakeHistoryDB, ws_hub: _FakeWsHub) -> None:
        self.history_db = history_db
        self.ws_hub = ws_hub
        self.settings_store = type("S", (), {"language": "en", "set_language": lambda self, v: v})()
        self.live_diagnostics = type("D", (), {"reset": lambda self: None})()
        self.metrics_logger = type(
            "M",
            (),
            {
                "status": lambda self: {},
                "start_logging": lambda self: {},
                "stop_logging": lambda self: {},
            },
        )()
        self.registry = type(
            "R",
            (),
            {
                "snapshot_for_api": lambda self: [],
                "get": lambda self, _cid: None,
                "set_name": lambda self, cid, name: type(
                    "U", (), {"client_id": cid, "name": name}
                )(),
                "remove_client": lambda self, _cid: True,
            },
        )()
        self.control_plane = type(
            "C", (), {"send_identify": lambda self, _id, _dur: (False, None)}
        )()
        self.gps_monitor = type(
            "G",
            (),
            {
                "effective_speed_mps": None,
                "override_speed_mps": None,
                "set_speed_override_kmh": lambda self, _v: None,
            },
        )()
        self.analysis_settings = type(
            "A",
            (),
            {"snapshot": lambda self: {}, "update": lambda self, payload: payload},
        )()
        self.processor = type(
            "P",
            (),
            {
                "debug_spectrum": lambda self, _id: {},
                "raw_samples": lambda self, _id, n_samples=1: {},
            },
        )()


def _make_router_and_state(language: str = "en", sample_count: int = 20):
    metadata = {
        "run_id": "run-1",
        "start_time_utc": "2026-01-01T00:00:00Z",
        "end_time_utc": "2026-01-01T00:00:20Z",
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 800,
        "feature_interval_s": 1.0,
        "language": language,
    }
    samples = [_sample(i) for i in range(sample_count)]
    analysis = summarize_run_data(metadata, samples, lang=language, include_samples=False)
    state = _FakeState(_FakeHistoryDB(metadata, samples, analysis), _FakeWsHub())
    app = FastAPI()
    router = create_router(state)
    app.include_router(router)
    return router, state


def _route_endpoint(router, path: str):
    for route in router.routes:
        if getattr(route, "path", "") == path:
            return route.endpoint
    raise AssertionError(f"Route not found: {path}")


@pytest.mark.asyncio
async def test_history_insights_respects_lang_query() -> None:
    router, _ = _make_router_and_state(language="en")
    endpoint = _route_endpoint(router, "/api/history/{run_id}/insights")
    en = await endpoint("run-1", "en")
    nl = await endpoint("run-1", "nl")
    assert en["lang"] == "en"
    assert nl["lang"] == "en"
    # /insights is persisted post-stop output only: lang query must not
    # trigger on-demand recomputation.
    assert en["most_likely_origin"] == nl["most_likely_origin"]
    # Suitability check keys are now i18n keys (language-neutral)
    check_keys = {
        str(item.get("check_key") or item.get("check")) for item in en.get("run_suitability", [])
    }
    assert "SUITABILITY_CHECK_SPEED_VARIATION" in check_keys


@pytest.mark.asyncio
async def test_report_pdf_respects_lang_query() -> None:
    router, _ = _make_router_and_state(language="en")
    endpoint = _route_endpoint(router, "/api/history/{run_id}/report.pdf")
    en = await endpoint("run-1", "en")
    nl = await endpoint("run-1", "nl")
    assert en.body.startswith(b"%PDF")
    assert nl.body.startswith(b"%PDF")
    assert en.body != nl.body


@pytest.mark.asyncio
async def test_report_pdf_respects_lang_query_with_persisted_report_template_data() -> None:
    """When template data is persisted in NL, PDF rendering keeps persisted language."""
    from dataclasses import asdict
    from io import BytesIO

    from pypdf import PdfReader

    from vibesensor.analysis.report_data_builder import map_summary

    router, state = _make_router_and_state(language="nl")
    state.history_db.analysis["_report_template_data"] = asdict(
        map_summary(state.history_db.analysis)
    )
    endpoint = _route_endpoint(router, "/api/history/{run_id}/report.pdf")

    nl = await endpoint("run-1", "nl")
    en = await endpoint("run-1", "en")

    assert nl.body.startswith(b"%PDF")
    assert en.body.startswith(b"%PDF")

    nl_reader = PdfReader(BytesIO(nl.body))
    en_reader = PdfReader(BytesIO(en.body))
    nl_text = "\n".join(page.extract_text() or "" for page in nl_reader.pages).lower()
    text_from_en_request = "\n".join(page.extract_text() or "" for page in en_reader.pages).lower()
    assert "diagnostisch werkformulier" in nl_text
    assert "diagnostisch werkformulier" in text_from_en_request
    assert "diagnostic worksheet" not in text_from_en_request


@pytest.mark.asyncio
async def test_report_pdf_lang_override_when_template_data_persisted() -> None:
    """Persisted template data should avoid report-time map_summary rebuilds."""
    from dataclasses import asdict
    from io import BytesIO

    from pypdf import PdfReader

    from vibesensor.analysis.report_data_builder import map_summary

    # Create state with NL analysis + embedded _report_template_data
    metadata = {
        "run_id": "run-1",
        "start_time_utc": "2026-01-01T00:00:00Z",
        "end_time_utc": "2026-01-01T00:00:20Z",
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 800,
        "feature_interval_s": 1.0,
        "language": "nl",
    }
    samples = [_sample(i) for i in range(20)]
    analysis = summarize_run_data(metadata, samples, lang="nl", include_samples=False)
    # Embed _report_template_data as the new post-analysis code does
    report_data = map_summary(analysis)
    analysis["_report_template_data"] = asdict(report_data)

    db = _FakeHistoryDB(metadata, samples, analysis)
    state = _FakeState(db, _FakeWsHub())
    app = FastAPI()
    router = create_router(state)
    app.include_router(router)
    endpoint = _route_endpoint(router, "/api/history/{run_id}/report.pdf")

    with patch(
        "vibesensor.analysis.map_summary",
        side_effect=AssertionError("map_summary should not run when template data exists"),
    ):
        nl = await endpoint("run-1", "nl")
        en = await endpoint("run-1", "en")

    assert nl.body.startswith(b"%PDF")
    assert en.body.startswith(b"%PDF")
    nl_text = "\n".join(
        (page.extract_text() or "") for page in PdfReader(BytesIO(nl.body)).pages
    ).lower()
    text_from_en_request = "\n".join(
        (page.extract_text() or "") for page in PdfReader(BytesIO(en.body)).pages
    ).lower()
    assert "diagnostisch werkformulier" in nl_text
    assert "diagnostisch werkformulier" in text_from_en_request
    assert "diagnostic worksheet" not in text_from_en_request


@pytest.mark.asyncio
async def test_report_pdf_reuses_cached_pdf_for_same_run_lang_and_analysis_version() -> None:
    router, _ = _make_router_and_state(language="en")
    endpoint = _route_endpoint(router, "/api/history/{run_id}/report.pdf")
    call_count = 0

    def _fake_pdf(_summary: dict[str, Any]) -> bytes:
        nonlocal call_count
        call_count += 1
        return b"%PDF-cached"

    with patch("vibesensor.routes.history.build_report_pdf", side_effect=_fake_pdf):
        first = await endpoint("run-1", "en")
        second = await endpoint("run-1", "en")

    assert call_count == 1
    assert first.body == second.body == b"%PDF-cached"


@pytest.mark.asyncio
async def test_report_pdf_reuses_cached_pdf_across_lang_when_template_is_persisted() -> None:
    from dataclasses import asdict

    from vibesensor.analysis.report_data_builder import map_summary

    router, state = _make_router_and_state(language="nl")
    state.history_db.analysis["_report_template_data"] = asdict(
        map_summary(state.history_db.analysis)
    )
    endpoint = _route_endpoint(router, "/api/history/{run_id}/report.pdf")
    call_count = 0

    def _fake_pdf(_data) -> bytes:
        nonlocal call_count
        call_count += 1
        return b"%PDF-cached-cross-lang"

    with patch("vibesensor.routes.history.build_report_pdf", side_effect=_fake_pdf):
        first = await endpoint("run-1", "en")
        second = await endpoint("run-1", "nl")

    assert call_count == 1
    assert first.body == second.body == b"%PDF-cached-cross-lang"


@pytest.mark.asyncio
async def test_report_pdf_cache_invalidates_when_analysis_version_changes() -> None:
    metadata = {
        "run_id": "run-1",
        "start_time_utc": "2026-01-01T00:00:00Z",
        "end_time_utc": "2026-01-01T00:00:20Z",
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 800,
        "feature_interval_s": 1.0,
        "language": "en",
    }
    samples = [_sample(i) for i in range(20)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)

    @dataclass
    class _VersionFlipDB(_FakeHistoryDB):
        versions: list[int] = field(default_factory=lambda: [1, 2])
        _idx: int = 0

        def get_run(self, run_id: str) -> dict[str, Any] | None:
            result = super().get_run(run_id)
            if result is None:
                return None
            version = self.versions[min(self._idx, len(self.versions) - 1)]
            self._idx += 1
            result["analysis_version"] = version
            return result

    state = _FakeState(_VersionFlipDB(metadata, samples, analysis), _FakeWsHub())
    router = create_router(state)
    endpoint = _route_endpoint(router, "/api/history/{run_id}/report.pdf")
    call_count = 0

    def _fake_pdf(_summary: dict[str, Any]) -> bytes:
        nonlocal call_count
        call_count += 1
        return b"%PDF-versioned"

    with patch("vibesensor.routes.history.build_report_pdf", side_effect=_fake_pdf):
        await endpoint("run-1", "en")
        await endpoint("run-1", "en")

    assert call_count == 2


async def _read_streaming_body(response) -> bytes:
    """Consume a StreamingResponse's body_iterator into bytes."""
    chunks = []
    async for chunk in response.body_iterator:
        if isinstance(chunk, str):
            chunks.append(chunk.encode("utf-8"))
        else:
            chunks.append(chunk)
    return b"".join(chunks)


@pytest.mark.asyncio
async def test_history_export_streams_zip_with_json_and_csv() -> None:
    router, _ = _make_router_and_state(language="en", sample_count=1000)
    endpoint = _route_endpoint(router, "/api/history/{run_id}/export")
    response = await endpoint("run-1")
    body = await _read_streaming_body(response)
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
    """Nested dicts/lists in CSV cells must be valid JSON, not Python repr."""
    router, _ = _make_router_and_state(language="en", sample_count=3)
    endpoint = _route_endpoint(router, "/api/history/{run_id}/export")
    response = await endpoint("run-1")
    body = await _read_streaming_body(response)
    with zipfile.ZipFile(io.BytesIO(body), "r") as archive:
        rows = list(csv.DictReader(io.StringIO(archive.read("run-1_raw.csv").decode("utf-8"))))
    assert len(rows) == 3
    # The top_peaks column contains a list of dicts.  Before the fix it was
    # Python repr (single quotes); now it must be valid JSON.
    for row in rows:
        raw = row.get("top_peaks", "")
        if raw:
            parsed = json.loads(raw)  # must not raise
            assert isinstance(parsed, list)
            assert all(isinstance(p, dict) for p in parsed)


@pytest.mark.asyncio
async def test_history_export_single_pass_fixed_columns() -> None:
    """Export uses fixed columns and reads samples only once (single pass)."""
    router, state = _make_router_and_state(language="en", sample_count=50)
    db = state.history_db
    original_iter = db.iter_run_samples
    call_count = 0

    def _counting_iter(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return original_iter(*args, **kwargs)

    db.iter_run_samples = _counting_iter  # type: ignore[assignment]
    endpoint = _route_endpoint(router, "/api/history/{run_id}/export")
    response = await endpoint("run-1")
    assert call_count == 1, f"iter_run_samples called {call_count} times, expected 1"
    # Verify CSV content is still correct
    body = await _read_streaming_body(response)
    with zipfile.ZipFile(io.BytesIO(body), "r") as archive:
        rows = list(csv.DictReader(io.StringIO(archive.read("run-1_raw.csv").decode("utf-8"))))
        assert len(rows) == 50


@pytest.mark.asyncio
async def test_history_export_uses_streaming_response() -> None:
    """Export uses StreamingResponse with SpooledTemporaryFile, not BytesIO.getvalue()."""
    from starlette.responses import StreamingResponse as _SR

    router, _ = _make_router_and_state(language="en", sample_count=10)
    endpoint = _route_endpoint(router, "/api/history/{run_id}/export")
    response = await endpoint("run-1")
    assert isinstance(response, _SR), f"Expected StreamingResponse, got {type(response).__name__}"
    assert response.media_type == "application/zip"
    # Content-Length header must be present (set from spool file size).
    content_length = response.headers.get("content-length")
    assert content_length is not None
    assert int(content_length) > 0


@pytest.mark.asyncio
async def test_history_export_csv_has_fixed_columns() -> None:
    """CSV header uses the fixed column schema regardless of sample keys."""
    from vibesensor.api import _EXPORT_CSV_COLUMNS

    router, _ = _make_router_and_state(language="en", sample_count=5)
    endpoint = _route_endpoint(router, "/api/history/{run_id}/export")
    response = await endpoint("run-1")
    body = await _read_streaming_body(response)
    with zipfile.ZipFile(io.BytesIO(body), "r") as archive:
        reader = csv.DictReader(io.StringIO(archive.read("run-1_raw.csv").decode("utf-8")))
        assert tuple(reader.fieldnames or []) == _EXPORT_CSV_COLUMNS


@pytest.mark.asyncio
async def test_history_export_large_run() -> None:
    """Export for a larger run produces valid ZIP with expected row count."""
    router, _ = _make_router_and_state(language="en", sample_count=5000)
    endpoint = _route_endpoint(router, "/api/history/{run_id}/export")
    response = await endpoint("run-1")
    body = await _read_streaming_body(response)
    with zipfile.ZipFile(io.BytesIO(body), "r") as archive:
        names = set(archive.namelist())
        assert "run-1_raw.csv" in names
        assert "run-1.json" in names
        metadata = json.loads(archive.read("run-1.json").decode("utf-8"))
        assert metadata["sample_count"] == 5000
        rows = list(csv.DictReader(io.StringIO(archive.read("run-1_raw.csv").decode("utf-8"))))
        assert len(rows) == 5000


@pytest.mark.asyncio
async def test_ws_selected_client_id_validation() -> None:
    router, state = _make_router_and_state(language="en")
    endpoint = _route_endpoint(router, "/ws")
    ws = _FakeWs(
        messages=[
            json.dumps({"client_id": "not-a-mac"}),
            json.dumps({"client_id": "aa:bb:cc:dd:ee:ff"}),
        ],
        selected_query="ZZZZZZZZZZZZ",
    )
    await endpoint(ws)
    assert None in state.ws_hub.selected_updates
    assert "aabbccddeeff" in state.ws_hub.selected_updates


@pytest.mark.asyncio
async def test_history_insights_lang_query_does_not_recompute() -> None:
    router, _ = _make_router_and_state(language="en", sample_count=30_000)
    endpoint = _route_endpoint(router, "/api/history/{run_id}/insights")
    # Requesting a different language should still return persisted analysis.
    payload = await endpoint("run-1", "nl")
    assert payload["lang"] == "en"
    assert "sampling" not in payload


@pytest.mark.asyncio
async def test_delete_active_run_returns_409() -> None:
    """DELETE /api/history/{run_id} returns 409 when run is active."""

    @dataclass
    class _ActiveDB(_FakeHistoryDB):
        def get_active_run_id(self) -> str | None:
            return "run-1"

        def delete_run_if_safe(self, run_id: str) -> tuple[bool, str | None]:
            if run_id == "run-1":
                return False, "active"
            return False, "not_found"

    metadata = {
        "run_id": "run-1",
        "start_time_utc": "2026-01-01T00:00:00Z",
        "end_time_utc": "2026-01-01T00:00:20Z",
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 800,
        "feature_interval_s": 1.0,
        "language": "en",
    }
    samples = [_sample(i) for i in range(5)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    db = _ActiveDB(metadata, samples, analysis)
    state = _FakeState(db, _FakeWsHub())
    app = FastAPI()
    router = create_router(state)
    app.include_router(router)

    # Find the DELETE endpoint specifically
    delete_endpoint = None
    for route in router.routes:
        if getattr(route, "path", "") == "/api/history/{run_id}":
            if "DELETE" in getattr(route, "methods", set()):
                delete_endpoint = route.endpoint
                break
    assert delete_endpoint is not None

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await delete_endpoint("run-1")
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_delete_analyzing_run_returns_409() -> None:
    @dataclass
    class _AnalyzingDB(_FakeHistoryDB):
        def get_run_status(self, run_id: str) -> str | None:
            if run_id == "run-1":
                return "analyzing"
            return None

        def delete_run_if_safe(self, run_id: str) -> tuple[bool, str | None]:
            if run_id == "run-1":
                return False, "analyzing"
            return False, "not_found"

        def delete_run(self, run_id: str) -> bool:  # pragma: no cover - defensive
            raise AssertionError("delete_run should not be called for analyzing run")

    metadata = {
        "run_id": "run-1",
        "start_time_utc": "2026-01-01T00:00:00Z",
        "end_time_utc": "2026-01-01T00:00:20Z",
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 800,
        "feature_interval_s": 1.0,
        "language": "en",
    }
    samples = [_sample(i) for i in range(5)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    db = _AnalyzingDB(metadata, samples, analysis)
    router = create_router(_FakeState(db, _FakeWsHub()))
    delete_endpoint = None
    for route in router.routes:
        if getattr(route, "path", "") == "/api/history/{run_id}" and "DELETE" in getattr(
            route, "methods", set()
        ):
            delete_endpoint = route.endpoint
            break
    assert delete_endpoint is not None

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await delete_endpoint("run-1")
    assert exc_info.value.status_code == 409
