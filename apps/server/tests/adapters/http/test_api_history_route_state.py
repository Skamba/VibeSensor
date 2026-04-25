from __future__ import annotations

import json
from dataclasses import dataclass, replace

import pytest
from _history_endpoint_helpers import (
    FakeHistoryDB,
    FakeState,
    FakeWsHub,
    make_metadata,
    make_router_and_state,
    make_status_router,
    response_payload,
    route_endpoint,
    route_endpoint_with_method,
    sample,
)
from fastapi import HTTPException
from test_support.persisted_analysis import make_persisted_analysis

from vibesensor.adapters.analysis_summary import summarize_run_data
from vibesensor.adapters.http import create_router
from vibesensor.domain import CarSnapshot
from vibesensor.shared.types.history_records import StoredHistoryRun


@pytest.mark.asyncio
async def test_delete_active_run_returns_409() -> None:
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
    db = ActiveDB(metadata, samples, analysis)
    state = FakeState(db, FakeWsHub())
    router = create_router(state)

    delete_endpoint = route_endpoint_with_method(router, "/api/history/{run_id}", "DELETE")
    with pytest.raises(HTTPException) as exc_info:
        await delete_endpoint("run-1")
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_delete_analyzing_run_returns_409() -> None:
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
    db = AnalyzingDB(metadata, samples, analysis)
    router = create_router(FakeState(db, FakeWsHub()))
    delete_endpoint = route_endpoint_with_method(router, "/api/history/{run_id}", "DELETE")

    with pytest.raises(HTTPException) as exc_info:
        await delete_endpoint("run-1")
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "analysis", "expected_status", "expected_detail"),
    [
        ("analyzing", {"status": "analyzing"}, 202, None),
        ("error", {"status": "error"}, 422, "Analysis failed"),
        ("complete", None, 422, "No analysis available for this run"),
    ],
)
async def test_history_insights_status_and_analysis_errors(
    status: str,
    analysis: dict[str, object] | None,
    expected_status: int,
    expected_detail: str | None,
) -> None:
    router = make_status_router(status=status, analysis=analysis, include_error_message=False)
    endpoint = route_endpoint(router, "/api/history/{run_id}/insights")

    if expected_status == 202:
        from fastapi.responses import JSONResponse

        payload = await endpoint("run-1")
        assert isinstance(payload, JSONResponse)
        assert payload.status_code == 202
        body = json.loads(payload.body)
        assert body["status"] == "analyzing"
        assert body["run_id"] == "run-1"
        return

    with pytest.raises(HTTPException) as exc_info:
        await endpoint("run-1")
    assert exc_info.value.status_code == expected_status
    assert exc_info.value.detail == expected_detail


