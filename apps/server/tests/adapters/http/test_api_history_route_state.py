from __future__ import annotations

from dataclasses import dataclass, replace

import pytest
from _history_endpoint_helpers import (
    FakeHistoryDB,
    FakeState,
    FakeWsHub,
    make_app_and_state,
    make_metadata,
    make_status_app,
    sample,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_support.persisted_analysis import make_persisted_analysis

from vibesensor.adapters.analysis_summary import summarize_run_data
from vibesensor.adapters.http import create_router
from vibesensor.domain import CarSnapshot
from vibesensor.shared.types.history_records import StoredHistoryRun
from vibesensor.shared.types.raw_capture import (
    RawCaptureLossStats,
    RawCaptureManifest,
    RawCaptureSensorLossStats,
    RawCaptureSensorManifest,
)


def _app_from_state(state: FakeState) -> FastAPI:
    app = FastAPI()
    app.include_router(create_router(state))
    return app


def test_delete_active_run_returns_409() -> None:
    @dataclass
    class ActiveDB(FakeHistoryDB):
        async def aget_active_run_id(self) -> str | None:
            return "run-1"

        async def adelete_run_if_safe(self, run_id: str) -> tuple[bool, str | None]:
            if run_id == "run-1":
                return False, "active"
            return False, "not_found"

    metadata = make_metadata()
    samples = [sample(i) for i in range(5)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    app = _app_from_state(FakeState(ActiveDB(metadata, samples, analysis), FakeWsHub()))

    with TestClient(app) as client:
        response = client.delete("/api/history/run-1")

    assert response.status_code == 409


def test_delete_analyzing_run_returns_409() -> None:
    @dataclass
    class AnalyzingDB(FakeHistoryDB):
        async def adelete_run_if_safe(self, run_id: str) -> tuple[bool, str | None]:
            if run_id == "run-1":
                return False, "analyzing"
            return False, "not_found"

        async def adelete_run(self, run_id: str) -> bool:
            raise AssertionError("delete_run should not be called for analyzing run")

    metadata = make_metadata()
    samples = [sample(i) for i in range(5)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    app = _app_from_state(FakeState(AnalyzingDB(metadata, samples, analysis), FakeWsHub()))

    with TestClient(app) as client:
        response = client.delete("/api/history/run-1")

    assert response.status_code == 409


@pytest.mark.parametrize(
    ("status", "analysis", "expected_status", "expected_detail"),
    [
        ("analyzing", {"status": "analyzing"}, 202, None),
        ("error", {"status": "error"}, 422, "Analysis failed"),
        ("complete", None, 422, "No analysis available for this run"),
    ],
)
def test_history_insights_status_and_analysis_errors(
    status: str,
    analysis: dict[str, object] | None,
    expected_status: int,
    expected_detail: str | None,
) -> None:
    app = make_status_app(status=status, analysis=analysis, include_error_message=False)

    with TestClient(app) as client:
        response = client.get("/api/history/run-1/insights")

    assert response.status_code == expected_status
    if expected_status == 202:
        body = response.json()
        assert body["status"] == "analyzing"
        assert body["run_id"] == "run-1"
        return
    assert response.json()["detail"] == expected_detail


def test_delete_run_returns_404_for_not_found_reason() -> None:
    app, _ = make_app_and_state(language="en")

    with TestClient(app) as client:
        response = client.delete("/api/history/missing-run")

    assert response.status_code == 404


def test_delete_run_returns_generic_409_for_unknown_reason() -> None:
    @dataclass
    class LockedDB(FakeHistoryDB):
        async def adelete_run_if_safe(self, run_id: str) -> tuple[bool, str | None]:
            if run_id == "run-1":
                return False, "locked"
            return False, "not_found"

    metadata = make_metadata()
    samples = [sample(i) for i in range(5)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    app = _app_from_state(FakeState(LockedDB(metadata, samples, analysis), FakeWsHub()))

    with TestClient(app) as client:
        response = client.delete("/api/history/run-1")

    assert response.status_code == 409
    assert response.json()["detail"] == "Cannot delete run at this time"


def test_history_insights_does_not_mutate_db_analysis() -> None:
    app, state = make_app_and_state(language="en")
    original_analysis = state.history_db.analysis
    original_keys = set(original_analysis.keys())

    with TestClient(app) as client:
        response = client.get("/api/history/run-1/insights")

    assert response.status_code == 200
    assert set(state.history_db.analysis.keys()) == original_keys


def test_history_insights_complete_response_includes_status_and_run_id() -> None:
    metadata = make_metadata()
    samples = [sample(i) for i in range(5)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    analysis.pop("status", None)
    analysis.pop("run_id", None)
    app, _ = make_app_and_state(
        language="en", metadata=metadata, samples=samples, analysis=analysis
    )

    with TestClient(app) as client:
        response = client.get("/api/history/run-1/insights")

    payload = response.json()
    assert payload["status"] == "complete"
    assert payload["run_id"] == "run-1"


def test_history_endpoints_preserve_analysis_case_id() -> None:
    metadata = make_metadata()
    samples = [sample(i) for i in range(5)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    analysis["case_id"] = "case-123"
    app, _ = make_app_and_state(
        language="en", metadata=metadata, samples=samples, analysis=analysis
    )

    with TestClient(app) as client:
        history_payload = client.get("/api/history/run-1").json()
        insights_payload = client.get("/api/history/run-1/insights").json()

    assert history_payload["analysis"]["case_id"] == "case-123"
    assert insights_payload["case_id"] == "case-123"


def test_history_run_includes_sample_count() -> None:
    metadata = make_metadata()
    samples = [sample(i) for i in range(3)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    app, _ = make_app_and_state(
        language="en", metadata=metadata, samples=samples, analysis=analysis
    )

    with TestClient(app) as client:
        response = client.get("/api/history/run-1")

    assert response.json()["sample_count"] == 3


def test_history_run_detail_includes_raw_capture_quality() -> None:
    @dataclass
    class RawManifestDB(FakeHistoryDB):
        async def aget_run(self, run_id: str) -> StoredHistoryRun | None:
            run = await super().aget_run(run_id)
            if run is None:
                return None
            losses = RawCaptureLossStats(queue_overflow_chunk_count=120)
            sensor = RawCaptureSensorManifest(
                client_id="sensor-a",
                sample_rate_hz=800,
                data_file="sensor-a.raw.i16le",
                index_file="sensor-a.index.jsonl",
                sample_count=64_000,
                chunk_count=1000,
                bytes_written=384_000,
            )
            return replace(
                run,
                raw_capture_manifest=RawCaptureManifest(
                    run_id=run_id,
                    relative_dir=f"raw-runs/{run_id}",
                    sensors=(sensor,),
                    total_samples=64_000,
                    total_bytes=384_000,
                    created_at="2026-01-01T00:00:00Z",
                    sensor_losses=(RawCaptureSensorLossStats(client_id="sensor-a", losses=losses),),
                    losses=losses,
                ),
            )

    metadata = make_metadata()
    samples = [sample(i) for i in range(3)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    app = _app_from_state(FakeState(RawManifestDB(metadata, samples, analysis), FakeWsHub()))

    with TestClient(app) as client:
        response = client.get("/api/history/run-1")

    quality = response.json()["raw_capture_quality"]
    assert quality["severity"] == "fatal"
    assert quality["reason"] == "raw_capture_queue_overflow_fatal"
    assert quality["gate_whole_run"] is True
    assert quality["queue_overflow_chunk_count"] == 120


def test_history_list_includes_recorded_car_name() -> None:
    metadata = make_metadata(active_car_snapshot={"name": "Track Car"})
    samples = [sample(i) for i in range(3)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    app, _ = make_app_and_state(
        language="en", metadata=metadata, samples=samples, analysis=analysis
    )

    with TestClient(app) as client:
        response = client.get("/api/history")

    assert response.json()["runs"][0]["car_name"] == "Track Car"


def test_history_endpoints_include_degraded_raw_capture_finalize_state() -> None:
    metadata = make_metadata(
        raw_capture_finalize={
            "status": "timeout",
            "queue_depth": 4,
            "error_summary": "raw capture finalize timed out",
        }
    )
    samples = [sample(i) for i in range(3)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    app, _ = make_app_and_state(
        language="en", metadata=metadata, samples=samples, analysis=analysis
    )

    with TestClient(app) as client:
        list_payload = client.get("/api/history").json()
        run_payload = client.get("/api/history/run-1").json()

    assert list_payload["runs"][0]["lifecycle"] == {
        "stage": "post_analysis_ready",
        "raw_capture": "degraded",
        "whole_run_artifacts": "not_recorded",
        "post_analysis": "ready",
        "report": "ready",
    }
    assert list_payload["runs"][0]["artifact_availability"]["raw_capture"] == "degraded"
    assert list_payload["runs"][0]["raw_capture_finalize"] == {
        "status": "timeout",
        "queue_depth": 4,
        "error_summary": "raw capture finalize timed out",
    }
    assert run_payload["lifecycle"] == {
        "stage": "post_analysis_ready",
        "raw_capture": "degraded",
        "whole_run_artifacts": "not_recorded",
        "post_analysis": "ready",
        "report": "ready",
    }
    assert run_payload["artifact_availability"]["raw_capture"] == "degraded"
    assert run_payload["raw_capture_finalize"] == {
        "status": "timeout",
        "queue_depth": 4,
        "error_summary": "raw capture finalize timed out",
    }


def test_history_run_detail_exposes_finalization_stage_metadata() -> None:
    metadata = make_metadata(
        finalization_stages=[
            {
                "stage_name": "FinalizeRawCaptureStage",
                "status": "degraded",
                "duration_ms": 7,
                "warnings": ["raw capture finalize timed out"],
                "diagnostic_context": {
                    "raw_capture_status": "timeout",
                    "queue_depth": 4,
                },
            },
            {
                "stage_name": "ResolvePostAnalysisCandidateStage",
                "status": "skipped",
                "duration_ms": 0,
                "diagnostic_context": {"reason": "raw_capture_finalize_unsettled"},
            },
        ]
    )
    samples = [sample(i) for i in range(3)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    app, _ = make_app_and_state(
        language="en", metadata=metadata, samples=samples, analysis=analysis
    )

    with TestClient(app) as client:
        run_payload = client.get("/api/history/run-1").json()

    assert "finalization_stages" not in run_payload["metadata"]
    assert run_payload["finalization_stages"] == [
        {
            "stage_name": "FinalizeRawCaptureStage",
            "status": "degraded",
            "duration_ms": 7,
            "warnings": ["raw capture finalize timed out"],
            "diagnostic_context": {
                "raw_capture_status": "timeout",
                "queue_depth": 4,
            },
        },
        {
            "stage_name": "ResolvePostAnalysisCandidateStage",
            "status": "skipped",
            "duration_ms": 0,
            "diagnostic_context": {"reason": "raw_capture_finalize_unsettled"},
        },
    ]


def test_history_list_uses_nested_active_car_snapshot_name() -> None:
    metadata = make_metadata(
        active_car_snapshot={
            "id": "car-1",
            "name": "Nested Track Car",
            "type": "coupe",
        }
    )
    samples = [sample(i) for i in range(3)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    app, _ = make_app_and_state(
        language="en", metadata=metadata, samples=samples, analysis=analysis
    )

    with TestClient(app) as client:
        payload = client.get("/api/history").json()

    assert payload["runs"][0]["car_name"] == "Nested Track Car"


def test_history_run_projects_canonical_nested_run_context() -> None:
    metadata = make_metadata(
        analysis_settings_snapshot={
            "tire_width_mm": 275.0,
            "tire_aspect_pct": 35.0,
            "rim_in": 20.0,
            "final_drive_ratio": 3.15,
            "current_gear_ratio": 0.91,
        },
        active_car_snapshot={
            "id": "car-1",
            "name": "Nested Track Car",
            "type": "hatchback",
        },
    )
    samples = [sample(i) for i in range(3)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    app, _ = make_app_and_state(
        language="en", metadata=metadata, samples=samples, analysis=analysis
    )

    with TestClient(app) as client:
        payload = client.get("/api/history/run-1").json()

    projected_metadata = payload["metadata"]
    assert projected_metadata["active_car_snapshot"]["name"] == "Nested Track Car"
    assert projected_metadata["active_car_snapshot"]["type"] == "hatchback"
    assert projected_metadata["active_car_snapshot"]["id"] == "car-1"
    assert "aspects" not in projected_metadata["active_car_snapshot"]
    assert float(
        projected_metadata["analysis_settings_snapshot"]["tire_width_mm"]
    ) == pytest.approx(275.0)
    assert float(
        projected_metadata["analysis_settings_snapshot"]["tire_aspect_pct"]
    ) == pytest.approx(35.0)
    assert float(projected_metadata["analysis_settings_snapshot"]["rim_in"]) == pytest.approx(20.0)
    assert "reference_context" not in projected_metadata
    assert "tire_circumference_m" not in projected_metadata


def test_history_run_includes_error_message_for_error_status() -> None:
    app = make_status_app(
        status="error",
        analysis={"status": "error"},
        include_error_message=True,
    )

    with TestClient(app) as client:
        response = client.get("/api/history/run-1")

    assert response.json()["error_message"] == "Analysis failed"


def test_history_insights_localizes_and_adds_run_context_warnings() -> None:
    metadata = make_metadata(
        analysis_settings_snapshot={
            "tire_width_mm": 245.0,
            "tire_aspect_pct": 35.0,
            "rim_in": 19.0,
            "final_drive_ratio": 3.23,
            "current_gear_ratio": 0.82,
        },
        active_car_snapshot={
            "id": "car-a",
            "name": "Track Car",
            "type": "coupe",
        },
        car_name="Track Car",
        tire_width_mm=245.0,
        tire_aspect_pct=35.0,
        rim_in=19.0,
        final_drive_ratio=3.23,
        current_gear_ratio=0.82,
        incomplete_for_order_analysis=True,
    )
    samples = [sample(i) for i in range(5)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)

    app, state = make_app_and_state(
        language="en",
        metadata=metadata,
        analysis=analysis,
        samples=samples,
    )
    state.settings_store.active_car_snapshot = lambda: CarSnapshot(
        car_id="car-b",
        name="Daily Car",
        car_type="wagon",
        aspects={
            "tire_width_mm": 225.0,
            "tire_aspect_pct": 45.0,
            "rim_in": 18.0,
            "final_drive_ratio": 2.91,
            "current_gear_ratio": 0.72,
        },
    )

    with TestClient(app) as client:
        payload = client.get("/api/history/run-1/insights", params={"lang": "nl"}).json()

    warnings = payload.get("warnings")
    assert isinstance(warnings, list)
    assert len(warnings) == 2
    titles = {str(item.get("title")) for item in warnings if isinstance(item, dict)}
    assert "De referentiecontext voor ordeanalyse was onvolledig voor deze run" in titles
    assert "Voertuigprofielinstellingen zijn na deze run gewijzigd" in titles


def test_history_run_strips_internal_analysis_fields() -> None:
    @dataclass
    class InternalFieldDB(FakeHistoryDB):
        async def aget_run(self, run_id: str) -> StoredHistoryRun | None:
            if run_id != "run-1":
                return None
            result = await super().aget_run(run_id)
            assert result is not None
            analysis = dict(result.analysis.to_json_object() if result.analysis is not None else {})
            analysis["_internal_secret"] = "should-not-appear"
            analysis["_report_template_data"] = {"lang": "en"}
            return replace(result, analysis=make_persisted_analysis(analysis))

    metadata = make_metadata()
    samples = [sample(0)]
    app = _app_from_state(FakeState(InternalFieldDB(metadata, samples, {}), FakeWsHub()))

    with TestClient(app) as client:
        response = client.get("/api/history/run-1")

    result = response.json()
    assert {"run_id", "status", "sample_count", "metadata", "analysis"}.issubset(result.keys())
    assert result.get("error_message") is None
    analysis = result.get("analysis", {})
    assert "_internal_secret" not in analysis
    assert "_report_template_data" not in analysis


def test_history_run_preserves_missing_optional_analysis_fields() -> None:
    metadata = make_metadata()
    samples = [sample(0)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    analysis.pop("plots", None)
    analysis.pop("analysis_metadata", None)
    db = FakeHistoryDB(metadata, samples, analysis)
    app = _app_from_state(FakeState(db, FakeWsHub()))
    route = next(
        route
        for route in app.router.routes
        if getattr(route, "path", "") == "/api/history/{run_id}"
        and "GET" in getattr(route, "methods", set())
    )

    with TestClient(app) as client:
        response = client.get("/api/history/run-1")

    payload = response.json()["analysis"]
    assert getattr(route, "response_model_exclude_unset", False) is True
    assert "findings" in payload
    assert "samples" not in payload
    assert "plots" not in payload
    assert "analysis_metadata" not in payload
