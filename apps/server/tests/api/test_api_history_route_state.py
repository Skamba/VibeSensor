from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
from fastapi import HTTPException

from vibesensor.analysis import summarize_run_data
from vibesensor.routes import create_router

from _history_endpoint_helpers import FakeHistoryDB
from _history_endpoint_helpers import FakeState
from _history_endpoint_helpers import FakeWsHub
from _history_endpoint_helpers import make_metadata
from _history_endpoint_helpers import make_router_and_state
from _history_endpoint_helpers import make_status_router
from _history_endpoint_helpers import route_endpoint
from _history_endpoint_helpers import route_endpoint_with_method
from _history_endpoint_helpers import sample


@pytest.mark.asyncio
async def test_delete_active_run_returns_409() -> None:
    @dataclass
    class ActiveDB(FakeHistoryDB):
        def get_active_run_id(self) -> str | None:
            return "run-1"

        def delete_run_if_safe(self, run_id: str) -> tuple[bool, str | None]:
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
        def get_run_status(self, run_id: str) -> str | None:
            if run_id == "run-1":
                return "analyzing"
            return None

        def delete_run_if_safe(self, run_id: str) -> tuple[bool, str | None]:
            if run_id == "run-1":
                return False, "analyzing"
            return False, "not_found"

        def delete_run(self, run_id: str) -> bool:
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
        def delete_run_if_safe(self, run_id: str) -> tuple[bool, str | None]:
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
async def test_history_insights_always_emits_analysis_is_current() -> None:
    @dataclass
    class NoVersionDB(FakeHistoryDB):
        def get_run(self, run_id: str) -> dict[str, object] | None:
            if run_id != "run-1":
                return None
            return {
                "run_id": run_id,
                "status": "complete",
                "metadata": self.metadata,
                "analysis": self.analysis,
            }

    metadata = make_metadata()
    samples = [sample(i) for i in range(5)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    db = NoVersionDB(metadata, samples, analysis)
    router = create_router(FakeState(db, FakeWsHub()))
    endpoint = route_endpoint(router, "/api/history/{run_id}/insights")

    payload = await endpoint("run-1")
    assert "analysis_is_current" in payload
    assert payload["analysis_is_current"] is False


@pytest.mark.asyncio
async def test_history_run_strips_internal_analysis_fields() -> None:
    @dataclass
    class InternalFieldDB(FakeHistoryDB):
        def get_run(self, run_id: str) -> dict[str, object] | None:
            if run_id != "run-1":
                return None
            return {
                "run_id": run_id,
                "status": "complete",
                "metadata": self.metadata,
                "analysis": {
                    "some_field": 42,
                    "_internal_secret": "should-not-appear",
                    "_report_template_data": {"lang": "en"},
                },
            }

    metadata = make_metadata()
    samples = [sample(0)]
    db = InternalFieldDB(metadata, samples, {})
    router = create_router(FakeState(db, FakeWsHub()))
    endpoint = route_endpoint(router, "/api/history/{run_id}")

    result = await endpoint("run-1")
    assert isinstance(result, dict)
    analysis = result.get("analysis", {})
    assert "_internal_secret" not in analysis
    assert "_report_template_data" not in analysis
    assert analysis.get("some_field") == 42


@pytest.mark.asyncio
async def test_history_insights_analyzing_returns_202_json_response() -> None:
    from fastapi.responses import JSONResponse

    router = make_status_router(
        status="analyzing", analysis={"status": "analyzing"}, include_error_message=False
    )
    endpoint = route_endpoint(router, "/api/history/{run_id}/insights")
    result = await endpoint("run-1")
    assert isinstance(result, JSONResponse)
    assert result.status_code == 202
    body = json.loads(result.body)
    assert body["status"] == "analyzing"
    assert body["run_id"] == "run-1"