@pytest.mark.asyncio
async def test_delete_run_returns_404_for_not_found_reason() -> None:
    router, _ = make_router_and_state(language="en")
    delete_endpoint = route_endpoint_with_method(router, "/api/history/{run_id}", "DELETE")

    with pytest.raises(HTTPException) as exc_info:
        await delete_endpoint("missing-run")
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_run_returns_generic_409_for_unknown_reason() -> None:
    @dataclass
    class LockedDB(FakeHistoryDB):
        async def adelete_run_if_safe(self, run_id: str) -> tuple[bool, str | None]:
            if run_id == "run-1":
                return False, "locked"
            return False, "not_found"

    metadata = make_metadata()
    samples = [sample(i) for i in range(5)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    router = create_router(FakeState(LockedDB(metadata, samples, analysis), FakeWsHub()))
    delete_endpoint = route_endpoint_with_method(router, "/api/history/{run_id}", "DELETE")

    with pytest.raises(HTTPException) as exc_info:
        await delete_endpoint("run-1")
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Cannot delete run at this time"


@pytest.mark.asyncio
async def test_history_insights_does_not_mutate_db_analysis() -> None:
    router, state = make_router_and_state(language="en")
    endpoint = route_endpoint(router, "/api/history/{run_id}/insights")
    original_analysis = state.history_db.analysis
    original_keys = set(original_analysis.keys())

    await endpoint("run-1")

    assert set(state.history_db.analysis.keys()) == original_keys


@pytest.mark.asyncio
async def test_history_insights_complete_response_includes_status_and_run_id() -> None:
    metadata = make_metadata()
    samples = [sample(i) for i in range(5)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    analysis.pop("status", None)
    analysis.pop("run_id", None)
    router = create_router(FakeState(FakeHistoryDB(metadata, samples, analysis), FakeWsHub()))
    endpoint = route_endpoint(router, "/api/history/{run_id}/insights")

    payload = response_payload(await endpoint("run-1"))

    assert payload["status"] == "complete"
    assert payload["run_id"] == "run-1"


@pytest.mark.asyncio
async def test_history_endpoints_preserve_analysis_case_id() -> None:
    metadata = make_metadata()
    samples = [sample(i) for i in range(5)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    analysis["case_id"] = "case-123"
    router = create_router(FakeState(FakeHistoryDB(metadata, samples, analysis), FakeWsHub()))

    history_payload = response_payload(
        await route_endpoint(router, "/api/history/{run_id}")("run-1")
    )
    insights_payload = response_payload(
        await route_endpoint(router, "/api/history/{run_id}/insights")("run-1")
    )

    assert history_payload["analysis"]["case_id"] == "case-123"
    assert insights_payload["case_id"] == "case-123"


@pytest.mark.asyncio
async def test_history_run_includes_sample_count() -> None:
    metadata = make_metadata()
    samples = [sample(i) for i in range(3)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    router = create_router(FakeState(FakeHistoryDB(metadata, samples, analysis), FakeWsHub()))

    payload = response_payload(await route_endpoint(router, "/api/history/{run_id}")("run-1"))

    assert payload["sample_count"] == 3


@pytest.mark.asyncio
async def test_history_list_includes_recorded_car_name() -> None:
    metadata = make_metadata(active_car_snapshot={"name": "Track Car"})
    samples = [sample(i) for i in range(3)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    router = create_router(FakeState(FakeHistoryDB(metadata, samples, analysis), FakeWsHub()))

    payload = response_payload(await route_endpoint(router, "/api/history")())

    assert payload["runs"][0]["car_name"] == "Track Car"


@pytest.mark.asyncio
async def test_history_endpoints_include_degraded_raw_capture_finalize_state() -> None:
    metadata = make_metadata(
        raw_capture_finalize={
            "status": "timeout",
            "queue_depth": 4,
            "error_summary": "raw capture finalize timed out",
        }
    )
    samples = [sample(i) for i in range(3)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    router = create_router(FakeState(FakeHistoryDB(metadata, samples, analysis), FakeWsHub()))

    list_payload = response_payload(await route_endpoint(router, "/api/history")())
    run_payload = response_payload(await route_endpoint(router, "/api/history/{run_id}")("run-1"))

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


@pytest.mark.asyncio
async def test_history_list_uses_nested_active_car_snapshot_name() -> None:
    metadata = make_metadata(
        active_car_snapshot={
            "id": "car-1",
            "name": "Nested Track Car",
            "type": "coupe",
        }
    )
    samples = [sample(i) for i in range(3)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    router = create_router(FakeState(FakeHistoryDB(metadata, samples, analysis), FakeWsHub()))

    payload = response_payload(await route_endpoint(router, "/api/history")())

    assert payload["runs"][0]["car_name"] == "Nested Track Car"


@pytest.mark.asyncio
async def test_history_run_projects_canonical_nested_run_context() -> None:
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
    router = create_router(FakeState(FakeHistoryDB(metadata, samples, analysis), FakeWsHub()))

    payload = response_payload(await route_endpoint(router, "/api/history/{run_id}")("run-1"))
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


@pytest.mark.asyncio
async def test_history_run_includes_error_message_for_error_status() -> None:
    router = make_status_router(
        status="error",
        analysis={"status": "error"},
        include_error_message=True,
    )

    payload = response_payload(await route_endpoint(router, "/api/history/{run_id}")("run-1"))

    assert payload["error_message"] == "Analysis failed"


@pytest.mark.asyncio
async def test_history_insights_localizes_and_adds_run_context_warnings() -> None:
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

    router, state = make_router_and_state(
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
    endpoint = route_endpoint(router, "/api/history/{run_id}/insights")

    payload = response_payload(await endpoint("run-1", "nl"))
    warnings = payload.get("warnings")
    assert isinstance(warnings, list)
    assert len(warnings) == 2
    titles = {str(item.get("title")) for item in warnings if isinstance(item, dict)}
    assert "De referentiecontext voor ordeanalyse was onvolledig voor deze run" in titles
    assert "Voertuigprofielinstellingen zijn na deze run gewijzigd" in titles


@pytest.mark.asyncio
async def test_history_run_strips_internal_analysis_fields() -> None:
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
    db = InternalFieldDB(metadata, samples, {})
    router = create_router(FakeState(db, FakeWsHub()))
    endpoint = route_endpoint(router, "/api/history/{run_id}")

    result = response_payload(await endpoint("run-1"))
    assert {"run_id", "status", "sample_count", "metadata", "analysis"}.issubset(result.keys())
    assert result.get("error_message") is None
    analysis = result.get("analysis", {})
    assert "_internal_secret" not in analysis
    assert "_report_template_data" not in analysis


@pytest.mark.asyncio
async def test_history_run_preserves_missing_optional_analysis_fields() -> None:
    metadata = make_metadata()
    samples = [sample(0)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    analysis.pop("plots", None)
    analysis.pop("analysis_metadata", None)
    db = FakeHistoryDB(metadata, samples, analysis)
    router = create_router(FakeState(db, FakeWsHub()))
    endpoint = route_endpoint(router, "/api/history/{run_id}")
    route = next(
        route
        for route in router.routes
        if getattr(route, "path", "") == "/api/history/{run_id}"
        and "GET" in getattr(route, "methods", set())
    )

    result = await endpoint("run-1")
    payload = response_payload(result)["analysis"]
    assert getattr(route, "response_model_exclude_unset", False) is True
    assert "findings" in payload
    assert "samples" not in payload
    assert "plots" not in payload
    assert "analysis_metadata" not in payload
