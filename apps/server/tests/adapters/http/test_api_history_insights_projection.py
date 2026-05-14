from __future__ import annotations

import pytest
from _history_endpoint_helpers import make_app_and_state, make_metadata, make_status_app, sample
from fastapi.testclient import TestClient

from vibesensor.adapters.analysis_summary import summarize_run_data
from vibesensor.domain import CarSnapshot


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


def test_history_insights_preserves_analysis_case_id() -> None:
    metadata = make_metadata()
    samples = [sample(i) for i in range(5)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    analysis["case_id"] = "case-123"
    app, _ = make_app_and_state(
        language="en", metadata=metadata, samples=samples, analysis=analysis
    )

    with TestClient(app) as client:
        payload = client.get("/api/history/run-1/insights").json()

    assert payload["case_id"] == "case-123"


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
    assert "De referentiecontext voor ordeanalyse was onvolledig voor deze meting" in titles
    assert "Voertuigprofielinstellingen zijn na deze meting gewijzigd" in titles
